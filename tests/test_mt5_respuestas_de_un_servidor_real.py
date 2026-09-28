"""Lo que contesta un servidor real y el camino de la demo nunca vio.

Salio de la auditoria del 27/09, antes de fondear. Cada caso esta reproducido
con el paquete MetaTrader5 instalado o con sus constantes:

- `order_send` que devuelve None. El paquete lo hace ante un corte del canal
  con la terminal, y un corte al RECIBIR la respuesta no deshace lo que el
  servidor ya ejecuto. Se reenviaba con el modo de llenado siguiente: podia
  abrir una SEGUNDA posicion real que el bot no gestionaba.
- MetaTrader que se reinicia con el bot andando: el paquete no se reengancha
  solo, y todo fallaba hasta reiniciar el bot a mano.
- La terminal en la otra cuenta: `posicion_existe` contestaba "no esta" y el
  motor borraba del registro las posiciones REALES vivas.
- Recotizaciones, llenados parciales y una lista de simbolos que todavia no
  bajo.
"""

from __future__ import annotations

import asyncio
import sys

from tct.brokers.mt5_native import MAGIA, MT5NativeBroker
from tct.signals.models import OrderType, Side
from tests.fake_mt5 import TRADE_RETCODE_DONE, FakeMT5, FakeResult, enchufar

REAL = 516648640
DEMO = 592098515


class Ajustes:
    mt5_login = str(REAL)
    mt5_password = "x"
    mt5_server = "FxPro-MT5 Live"
    mt5_path = ""
    mt5_broker_profile = "fxpro"
    max_lot = 0.05
    default_lot = 0.05
    allow_live_trading = True
    trading_mode = "LIVE"
    is_live = True


class ServidorReal(FakeMT5):
    """FxPro: el oro se llama GOLD, la cuenta es la real, y se le pueden
    programar las respuestas raras de un servidor de verdad."""

    def __init__(self):
        super().__init__({"GOLD": {"bid": 4431.5, "ask": 4432.0}})
        self.cuenta_login = REAL
        # La orden se EJECUTA pero la respuesta se pierde en el camino.
        self.respuesta_perdida = False
        # order_send devuelve None sin ejecutar nada.
        self.sin_respuesta = False
        # Cuantas veces seguidas contestar "recotizacion" (10004).
        self.recotizar = 0
        # El canal con la terminal, cortado: todo devuelve None hasta initialize().
        self.canal_cortado = False
        # Las consultas de posiciones fallan (None).
        self.posiciones_ciegas = False
        self.initialize_llamadas = 0

    # -- El canal ------------------------------------------------------------

    def last_error(self):
        return (-10004, "No IPC connection") if self.canal_cortado else (1, "Success")

    def initialize(self, **_kwargs):
        self.initialize_llamadas += 1
        self.canal_cortado = False
        return True

    def login(self, *_a, **_k):
        return not self.canal_cortado

    def shutdown(self):
        pass

    def terminal_info(self):
        if self.canal_cortado:
            return None

        class Terminal:
            trade_allowed = True
        return Terminal()

    def account_info(self):
        if self.canal_cortado:
            return None
        login = self.cuenta_login

        class Cuenta:
            equity = 500.0
            balance = 500.0
            server = "FxPro-MT5 Live"
            trade_mode = 2

            def _asdict(self):
                return {"login": login, "trade_mode": 2, "server": "FxPro-MT5 Live"}
        Cuenta.login = login
        return Cuenta()

    def positions_get(self, ticket=None, symbol=None):
        if self.canal_cortado or self.posiciones_ciegas:
            return None
        return super().positions_get(ticket=ticket, symbol=symbol)

    def symbol_info_tick(self, name):
        return None if self.canal_cortado else super().symbol_info_tick(name)

    def symbol_info(self, name):
        return None if self.canal_cortado else super().symbol_info(name)

    # -- Ordenes -------------------------------------------------------------

    def order_send(self, request):
        if self.canal_cortado:
            self.enviados.append(dict(request))
            return None
        if self.sin_respuesta:
            self.enviados.append(dict(request))
            return None
        if self.recotizar > 0 and "position" not in request:
            self.recotizar -= 1
            self.enviados.append(dict(request))
            return FakeResult(10004, comment="Requote")
        resultado = super().order_send(request)
        if self.respuesta_perdida:
            return None
        return resultado


def armar():
    terminal = ServidorReal()
    return enchufar(MT5NativeBroker(Ajustes()), terminal), terminal


def abrir(broker):
    return asyncio.run(broker.open_order(
        symbol="XAUUSD", side=Side.BUY, order_type=OrderType.MARKET,
        lot=0.05, entry=4432.0, stop_loss=4424.0, take_profit=4436.0))


def aperturas(terminal):
    return [r for r in terminal.enviados if "position" not in r]


# --------------------------------------------------------------------------
# order_send sin respuesta: nunca se reenvia
# --------------------------------------------------------------------------


def test_sin_respuesta_pero_entro_no_se_reenvia_y_se_gestiona():
    broker, terminal = armar()
    terminal.respuesta_perdida = True

    resultado = abrir(broker)

    assert len(aperturas(terminal)) == 1, "reenvio la orden: pudo abrir dos"
    assert len(terminal.posiciones_abiertas()) == 1
    assert resultado.ok
    assert resultado.ticket == terminal.posiciones_abiertas()[0].ticket
    assert resultado.lot == 0.05


def test_sin_respuesta_y_no_entro_no_se_reenvia():
    broker, terminal = armar()
    terminal.sin_respuesta = True

    resultado = abrir(broker)

    assert len(aperturas(terminal)) == 1
    assert not resultado.ok
    assert "no esta en la cuenta" in resultado.reason


