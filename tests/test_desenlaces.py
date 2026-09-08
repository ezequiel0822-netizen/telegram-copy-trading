"""Como termino cada operacion, leido del historial de MetaTrader.

LA RESTRICCION DE DISENO, que viene del pedido y no es un detalle: esto es
SOLO LECTURA y no corre mientras el bot escucha. El dato sirve para evaluar el
canal, no para decidir una orden, asi que no vale la pena meterle ni un
milisegundo al unico camino donde la latencia importa.

El historial de MT5 es persistente: sigue ahi cuando uno pide el informe.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.informe import (
    clasificar_desenlace,
    resumir_desenlaces,
    tickets_operados,
)
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings

# La senal real del canal: SELL 4467, SL 4472, TPs 4463/4461/4459. Cerro en
# 4467.00 por el stop movido a breakeven.
SENAL = {
    "ts": "2026-09-05T11:31:00+00:00",
    "ticket": 10359370031,
    "symbol": "XAUUSD",
    "side": "SELL",
    "entry": 4467.0,
    "stop_loss": 4472.0,
    "take_profits": [4463.0, 4461.0, 4459.0],
}


class Deal:
    def __init__(self, entry, price, profit, reason):
        self.entry = entry
        self.price = price
        self.profit = profit
        self.reason = reason
        self.time = 0


class HistorialFalso(FakeMT5):
    """MT5 con historial. Revienta si alguien intenta operar."""

    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_REASON_CLIENT = 0
    DEAL_REASON_EXPERT = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5

    def __init__(self, deals):
        super().__init__({"XAUUSD": {"bid": 4466.5, "ask": 4467.5}})
        self._deals = deals

    def history_deals_get(self, position=None, **_kw):
        return self._deals

    def order_send(self, request):
        raise AssertionError(
            "leer el historial mando una orden: esto tiene que ser solo lectura"
        )


def leer(deals):
    settings = build_settings(Path(tempfile.mkdtemp()))
    broker = enchufar(MT5NativeBroker(settings), HistorialFalso(deals))
    return asyncio.run(broker.desenlace_de(10359370031))


# --------------------------------------------------------------------------
# La garantia: solo lectura
# --------------------------------------------------------------------------


def test_leer_el_historial_no_manda_ninguna_orden():
    """El fake revienta ante cualquier order_send. Si esto pasa, el camino es
    de lectura pura."""
    leer([Deal(1, 4467.0, 0.57, HistorialFalso.DEAL_REASON_SL)])


def test_no_toca_las_posiciones_abiertas():
    fake = HistorialFalso([Deal(1, 4467.0, 0.57, HistorialFalso.DEAL_REASON_SL)])
    settings = build_settings(Path(tempfile.mkdtemp()))
    broker = enchufar(MT5NativeBroker(settings), fake)

    asyncio.run(broker.desenlace_de(10359370031))

    assert fake.enviados == [], "se le mando algo al broker"


# --------------------------------------------------------------------------
# El motivo lo dice MT5, no se deduce
# --------------------------------------------------------------------------


def test_un_stop_en_breakeven_no_se_cuenta_como_perdida():
    """Es LA distincion que importa en este canal: mueve el stop a la entrada
    a los pocos minutos, asi que la mayoria cierra por SL a precio de entrada.
    Contarlas como stops describiria mal al canal entero."""
    desenlace = leer([Deal(1, 4467.0, 0.57, HistorialFalso.DEAL_REASON_SL)])

    assert desenlace["motivo"] == "sl"
    assert clasificar_desenlace(SENAL, desenlace) == "breakeven"


def test_un_stop_de_verdad_si_es_un_stop():
    desenlace = leer([Deal(1, 4472.0, -5.0, HistorialFalso.DEAL_REASON_SL)])

    assert clasificar_desenlace(SENAL, desenlace) == "stop"


def test_un_cierre_por_take_profit_dice_cual():
    desenlace = leer([Deal(1, 4463.0, 4.0, HistorialFalso.DEAL_REASON_TP)])

    assert clasificar_desenlace(SENAL, desenlace) == "TP1"


def test_reconoce_los_tp_mas_lejanos():
    """Hoy el bot manda solo el primero, pero el dia que mande los tres el
    informe ya lo sabe leer."""
    assert clasificar_desenlace(
        SENAL, leer([Deal(1, 4459.0, 8.0, HistorialFalso.DEAL_REASON_TP)])
    ) == "TP3"


def test_un_cierre_a_mano_se_distingue():
    desenlace = leer([Deal(1, 4465.0, 2.0, HistorialFalso.DEAL_REASON_CLIENT)])

    assert clasificar_desenlace(SENAL, desenlace) == "cerrada a mano"


def test_una_posicion_todavia_abierta_no_inventa_un_desenlace():
    """Sin deal de salida no hay resultado. Suponer uno seria peor que no
    tenerlo: contaminaria el numero con el que se decide."""
    assert leer([Deal(0, 4467.5, 0.0, 0)]) is None


def test_sin_historial_devuelve_desconocido():
    assert leer([]) is None
    assert leer(None) is None


# --------------------------------------------------------------------------
# De donde sale el ticket
# --------------------------------------------------------------------------


def test_el_ticket_sale_del_evento_aceptada():
    """Es el unico lugar durable: el paper trade se escribe ANTES de llamar al
    broker y todavia no lo conoce, y el estado lo borra al cerrar."""
    eventos = [{
        "kind": "aceptada",
        "ts": "2026-09-05T11:31:00+00:00",
        "order": {"ticket": 555},
        "signal": {"symbol": "XAUUSD", "side": "SELL", "entry": 4467.0,
                   "take_profits": [4463.0]},
    }]

    operadas = tickets_operados(eventos)

    assert len(operadas) == 1
    assert operadas[0]["ticket"] == 555


def test_una_senal_rechazada_no_tiene_ticket():
    eventos = [{"kind": "rechazada", "signal": {"symbol": "XAUUSD"}}]

    assert tickets_operados(eventos) == []


def test_una_apertura_fallida_tampoco():
    """El BTCUSD que el broker no pudo abrir: no hay posicion que rastrear."""
    eventos = [{"kind": "apertura_fallida", "order": {"ticket": None},
                "signal": {"symbol": "BTCUSD"}}]

    assert tickets_operados(eventos) == []


# --------------------------------------------------------------------------
# El resumen
# --------------------------------------------------------------------------


def test_el_resumen_agrupa_y_suma():
    filas = [
        {"resultado": "breakeven", "profit": 0.57},
        {"resultado": "breakeven", "profit": 0.12},
        {"resultado": "TP1", "profit": 4.0},
        {"resultado": None},
    ]

    r = resumir_desenlaces(filas)

    assert r["conocidos"] == 3
    assert r["sin_datos"] == 1
    assert dict(r["por_resultado"])["breakeven"] == 2
    assert r["profit_total"] == pytest.approx(4.69)


def test_las_que_no_tienen_desenlace_no_ensucian_el_neto():
    """Contarlas como cero haria parecer que hubo mas operaciones cerradas de
    las que hubo, y el promedio saldria mal."""
    r = resumir_desenlaces([{"resultado": None}, {"resultado": None}])

    assert r["conocidos"] == 0
    assert r["profit_total"] == 0.0


def test_el_informe_solo_lo_hace_con_el_flag():
    """`tct informe` a secas tiene que seguir siendo instantaneo y sin
    depender de que MetaTrader este abierto."""
    import inspect

    from tct import cli

    fuente = inspect.getsource(cli.cmd_informe)
    assert "con_resultados" in fuente
    assert "_informar_desenlaces" in fuente
