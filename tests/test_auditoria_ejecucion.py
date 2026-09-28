"""Lo que encontro el ataque a los arreglos de 596a891 (auditoria del 28/09).

Cada test reproduce un caso que la version anterior resolvia mal, y los cuatro
podian costar plata en la cuenta real:

1. Recotizacion: el reintento con el precio nuevo se salteaba el filtro de
   entrada tarde. Una entrada 4432 abrio a 4440.5, con el tope en 0.05%.
2. Un cierre TOTAL que el broker llenaba a medias se daba por cerrado: el
   resto quedaba vivo y fuera del registro.
3. Una orden sin respuesta porque MetaTrader se reinicio: no se reconectaba
   para mirar, se daba por "no entro" y quedaba una posicion real sin
   gestionar. Con tope 2 llegaron a quedar 3 abiertas.
4. Una pendiente del bot que se disparaba mientras se esperaba la respuesta
   se tomaba por la orden nueva: dos senales sobre una posicion.
"""

from __future__ import annotations

import asyncio

from tct.brokers.mt5_native import MAGIA, MT5NativeBroker
from tct.engine import Engine
from tct.signals.models import OrderType, Side
from tct.store import Store
from tests.fake_mt5 import FakeMT5, FakeResult, enchufar
from tests.test_engine import build_settings, send

SENAL = "XAUUSD BUY\nEntry 4432\nSL 4424\nTP 4436"


class Terminal(FakeMT5):
    """Un MetaTrader que puede recotizar, perder respuestas y cortarse."""

    def __init__(self):
        super().__init__({"XAUUSD": {"bid": 4431.5, "ask": 4432.5}})
        self.recotizar = 0
        self.al_recotizar = None  # que le pasa al precio en cada recotizacion
        self.respuesta_perdida = False
        self.sin_ejecutar = False
        self.canal_cortado = False
        self.cortar_al_contestar = False
        self.initialize_llamadas = 0

    def last_error(self):
        return (-10004, "No IPC connection") if self.canal_cortado else (1, "Success")

    def initialize(self, **_k):
        self.initialize_llamadas += 1
        self.canal_cortado = False
        return True

    def login(self, *_a, **_k):
        return True

    def shutdown(self):
        pass

    def terminal_info(self):
        if self.canal_cortado:
            return None

        class T:
            trade_allowed = True
        return T()

    def account_info(self):
        if self.canal_cortado:
            return None
        cuenta = super().account_info()
        datos = {"login": cuenta.login, "server": cuenta.server, "trade_mode": 0}
        cuenta._asdict = lambda: datos
        return cuenta

    def positions_get(self, ticket=None, symbol=None):
        return None if self.canal_cortado else super().positions_get(ticket=ticket,
                                                                      symbol=symbol)

    def orders_get(self, ticket=None, symbol=None):
        return None if self.canal_cortado else super().orders_get(ticket=ticket,
                                                                   symbol=symbol)

    def order_send(self, request):
        if self.canal_cortado:
            return None
        if self.recotizar > 0 and "position" not in request:
            self.recotizar -= 1
            self.enviados.append(dict(request))
            if self.al_recotizar:
                self.al_recotizar()
            return FakeResult(10004, comment="Requote")
        if self.sin_ejecutar:
            self.enviados.append(dict(request))
            return None
        resultado = super().order_send(request)
        if self.cortar_al_contestar:
            self.canal_cortado = True
            return None
        return None if self.respuesta_perdida else resultado

    def aperturas(self):
        return [r for r in self.enviados if "position" not in r]


def armar(tmp_path, **overrides):
    overrides.setdefault("max_spread_from_entry_pct", 0.05)
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    terminal = Terminal()
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), terminal))
    return engine, store, terminal


# --------------------------------------------------------------------------
# 1. Recotizacion
# --------------------------------------------------------------------------


def test_recotizacion_con_el_precio_todavia_bien_se_reintenta_y_abre(tmp_path):
    engine, store, terminal = armar(tmp_path)
    terminal.recotizar = 1

    resultado = send(engine, SENAL, message_id=1)

    assert resultado["status"] == "aceptada", resultado
    assert len(terminal.aperturas()) == 2
    assert len(store.open_positions()) == 1


def test_recotizacion_con_el_precio_ya_lejos_no_abre(tmp_path):
    """El caso reproducido: el precio sube 4 puntos por recotizacion."""
    engine, store, terminal = armar(tmp_path)
    terminal.recotizar = 2

    def subir():
        terminal.simbolos["XAUUSD"]["bid"] += 4.0
        terminal.simbolos["XAUUSD"]["ask"] += 4.0
    terminal.al_recotizar = subir

    resultado = send(engine, SENAL, message_id=1)

    assert resultado["status"] == "apertura_fallida", resultado
    assert len(terminal.aperturas()) == 1, "reintento con el precio fuera del filtro"
    assert terminal.posiciones_abiertas() == []
    assert "precio se movio" in resultado["reason"]


def test_las_recotizaciones_tienen_un_limite(tmp_path):
    engine, store, terminal = armar(tmp_path)
    terminal.recotizar = 10

    resultado = send(engine, SENAL, message_id=1)

    assert resultado["status"] == "apertura_fallida"
    assert len(terminal.aperturas()) == 3  # la primera y dos reintentos
    assert terminal.posiciones_abiertas() == []


# --------------------------------------------------------------------------
# 2. Cierre total llenado a medias
# --------------------------------------------------------------------------


