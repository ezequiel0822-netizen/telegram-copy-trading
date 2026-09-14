"""`/estado` tiene que decir contra que cuenta esta operando cada bot.

POR QUE
-------
Con DOS bots corriendo, la pregunta que mas importa es "este cual es". Y era
la unica que no se podia contestar desde el telefono: `/estado` decia
`Broker: mt5` en los dos, que es cierto y no sirve de nada.

El escenario que esto detecta es concreto y silencioso: si los dos `.env`
apuntan a la misma terminal -un MT5_PATH mal puesto, o los dos vacios- los dos
bots operan la MISMA cuenta. No hay ningun error; simplemente las operaciones
salen duplicadas en una cuenta y ninguna en la otra. La linea del arranque lo
dice, pero esa se ve una sola vez y despues se pierde entre los logs.
"""

from __future__ import annotations

import asyncio

from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.store import Store
from tct.telegram.control import ControlTelegram
from tests.test_engine import build_settings


def armar(tmp_path, cuenta, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    broker = PaperBroker()
    broker.cuenta = cuenta
    engine = Engine(settings, store, broker)
    return ControlTelegram(settings, store, engine)


def estado(control):
    return asyncio.run(control.manejar("/estado"))


def test_el_estado_dice_la_cuenta(tmp_path):
    control = armar(tmp_path, "FxPro-MT5 Demo #12345")

    assert "FxPro-MT5 Demo #12345" in estado(control)


def test_dos_instancias_se_distinguen(tmp_path):
    """La prueba de fondo: dos bots, dos respuestas distinguibles."""
    demo = armar(tmp_path / "a", "MetaQuotes-Demo #999", instance_name="demo")
    fxpro = armar(tmp_path / "b", "FxPro-MT5 Demo #111", instance_name="fxpro")

    uno, otro = estado(demo), estado(fxpro)

    assert "MetaQuotes-Demo" in uno and "FxPro" not in uno
    assert "FxPro" in otro and "MetaQuotes-Demo" not in otro


def test_sin_cuenta_no_agrega_una_linea_vacia(tmp_path):
    """El broker de papel no tiene cuenta. Una linea 'Cuenta :' en blanco seria
    peor que no tenerla."""
    control = armar(tmp_path, "")

    assert "Cuenta" not in estado(control)


def test_sigue_diciendo_lo_de_siempre(tmp_path):
    """Lo que ya mostraba no se puede perder."""
    salida = estado(armar(tmp_path, "MetaQuotes-Demo #1"))

    for esperado in ("Estado", "Modo", "Broker", "Abiertas", "Senales", "Lote"):
        assert esperado in salida, f"se perdio la linea '{esperado}'"
