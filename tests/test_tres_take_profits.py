"""Una posicion por take profit.

POR QUE
-------
MT5 admite UN take profit por posicion. El canal manda tres (+4, +6 y +8 puntos
en oro), y el bot mandaba solo el mas cercano: los otros dos no existian para
el broker. Perseguir los tres exige tres operaciones, no hay otra forma de
expresarlo.

LO QUE HAY QUE TENER PRESENTE
-----------------------------
El lote minimo (0.01) NO se puede partir. Tres posiciones son 0.03, o sea que
la senal vale el TRIPLE. Por eso arranca en 1 -el comportamiento historico-,
vive en el .env, y se imprime al arrancar.

Y hay una interaccion que no es obvia: la posicion del TP mas lejano puede
quedar viva horas. Con la regla vieja de "una posicion por simbolo" eso
bloquearia TODAS las senales siguientes de un canal que opera un solo
instrumento, que es justo el caso. De ahi sale MAX_POSITIONS_PER_SYMBOL.
"""

from __future__ import annotations

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings, send

ORO = 4438.0
SENAL = "XAUUSD BUY\nEntry 4438\nSL 4420\nTP1 4442\nTP2 4444\nTP3 4446"
SENAL_UN_TP = "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4442"
SENAL_2 = "XAUUSD BUY\nEntry 4439\nSL 4421\nTP1 4443\nTP2 4445\nTP3 4447"


class Aviso:
    def __init__(self):
        self.mensajes = []

    def enabled(self):
        return True

    async def send(self, texto):
        self.mensajes.append(texto)


def armar(tmp_path, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5}})
    aviso = Aviso()
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), fake), aviso)
    return store, engine, fake, aviso


# --------------------------------------------------------------------------
# Lo que no hay que romper: el valor de fabrica
# --------------------------------------------------------------------------

def test_de_fabrica_sigue_abriendo_una_sola(tmp_path):
    """POSITIONS_PER_SIGNAL=1 tiene que ser exactamente lo de siempre."""
    store, engine, _, _ = armar(tmp_path)

    send(engine, SENAL, message_id=1)

    assert len(store.open_positions()) == 1


def test_de_fabrica_manda_el_tp_mas_cercano(tmp_path):
    store, engine, fake, _ = armar(tmp_path)

    send(engine, SENAL, message_id=1)

    assert fake.posiciones_abiertas()[0].tp == 4442.0


# --------------------------------------------------------------------------
# Tres posiciones, una por objetivo
# --------------------------------------------------------------------------

def test_abre_una_posicion_por_take_profit(tmp_path):
    store, engine, _, _ = armar(tmp_path, positions_per_signal=3)

    send(engine, SENAL, message_id=1)

    assert len(store.open_positions()) == 3


def test_cada_posicion_persigue_un_objetivo_distinto(tmp_path):
    """Si las tres fueran al mismo TP no habria ninguna razon para abrir tres."""
    store, engine, fake, _ = armar(tmp_path, positions_per_signal=3)

    send(engine, SENAL, message_id=1)

    enviados = sorted(p.tp for p in fake.posiciones_abiertas())
    assert enviados == [4442.0, 4444.0, 4446.0]


def test_las_tres_comparten_el_mismo_stop(tmp_path):
    """El SL es uno solo en la senal: son tres salidas del mismo trade, no tres
    trades distintos."""
    _, engine, fake, _ = armar(tmp_path, positions_per_signal=3)

    send(engine, SENAL, message_id=1)

    assert {p.sl for p in fake.posiciones_abiertas()} == {4420.0}


def test_no_abre_mas_posiciones_que_objetivos(tmp_path):
    """Una cuarta posicion sin TP propio no persigue nada: solo duplica riesgo."""
    store, engine, _, _ = armar(tmp_path, positions_per_signal=3)

    send(engine, SENAL_UN_TP, message_id=1)

    assert len(store.open_positions()) == 1


def test_el_cupo_diario_cuenta_senales_y_no_posiciones(tmp_path):
    """Tres posiciones persiguiendo los tres TP de un mismo mensaje son UNA
    senal. Contarlas por separado vaciaria MAX_SIGNALS_PER_DAY tres veces mas
    rapido sin que el canal haya mandado nada mas."""
    store, engine, _, _ = armar(tmp_path, positions_per_signal=3)

    send(engine, SENAL, message_id=1)

    assert store.signals_today() == 1


def test_no_se_pasa_de_max_open_trades(tmp_path):
    """`evaluate_open` mira si entra UNA. Con un solo lugar libre y una senal
    que quiere abrir tres, el techo se cruzaria igual."""
    store, engine, _, _ = armar(tmp_path, positions_per_signal=3, max_open_trades=2)

    send(engine, SENAL, message_id=1)

    assert len(store.open_positions()) == 2


def test_el_aviso_dice_el_lote_total(tmp_path):
    """Tres veces el lote es tres veces el riesgo, y tiene que verse en el
    aviso: el estado de cuenta del dia siguiente es tarde."""
    _, engine, _, aviso = armar(tmp_path, positions_per_signal=3)

    send(engine, SENAL, message_id=1)

    assert "3 posiciones" in aviso.mensajes[-1]
    assert "0.03" in aviso.mensajes[-1]


# --------------------------------------------------------------------------
# El tope por instrumento
# --------------------------------------------------------------------------

def test_de_fabrica_una_senal_nueva_sigue_bloqueada(tmp_path):
    """MAX_POSITIONS_PER_SYMBOL=1 es el comportamiento historico."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL, message_id=1)

    resultado = send(engine, SENAL_2, message_id=2)

    assert resultado["status"] == "rechazada"
    assert any("Ya hay una posicion abierta" in r for r in resultado["reasons"])


def test_en_cero_no_hay_tope_por_instrumento(tmp_path):
    """Lo que hace falta para juntar datos con tres TP: que la TP3 colgada no
    bloquee la senal siguiente."""
    store, engine, _, _ = armar(
        tmp_path, positions_per_signal=3, max_positions_per_symbol=0,
        # Con el tope de fabrica (5) la segunda senal entraria recortada a 2 y
        # este test estaria midiendo MAX_OPEN_TRADES en vez de lo suyo.
        max_open_trades=10,
    )
    send(engine, SENAL, message_id=1)

    resultado = send(engine, SENAL_2, message_id=2)

    assert resultado["status"] == "aceptada"
    assert len(store.open_positions()) == 6


def test_el_tope_intermedio_frena_donde_dice(tmp_path):
    """Con 3, la segunda senal no entra: ya hay tres abiertas en ese simbolo."""
    store, engine, _, _ = armar(
        tmp_path, positions_per_signal=3, max_positions_per_symbol=3
    )
    send(engine, SENAL, message_id=1)

    resultado = send(engine, SENAL_2, message_id=2)

    assert resultado["status"] == "rechazada"
    assert any("3 posiciones abiertas" in r for r in resultado["reasons"])


# --------------------------------------------------------------------------
# El breakeven, con tres posiciones
# --------------------------------------------------------------------------

def test_el_breakeven_llega_a_las_tres(tmp_path):
    """Un "MOVER SL A 4438" sin simbolo aplica a todo lo abierto, y con tres
    posiciones del mismo trade tiene que alcanzarlas a las tres o no sirve."""
    store, engine, _, _ = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER SL A 4438", message_id=2)

    stops = {p.stop_loss for p in store.open_positions()}
    assert stops == {ORO + 0.5}, "alguna quedo con el stop viejo"