def test_un_cierre_total_llenado_a_medias_no_saca_la_posicion(tmp_path):
    engine, store, terminal = armar(tmp_path, default_lot=0.05, max_lot=0.05)
    send(engine, SENAL, message_id=1)
    original = FakeMT5.order_send

    def cierre_a_medias(request):
        if "position" in request:
            request = dict(request, volume=0.02)
            resultado = original(terminal, request)
            resultado.retcode = 10010
            return resultado
        return original(terminal, request)
    terminal.order_send = cierre_a_medias

    resultado = send(engine, "cerrar XAUUSD", message_id=2)

    assert terminal.posiciones_abiertas()[0].volume == 0.03
    abiertas = store.open_positions()
    assert len(abiertas) == 1, "la saco del registro con 0.03 lotes vivos"
    assert abs(abiertas[0].lot * abiertas[0].remaining_fraction - 0.03) < 1e-9
    assert resultado["status"] == "cierre_parcial_fallido"


# --------------------------------------------------------------------------
# 3. Orden sin respuesta
# --------------------------------------------------------------------------


def test_sin_respuesta_porque_metatrader_se_reinicio_reconecta_y_la_encuentra(
        tmp_path, monkeypatch):
    engine, store, terminal = armar(tmp_path)
    # Reconectar es volver a importar el paquete: el de este test es la terminal.
    monkeypatch.setitem(__import__("sys").modules, "MetaTrader5", terminal)
    terminal.cortar_al_contestar = True

    resultado = send(engine, SENAL, message_id=1)

    assert terminal.initialize_llamadas >= 1, "no reconecto para mirar"
    assert resultado["status"] == "aceptada", resultado
    assert len(store.open_positions()) == 1
    assert len(terminal.aperturas()) == 1


def test_una_orden_que_aparece_tarde_se_toma_bajo_gestion_y_cuenta_para_el_tope(tmp_path):
    engine, store, terminal = armar(tmp_path, max_open_trades=2,
                                    max_positions_per_symbol=2)
    terminal.sin_ejecutar = True

    primera = send(engine, SENAL, message_id=1)
    assert primera["status"] == "apertura_fallida"
    assert "sigue buscando" in primera["reason"]

    # Aparece despues (el servidor la ejecuto tarde).
    terminal.sin_ejecutar = False
    FakeMT5.order_send(terminal, {
        "action": terminal.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": 0.01,
        "type": terminal.ORDER_TYPE_BUY, "price": 4432.5, "magic": MAGIA,
        "sl": 4424.0, "tp": 4436.0,
    })
    asyncio.run(engine.revisar_el_broker())

    assert len(store.open_positions()) == 1, "no la tomo bajo gestion"
    assert store.open_positions()[0].stop_loss == 4424.0

    send(engine, SENAL.replace("4432", "4433"), message_id=2)
    send(engine, SENAL.replace("4432", "4431"), message_id=3)

    assert len(terminal.posiciones_abiertas()) == 2, "se paso de MAX_OPEN_TRADES"


def test_una_orden_que_nunca_aparece_se_deja_de_buscar(tmp_path, monkeypatch):
    from tct import engine as modulo
    monkeypatch.setattr(modulo, "BUSCAR_SIN_CONFIRMAR", modulo.timedelta(seconds=-1))
    engine, store, terminal = armar(tmp_path)
    terminal.sin_ejecutar = True

    send(engine, SENAL, message_id=1)
    asyncio.run(engine.revisar_el_broker())

    assert engine._sin_confirmar == []
    assert store.open_positions() == []


# --------------------------------------------------------------------------
# 4. Una pendiente propia que se dispara durante la espera
# --------------------------------------------------------------------------


def test_una_pendiente_propia_que_se_dispara_no_se_toma_por_la_orden_nueva(tmp_path):
    settings = build_settings(tmp_path)
    terminal = Terminal()
    broker = enchufar(MT5NativeBroker(settings), terminal)
    pendiente = terminal.poner_pendiente(900001, symbol="XAUUSD", volume=0.01)
    pendiente.magic = MAGIA

    def se_dispara_y_no_contesta(request):
        terminal.enviados.append(dict(request))
        del terminal._pendientes[900001]
        terminal._posiciones[900001] = pendiente  # mismo ticket, ahora posicion
        return None
    terminal.order_send = se_dispara_y_no_contesta

    resultado = asyncio.run(broker.open_order(
        symbol="XAUUSD", side=Side.BUY, order_type=OrderType.MARKET, lot=0.01,
        entry=4432.0, stop_loss=4424.0, take_profit=4436.0))

    assert not resultado.ok, "tomo la pendiente disparada como la orden nueva"
    assert resultado.raw.get("sin_confirmar")


def test_la_orden_que_aparecio_cuenta_aunque_el_vigilante_no_haya_pasado(tmp_path):
    """La senal siguiente puede llegar antes que la vuelta del vigilante (30 s):
    la orden que aparecio tiene que estar registrada antes de mirar el tope."""
    engine, store, terminal = armar(tmp_path, max_open_trades=1,
                                    max_positions_per_symbol=1)
    terminal.sin_ejecutar = True
    send(engine, SENAL, message_id=1)
    terminal.sin_ejecutar = False
    FakeMT5.order_send(terminal, {
        "action": terminal.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": 0.01,
        "type": terminal.ORDER_TYPE_BUY, "price": 4432.5, "magic": MAGIA,
        "sl": 4424.0, "tp": 4436.0,
    })

    resultado = send(engine, SENAL.replace("4432", "4433"), message_id=2)

    assert resultado["status"] == "rechazada", "abrio una de mas"
    assert len(terminal.posiciones_abiertas()) == 1
