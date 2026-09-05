"""Una terminal MetaTrader 5 falsa, para probar el camino que de verdad opera.

POR QUE EXISTE
--------------
El punto ciego historico de este repo: casi todos los tests corren contra el
broker de PAPEL, que acepta cualquier cosa, nunca devuelve ok=False y no ajusta
volumenes. `_normalize_volume`, la negociacion de filling mode y el redondeo al
lote minimo del instrumento viven en `mt5_native.py` y no los ejercitaba nadie.

Este modulo no es un mock que devuelve lo que se le pide: reproduce las reglas
del broker que importan y que causan bugs de plata.

  - El volumen se ajusta al paso y se SUBE al minimo del instrumento. Un
    "cerrar la mitad" de 0.01 termina cerrando 0.01, o sea el 100%.
  - `order_send` devuelve retcode, y 10009 (DONE) es el unico que salio bien.
  - Las posiciones existen: se abren, se cierran parcialmente y desaparecen.

No pretende ser MT5 completo. Pretende que un bug de estos no pueda pasar con
la suite en verde.
"""

from __future__ import annotations

from typing import Any

# Valores reales de la API de MT5. Importan poco entre ellos mientras sean
# consistentes, salvo DONE, que es el que distingue el exito del fracaso.
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_INVALID_FILL = 10030
TRADE_RETCODE_INVALID_VOLUME = 10014
TRADE_RETCODE_INVALID_STOPS = 10016
TRADE_RETCODE_NO_MONEY = 10019
# Lo devuelve MT5 cuando lo que se pide YA esta puesto. No es un fallo: es
# la prueba de que el cambio anterior entro. Pasa siempre en produccion,
# porque el canal edita sus mensajes y el bot reprocesa las ediciones.
TRADE_RETCODE_NO_CHANGES = 10025


class FakeSymbolInfo:
    def __init__(self, name, volume_min=0.01, volume_step=0.01, volume_max=100.0):
        self.name = name
        self.visible = True
        self.volume_min = volume_min
        self.volume_step = volume_step
        self.volume_max = volume_max
        self.filling_mode = 2  # SYMBOL_FILLING_IOC


class FakeTick:
    def __init__(self, bid, ask):
        self.bid = bid
        self.ask = ask


class FakeResult:
    def __init__(self, retcode, order=0, deal=0, price=0.0, comment="", volume=0.0):
        self.retcode = retcode
        self.order = order
        self.deal = deal
        self.price = price
        # El volumen CONFIRMADO por el broker. MT5 lo devuelve siempre, y no
        # tiene por que coincidir con el pedido: un llenado parcial ejecuta
        # menos. Sin este campo, el fake no podia reproducir esa divergencia.
        self.volume = volume
        self.comment = comment or ("ok" if retcode == TRADE_RETCODE_DONE else "rechazado")


class FakePosition:
    def __init__(self, ticket, symbol, volume, tipo, sl=0.0, tp=0.0):
        self.ticket = ticket
        self.symbol = symbol
        self.volume = volume
        self.type = tipo
        self.sl = sl
        self.tp = tp


