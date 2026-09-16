"""Un MOVER SL sin simbolo no le agranda el riesgo a la posicion de al lado.

EL AGUJERO
----------
El `MOVER SL A <entrada>` que este canal manda detras de CADA senal no nombra
instrumento, asi que va a todas las posiciones abiertas. Eso es deliberado y
esta bien. El chequeo de escala (FACTOR_ESCALA_STOP) separa un stop de oro de
uno de EURUSD... pero NO separa dos posiciones del MISMO instrumento, y este
canal opera solo oro.

Medido con el motor y un MT5 falso, con la configuracion de la cuenta real
(MAX_POSITIONS_PER_SYMBOL=2, una posicion por senal):

    A: entro en 4432.5, SL 4424   -> riesgo 8.5 puntos
    B: entro en 4460.5, SL 4452   -> riesgo 8.5 puntos
    llega "MOVER SL A 4432", que es el breakeven de A
    A: SL 4432.5   <- correcto
    B: SL 4432.0   <- riesgo 28.5 puntos, mas del triple

Con 0.01 de oro son ~28 dolares en UNA operacion, y el tope diario del 5% sobre
500 son 25: un mensaje de gestion rutinario arma solo una perdida mayor que el
presupuesto del dia entero. El freno diario no lo ataja porque solo mira
aperturas, y MT5 tampoco porque el stop sigue del lado correcto del mercado.

Y no avisaba nada: con TELEGRAM_NOTIFY_LEVEL=problems no salia un solo mensaje.

LA GUARDA ES ESTRECHA A PROPOSITO
---------------------------------
No prohibe alejar un stop —un stop de swing 5% abajo es legitimo y hay un test
que lo exige—. Solo descarta las posiciones que empeoraria CUANDO el mensaje
aplica a varias: con una sola posicion abierta el mensaje no es ambiguo.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.risk import stop_agranda_el_riesgo
from tct.store import Store
from tests.fake_mt5 import FakeMT5
from tests.test_engine import build_settings

A = "DEAL | GOLD BUY XAUUSD 4432 TP1: 4436 TP2: 4438 TP3: 4440 SL: 4424"
B = "DEAL | GOLD BUY XAUUSD 4460 TP1: 4464 TP2: 4466 TP3: 4468 SL: 4452"
A_SELL = "DEAL | GOLD SELL XAUUSD 4460 TP1: 4456 TP2: 4454 TP3: 4452 SL: 4468"
B_SELL = "DEAL | GOLD SELL XAUUSD 4432 TP1: 4428 TP2: 4426 TP3: 4424 SL: 4440"


class Avisos:
    def __init__(self):
        self.out = []

    def enabled(self):
        return True

    async def send(self, texto):
        self.out.append(texto)
        return True


def armar(tope=2, nivel="problems"):
    tmp = Path(tempfile.mkdtemp())
    settings = build_settings(
        tmp, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="x", mt5_server="FxPro-MT5",
        default_lot=0.01, max_lot=0.01, allowed_symbols={"XAUUSD"},
        max_open_trades=2, max_positions_per_symbol=tope, max_signals_per_day=10,
        positions_per_signal=1, telegram_notify_level=nivel,
    )
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": 4432.0, "ask": 4432.5}})
    broker = MT5NativeBroker(settings)
    broker._mt5 = fake
    broker._ready = True
    broker.cuenta = "FxPro-MT5 #555"
    avisos = Avisos()
    return Engine(settings, store, broker, avisos), store, fake, avisos


def mandar(engine, texto, mid):
    return asyncio.run(engine.handle_message(texto, {"message_id": mid, "chat_id": -100}))


def riesgos(store):
    return [round(abs((p.entry_real or p.entry) - p.stop_loss), 2)
            for p in store.state.open_positions]


# --------------------------------------------------------------------------
# El escenario que cuesta plata
# --------------------------------------------------------------------------


def test_el_breakeven_de_una_no_le_aleja_el_stop_a_la_otra():
    engine, store, fake, _ = armar()
    mandar(engine, A, 1)
    fake.simbolos["XAUUSD"] = {"bid": 4460.0, "ask": 4460.5}
    mandar(engine, B, 2)
    assert riesgos(store) == [8.5, 8.5], "el escenario no quedo armado"

    mandar(engine, "MOVER SL A 4432", 3)

    assert riesgos(store) == [0.0, 8.5], (
        "el breakeven de la senal A le agrando el riesgo a la B"
    )


def test_la_que_si_corresponde_igual_se_mueve():
    """Lo importante: no se rechaza el mensaje entero. Se mueve lo que se puede."""
    engine, store, fake, _ = armar()
    mandar(engine, A, 1)
    fake.simbolos["XAUUSD"] = {"bid": 4460.0, "ask": 4460.5}
    mandar(engine, B, 2)

    resultado = mandar(engine, "MOVER SL A 4432", 3)

    # El motor lo dice mejor que "sl_movido" a secas: hubo una que no entro.
    assert resultado["status"] == "sl_movido_parcial"
    assert resultado["count"] == 1


def test_lo_que_quedo_sin_mover_avisa():
    """Antes no salia NADA con nivel 'problems': te ibas creyendo que las dos
    quedaron protegidas mientras una arriesgaba el triple."""
    engine, store, fake, avisos = armar()
    mandar(engine, A, 1)
    fake.simbolos["XAUUSD"] = {"bid": 4460.0, "ask": 4460.5}
    mandar(engine, B, 2)

    mandar(engine, "MOVER SL A 4432", 3)

    texto = "\n".join(avisos.out)
    assert texto, "no salio ningun aviso"
    assert "1 de 2" in texto, "no dice que una quedo sin mover"
    assert "aleja el stop" in texto, "no dice por que"


def test_tambien_en_SELL_pero_al_reves():
    """En un SELL el stop protege desde arriba: alejarlo es subirlo."""
    engine, store, fake, _ = armar()
    fake.simbolos["XAUUSD"] = {"bid": 4460.0, "ask": 4460.5}
    mandar(engine, A_SELL, 1)
    fake.simbolos["XAUUSD"] = {"bid": 4432.0, "ask": 4432.5}
    mandar(engine, B_SELL, 2)
    antes = riesgos(store)

    mandar(engine, "MOVER SL A 4460", 3)

    assert riesgos(store)[1] <= antes[1], "le subio el stop a la posicion SELL de abajo"


# --------------------------------------------------------------------------
# Lo que NO hay que romper
# --------------------------------------------------------------------------


def test_con_una_sola_posicion_el_mensaje_se_obedece_aunque_aleje():
    """Sin ambiguedad no hay nada que proteger: el mensaje dice lo que dice.
    Es el caso del stop de swing, que ya tenia su test en test_gestion_escala."""
    engine, store, _, _ = armar(tope=1)
    mandar(engine, A, 1)

    mandar(engine, "Move SL to 4400", 2)

    assert store.state.open_positions[0].stop_loss == 4400.0


def test_acercar_el_stop_siempre_se_permite():
    engine, store, fake, _ = armar()
    mandar(engine, A, 1)
    fake.simbolos["XAUUSD"] = {"bid": 4460.0, "ask": 4460.5}
    mandar(engine, B, 2)

    mandar(engine, "MOVER SL A 4455", 3)

    assert [p.stop_loss for p in store.state.open_positions] == [4455.0, 4455.0]


# --------------------------------------------------------------------------
# La funcion sola
# --------------------------------------------------------------------------


@pytest.mark.parametrize("side, actual, nuevo, esperado", [
    ("BUY", 4452.0, 4432.0, True),    # baja el stop de un BUY: aleja
    ("BUY", 4452.0, 4455.0, False),   # lo sube: protege
    ("SELL", 4440.0, 4468.0, True),   # sube el stop de un SELL: aleja
    ("SELL", 4440.0, 4435.0, False),  # lo baja: protege
    ("BUY", 4452.0, 4452.0, False),   # igual: no cambia nada
])
def test_la_direccion_depende_del_lado(side, actual, nuevo, esperado):
    motivo = stop_agranda_el_riesgo(side, actual, nuevo, hay_varias=True)
    assert (motivo is not None) is esperado


def test_sin_stop_previo_no_opina():
    assert stop_agranda_el_riesgo("BUY", None, 4432.0, hay_varias=True) is None


def test_con_una_sola_posicion_no_opina():
    assert stop_agranda_el_riesgo("BUY", 4452.0, 4432.0, hay_varias=False) is None
