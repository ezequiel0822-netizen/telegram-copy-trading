"""El freno diario mide contra el saldo con el que ABRIO el dia.

DOS AGUJEROS, los dos medidos ejecutando
----------------------------------------
1. La referencia se tomaba con la PRIMERA SENAL del dia, no al arrancar. Con
   posiciones abiertas de la noche anterior, entre que el dia cambia y llega el
   primer mensaje pueden pasar horas y varios dolares:

       la cuenta abrio en 500 y esta en 486 cuando llega la 1a senal
       referencia que tomaba el bot: 486  (deberia ser 500)
       tras perder otros 14 (el dia va -5.6%): aceptada, sin freno

   O sea: el tope del 5% no frenaba un dia que habia perdido 5.6%.

2. Si `account_equity()` LANZA, `_actualizar_equity` hacia `return` pelado y
   `balance_actual` conservaba la lectura anterior. Con la terminal caida
   mientras la cuenta baja, el freno comparaba contra un numero viejo y daba
   por bueno un dia que ya se habia pasado del tope. "Sin dato no se rechaza
   nada" es correcto; seguir usando el dato viejo no es lo mismo que no tener
   dato.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.store import Store
from tests.test_engine import build_settings


class BrokerConEquity(PaperBroker):
    def __init__(self, equity):
        super().__init__()
        self.equity = equity
        self.consultas = 0

    async def account_equity(self):
        self.consultas += 1
        if isinstance(self.equity, Exception):
            raise self.equity
        return self.equity


def armar(tmp_path, equity, pct=5.0):
    settings = build_settings(tmp_path, max_daily_loss_pct=pct)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return Engine(settings, store, BrokerConEquity(equity)), store


# --------------------------------------------------------------------------
# 1) La referencia se toma al arrancar
# --------------------------------------------------------------------------


def test_al_arrancar_queda_fijada_la_referencia(tmp_path):
    engine, store = armar(tmp_path, 500.0)

    asyncio.run(engine.fijar_referencia_del_dia())

    assert store.state.day_start_balance == 500.0, (
        "la referencia del dia no se fijo al arrancar"
    )


def test_lo_que_se_pierde_antes_de_la_primera_senal_cuenta(tmp_path):
    """El escenario medido: el bot arranca con la cuenta en 500, las
    posiciones de anoche la bajan a 486, y recien ahi llega una senal."""
    engine, store = armar(tmp_path, 500.0, pct=5.0)
    asyncio.run(engine.fijar_referencia_del_dia())

    engine.broker.equity = 472.0  # el dia va -5.6%
    asyncio.run(engine._actualizar_equity())

    from tct.risk import _daily_loss_reasons

    motivos = _daily_loss_reasons(engine.settings, store)

    assert motivos, "un dia que perdio 5.6% paso el tope del 5%"
    assert "5.6%" in motivos[0]


def test_el_arranque_la_llama_de_verdad():
    """El cableado, no la unidad. Los dos bugs mas caros del proyecto fueron
    codigo correcto que nadie llamaba desde ningun lado."""
    from tct import cli

    fuente = inspect.getsource(cli._run_async)

    assert "fijar_referencia_del_dia" in fuente, (
        "el arranque no fija la referencia del dia"
    )


# --------------------------------------------------------------------------
# 2) Sin dato es sin dato, no el dato viejo
# --------------------------------------------------------------------------


def test_un_fallo_de_lectura_borra_el_valor_viejo(tmp_path):
    engine, store = armar(tmp_path, 500.0)
    asyncio.run(engine._actualizar_equity())
    assert store.balance_actual == 500.0

    engine.broker.equity = RuntimeError("terminal caida")
    asyncio.run(engine._actualizar_equity())

    assert store.balance_actual is None, (
        "se quedo con la lectura vieja: el freno mide contra un numero de antes"
    )


def test_sin_dato_el_freno_no_opina(tmp_path):
    """Lo que no hay que romper: un broker que no contesta no puede dejar al
    bot sin operar. Es la regla de la seccion 9."""
    engine, store = armar(tmp_path, 500.0)
    asyncio.run(engine._actualizar_equity())
    engine.broker.equity = RuntimeError("terminal caida")
    asyncio.run(engine._actualizar_equity())

    from tct.risk import _daily_loss_reasons

    assert _daily_loss_reasons(engine.settings, store) == []


def test_la_referencia_sobrevive_al_fallo(tmp_path):
    """Perder la lectura de AHORA no puede perder la referencia del dia: si no,
    el primer equity que llegue despues se convierte en la nueva referencia y
    la perdida acumulada se borra sola."""
    engine, store = armar(tmp_path, 500.0)
    asyncio.run(engine.fijar_referencia_del_dia())

    engine.broker.equity = RuntimeError("terminal caida")
    asyncio.run(engine._actualizar_equity())

    assert store.state.day_start_balance == 500.0


@pytest.mark.parametrize("equity", [None, 500.0])
def test_el_freno_apagado_no_consulta_al_broker(tmp_path, equity):
    """Con MAX_DAILY_LOSS_PCT=0 no hay nada que medir, y una consulta al broker
    por mensaje no es gratis."""
    engine, _ = armar(tmp_path, equity, pct=0.0)

    asyncio.run(engine.fijar_referencia_del_dia())

    assert engine.broker.consultas == 0