def test_sin_respuesta_y_sin_poder_mirar_la_cuenta_lo_dice():
    """El unico caso en que puede quedar una posicion sin registrar: que se vea."""
    broker, terminal = armar()
    terminal.sin_respuesta = True
    terminal.posiciones_ciegas = True

    resultado = abrir(broker)

    assert len(aperturas(terminal)) == 1
    assert not resultado.ok
    assert "mira MetaTrader" in resultado.reason


def test_una_posicion_que_ya_estaba_no_se_confunde_con_la_nueva():
    broker, terminal = armar()
    previa = abrir(broker)
    terminal.sin_respuesta = True

    resultado = abrir(broker)

    assert previa.ok and not resultado.ok
    assert len(terminal.posiciones_abiertas()) == 1


def test_un_cierre_sin_respuesta_no_se_reenvia():
    """Un parcial mandado dos veces achicaba la posicion dos veces."""
    broker, terminal = armar()
    abierta = abrir(broker)
    terminal.respuesta_perdida = True

    resultado = asyncio.run(broker.close_position(ticket=abierta.ticket, symbol="XAUUSD",
                                                  fraction=0.4))

    cierres = [r for r in terminal.enviados if "position" in r]
    assert len(cierres) == 1
    assert resultado.ok and resultado.lot == 0.02
    assert terminal.posiciones_abiertas()[0].volume == 0.03


# --------------------------------------------------------------------------
# Lo demas que contesta un servidor real
# --------------------------------------------------------------------------


def test_una_recotizacion_se_reintenta_con_el_precio_nuevo():
    broker, terminal = armar()
    terminal.recotizar = 1
    terminal.simbolos["GOLD"]["ask"] = 4432.0

    def mover_el_precio(nombre):
        terminal.simbolos["GOLD"]["ask"] = 4432.4
        return FakeMT5.symbol_info_tick(terminal, nombre)
    terminal.symbol_info_tick = mover_el_precio

    resultado = abrir(broker)

    assert resultado.ok
    assert len(aperturas(terminal)) == 2
    assert aperturas(terminal)[-1]["price"] == 4432.4


def test_las_recotizaciones_tienen_un_limite():
    broker, terminal = armar()
    terminal.recotizar = 10

    resultado = abrir(broker)

    assert not resultado.ok
    assert len(aperturas(terminal)) == 3
    assert terminal.posiciones_abiertas() == []


def test_un_llenado_parcial_es_una_posicion_abierta():
    broker, terminal = armar()
    terminal.llenado = 0.6

    def parcial(request):
        resultado = FakeMT5.order_send(terminal, request)
        resultado.retcode = 10010
        return resultado
    terminal.order_send = parcial

    resultado = abrir(broker)

    assert resultado.ok
    assert resultado.lot == 0.03


def test_la_lista_de_simbolos_vacia_no_deja_el_oro_muerto_toda_la_sesion():
    broker, terminal = armar()
    todos = terminal.symbols_get
    terminal.symbols_get = lambda: ()

    assert broker._resolver_contra_broker("XAUUSD") is None
    terminal.symbols_get = todos
    assert broker._resolver_contra_broker("XAUUSD") == "GOLD"


# --------------------------------------------------------------------------
# La terminal en la otra cuenta
# --------------------------------------------------------------------------


def test_en_otra_cuenta_no_se_dice_que_la_posicion_no_existe():
    broker, terminal = armar()
    abierta = abrir(broker)
    terminal.cuenta_login = DEMO

    assert asyncio.run(broker.posicion_existe(abierta.ticket)) is None

    terminal.cuenta_login = REAL
    assert asyncio.run(broker.posicion_existe(abierta.ticket)) is True


# --------------------------------------------------------------------------
# MetaTrader que se reinicia
# --------------------------------------------------------------------------


def _con_el_paquete_falso(monkeypatch, terminal):
    # `_connect_sync` hace `import MetaTrader5`: que encuentre la terminal falsa.
    monkeypatch.setitem(sys.modules, "MetaTrader5", terminal)


def test_despues_de_un_reinicio_la_orden_reconecta_sola(monkeypatch):
    broker, terminal = armar()
    _con_el_paquete_falso(monkeypatch, terminal)
    terminal.canal_cortado = True

    resultado = abrir(broker)

    assert terminal.initialize_llamadas == 1
    assert resultado.ok, resultado.reason
    assert len(aperturas(terminal)) == 1


def test_el_vigilante_reconecta_sin_esperar_una_senal(monkeypatch):
    broker, terminal = armar()
    _con_el_paquete_falso(monkeypatch, terminal)
    terminal.canal_cortado = True

    asyncio.run(broker.revisar_conexion())

    assert terminal.initialize_llamadas == 1
    assert terminal.terminal_info() is not None


def test_si_volvio_en_otra_cuenta_no_reconecta(monkeypatch):
    broker, terminal = armar()
    _con_el_paquete_falso(monkeypatch, terminal)
    terminal.canal_cortado = True
    terminal.cuenta_login = DEMO

    resultado = abrir(broker)

    assert not resultado.ok
    assert aperturas(terminal) == []


def test_con_la_terminal_viva_el_vigilante_no_toca_nada(monkeypatch):
    broker, terminal = armar()
    _con_el_paquete_falso(monkeypatch, terminal)

    asyncio.run(broker.revisar_conexion())

    assert terminal.initialize_llamadas == 0


def test_las_ordenes_llevan_la_marca_del_bot():
    broker, terminal = armar()

    abrir(broker)

    assert aperturas(terminal)[0]["magic"] == MAGIA
    assert terminal.posiciones_abiertas()[0].magic == MAGIA
    assert TRADE_RETCODE_DONE == 10009
