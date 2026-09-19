"""Un "mover TP" que podria ser de varias posiciones no mueve ninguna, y avisa.

EL CASO
-------
Con POSITIONS_PER_SIGNAL=1 todas las posiciones persiguen el TP1, asi que con
dos senales de oro abiertas "la posicion del TP1" no identifica a ninguna. El
mensaje del canal no nombra simbolo ni senal. Medido con el motor y el MT5
falso, con la configuracion de la cuenta real:

    A: BUY entro en 4432.5, TP 4436   -> buscaba +3.5 puntos
    B: BUY entro en 4460.5, TP 4464
    llega "MOVER TP A 4470", que es de B
    A: TP 4470   -> ahora busca +37.5
    B: TP 4470

El stop quedaba intacto, asi que no agrandaba la perdida maxima. Pero una
ganancia chica probable se volvia una moneda al aire, y la posicion seguia
ocupando el lugar de la senal siguiente.

LA DECISION, del usuario (2026-09-16): en ese caso no se mueve ninguna y se
avisa. No hay forma de saber de cual habla, y adivinar es peor que preguntar.

Solo cuentan como candidatas las que de verdad podrian recibir el TP. Si una lo
tendria del lado equivocado (4470 no es un TP para un SELL con el oro en 4460)
el mensaje no es ambiguo, y se mueve la que corresponde.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.store import Store
from tests.fake_mt5 import FakeMT5
from tests.test_engine import AvisosDelLog, build_settings

A = "DEAL | GOLD BUY XAUUSD 4432 TP1: 4436 TP2: 4438 TP3: 4440 SL: 4424"
B = "DEAL | GOLD BUY XAUUSD 4460 TP1: 4464 TP2: 4466 TP3: 4468 SL: 4452"
B_SELL = "DEAL | GOLD SELL XAUUSD 4460 TP1: 4456 TP2: 4454 TP3: 4452 SL: 4468"


def armar(por_senal=1):
    tmp = Path(tempfile.mkdtemp())
    settings = build_settings(
        tmp, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="x", mt5_server="FxPro-MT5",
        default_lot=0.01, max_lot=0.01, allowed_symbols={"XAUUSD"},
        max_open_trades=10, max_positions_per_symbol=10, max_signals_per_day=10,
        positions_per_signal=por_senal,
    )
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": 4432.0, "ask": 4432.5}})
    broker = MT5NativeBroker(settings)
    broker._mt5 = fake
    broker._ready = True
    broker.cuenta = "FxPro-MT5 #555"
    return Engine(settings, store, broker), store, fake, AvisosDelLog()


def mandar(engine, texto, mid):
    return asyncio.run(engine.handle_message(texto, {"message_id": mid, "chat_id": -100}))


def dos_de_oro():
    engine, store, fake, avisos = armar()
    mandar(engine, A, 1)
    fake.simbolos["XAUUSD"] = {"bid": 4460.0, "ask": 4460.5}
    mandar(engine, B, 2)
    return engine, store, fake, avisos


# --------------------------------------------------------------------------
# Lo que pidio el usuario
# --------------------------------------------------------------------------


def test_con_dos_posiciones_no_se_mueve_ninguna():
    engine, store, fake, _ = dos_de_oro()

    resultado = mandar(engine, "MOVER TP A 4470", 3)

    assert resultado["status"] == "tp_ambiguo"
    assert [p.tp_objetivo for p in store.state.open_positions] == [4436.0, 4464.0]
    assert sorted(p.tp for p in fake._posiciones.values()) == [4436.0, 4464.0], (
        "el estado no lo movio pero al broker le llego igual"
    )


def test_queda_dicho_que_no_se_movio_y_por_que():
    """Es la unica forma de enterarse de que el canal pidio algo que el bot no
    hizo. Va al log como problema, no mezclado con la rutina."""
    engine, _, _, avisos = dos_de_oro()

    with avisos:
        mandar(engine, "MOVER TP A 4470", 3)

    assert "NO se movio el TP a 4470" in avisos.texto
    assert "4432.5" in avisos.texto and "4460.5" in avisos.texto, "no dice cuales son"
    assert "a mano" in avisos.texto, "no dice que hacer"


def test_queda_registrado_para_el_informe():
    engine, store, _, _ = dos_de_oro()

    mandar(engine, "MOVER TP A 4470", 3)

    eventos = [e for e in store.read_events() if e.get("kind") == "mover_tp"]
    assert eventos, "no quedo el evento"
    ultimo = eventos[-1]
    assert ultimo.get("ambiguo") is True
    assert ultimo["movidas"] == []
    assert len(ultimo["no_movidas"]) == 2


def test_el_stop_no_se_toca():
    engine, _, fake, _ = dos_de_oro()

    mandar(engine, "MOVER TP A 4470", 3)

    assert sorted(p.sl for p in fake._posiciones.values()) == [4424.0, 4452.0]


# --------------------------------------------------------------------------
# Lo que NO hay que romper
# --------------------------------------------------------------------------


def test_con_una_sola_posicion_se_mueve_como_siempre():
    engine, store, fake, _ = armar()
    mandar(engine, A, 1)

    resultado = mandar(engine, "MOVER TP A 4440", 2)

    assert resultado["status"] == "tp_movido"
    assert store.state.open_positions[0].tp_objetivo == 4440.0


def test_una_senal_con_tres_posiciones_no_es_ambigua():
    """La instancia de MetaQuotes abre tres por senal, y solo UNA persigue el
    TP1. Eso no es ambiguedad: es la regla de siempre."""
    engine, store, _, _ = armar(por_senal=3)
    mandar(engine, A, 1)

    resultado = mandar(engine, "MOVER TP A 4440", 2)

    assert resultado["status"] == "tp_movido"
    assert len(resultado["movidas"]) == 1


def test_si_solo_una_puede_recibirlo_no_hay_ambiguedad():
    """4470 con el oro en 4460 es un TP de BUY: al SELL le quedaria del lado
    equivocado. El mensaje solo puede hablar del BUY."""
    engine, store, fake, _ = armar()
    fake.simbolos["XAUUSD"] = {"bid": 4460.0, "ask": 4460.5}
    mandar(engine, B, 1)
    mandar(engine, B_SELL, 2)

    resultado = mandar(engine, "MOVER TP A 4470", 3)

    assert resultado["status"] == "tp_movido"
    assert len(resultado["movidas"]) == 1
    assert resultado["movidas"][0]["tp_nuevo"] == 4470.0