class FakeMT5:
    """La terminal. Se enchufa con `broker._mt5 = fake; broker._ready = True`."""

    # Constantes que lee mt5_native.py.
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 2
    TRADE_ACTION_PENDING = 5
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5
    ORDER_TIME_GTC = 0
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    TRADE_RETCODE_DONE = TRADE_RETCODE_DONE
    TRADE_RETCODE_INVALID_FILL = TRADE_RETCODE_INVALID_FILL
    TRADE_RETCODE_NO_CHANGES = TRADE_RETCODE_NO_CHANGES

    def __init__(self, simbolos: dict[str, dict[str, Any]] | None = None) -> None:
        # {"XAUUSD": {"bid": 4438.0, "ask": 4438.5, "volume_min": 0.01, ...}}
        self.simbolos = simbolos or {
            "XAUUSD": {"bid": 4438.0, "ask": 4438.5},
        }
        self._posiciones: dict[int, FakePosition] = {}
        self._proximo_ticket = 500_001
        # Todo lo que se le mando: es lo que permite afirmar que volumen SALIO
        # de verdad, en vez de creerle al numero que el motor dice tener.
        self.enviados: list[dict[str, Any]] = []
        # Si se llena, la proxima order_send devuelve este retcode.
        self.rechazar_con: int | None = None
        # Fraccion del volumen pedido que se llena de verdad. 1.0 = todo.
        # Bajarla reproduce un llenado parcial, que es lo que hace que el
        # volumen pedido y el ejecutado dejen de coincidir.
        self.llenado = 1.0

    # -- Consultas ---------------------------------------------------------

    def _info(self, name):
        datos = self.simbolos.get(name)
        if datos is None:
            return None
        return FakeSymbolInfo(
            name,
            volume_min=datos.get("volume_min", 0.01),
            volume_step=datos.get("volume_step", 0.01),
            volume_max=datos.get("volume_max", 100.0),
        )

    def symbol_info(self, name):
        return self._info(name)

    def symbol_select(self, name, activar=True):
        return name in self.simbolos

    def symbols_get(self):
        return [FakeSymbolInfo(n) for n in self.simbolos]

    def symbol_info_tick(self, name):
        datos = self.simbolos.get(name)
        if datos is None:
            return None
        return FakeTick(datos.get("bid", 0.0), datos.get("ask", 0.0))

    def positions_get(self, ticket=None):
        if ticket is None:
            return tuple(self._posiciones.values())
        posicion = self._posiciones.get(ticket)
        return (posicion,) if posicion else ()

    def account_info(self):
        class Cuenta:
            equity = 10_000.0
            balance = 10_000.0
            server = "FakeBroker-Demo"
        return Cuenta()

    def last_error(self):
        return (0, "sin error")

    # -- Ordenes -----------------------------------------------------------

    def order_send(self, request):
        self.enviados.append(dict(request))

        if self.rechazar_con is not None:
            return FakeResult(self.rechazar_con, comment="rechazo forzado por el test")

        if request["action"] == self.TRADE_ACTION_SLTP:
            posicion = self._posiciones.get(request["position"])
            if posicion is None:
                return FakeResult(TRADE_RETCODE_INVALID_STOPS, comment="posicion inexistente")
            nuevo_sl = request.get("sl", 0.0)
            if posicion.sl == nuevo_sl:
                # Sin esto el fake devolvia DONE y los tests del camino de
                # mover el stop pasaban sin ejercitar el caso que importa.
                return FakeResult(TRADE_RETCODE_NO_CHANGES,
                                  comment="No changes")
            posicion.sl = nuevo_sl
            return FakeResult(TRADE_RETCODE_DONE)

        # Cerrar: un DEAL que nombra una posicion existente.
        if request["action"] == self.TRADE_ACTION_DEAL and "position" in request:
            posicion = self._posiciones.get(request["position"])
            if posicion is None:
                return FakeResult(TRADE_RETCODE_INVALID_VOLUME, comment="posicion inexistente")
            volumen = request["volume"]
            # El broker no puede cerrar mas de lo que hay abierto.
            cerrado = min(volumen, posicion.volume)
            posicion.volume = round(posicion.volume - cerrado, 8)
            if posicion.volume <= 0:
                del self._posiciones[request["position"]]
            return FakeResult(TRADE_RETCODE_DONE, price=request.get("price", 0.0),
                              volume=cerrado)

        # Abrir.
        ticket = self._proximo_ticket
        self._proximo_ticket += 1
        es_compra = request["type"] in (self.ORDER_TYPE_BUY, self.ORDER_TYPE_BUY_LIMIT,
                                        self.ORDER_TYPE_BUY_STOP)
        llenado = round(request["volume"] * self.llenado, 8)
        self._posiciones[ticket] = FakePosition(
            ticket, request["symbol"], llenado,
            self.POSITION_TYPE_BUY if es_compra else self.POSITION_TYPE_SELL,
            sl=request.get("sl", 0.0), tp=request.get("tp", 0.0),
        )
        return FakeResult(TRADE_RETCODE_DONE, order=ticket,
                          price=request.get("price", 0.0), volume=llenado)

    # -- Ayudas para los tests --------------------------------------------

    def volumenes_enviados(self) -> list[float]:
        return [r["volume"] for r in self.enviados if "volume" in r]

    def posiciones_abiertas(self) -> list[FakePosition]:
        return list(self._posiciones.values())


def enchufar(broker, fake: FakeMT5):
    """Conecta un MT5NativeBroker a una terminal falsa, sin red ni MetaTrader."""
    broker._mt5 = fake
    broker._ready = True
    broker._symbol_cache = {}
    return broker
