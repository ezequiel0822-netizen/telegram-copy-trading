"""`tct evaluar-stop`: que habria pasado con el stop al 65/75/85% (08/10).

Los stops de -40 le parecen mucho. Antes de achicarlos quiso saber cuantas de
las que terminaron en TP se habrian cortado. Esto SOLO LEE el historial.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

import pytest

from tct import cli
from tct.brokers.mt5_native import MT5NativeBroker
from tct.informe import evaluar_stop_corto
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings

# El ejemplo que dio: BUY 4392 con SL 4382 (10 puntos), a 0.05 lotes de oro.
def fila(resultado, profit, peor, side="BUY", entry=4392.0, sl=4382.0, lleno=None):
    return {"side": side, "entry": entry, "stop_loss": sl, "resultado": resultado,
            "profit": profit, "peor": peor, "usd_por_punto": 5.0,
            "precio_entrada": lleno if lleno is not None else entry}


def test_un_tp_que_bajo_al_80_por_ciento_se_corta_al_75_y_no_al_85():
    r = evaluar_stop_corto([fila("TP1", 20.0, peor=4384.0)], [65, 75, 85])

    assert r["filas"][0]["llego"] == pytest.approx(0.8)
    por_pct = {e["pct"]: e for e in r["escenarios"]}
    assert por_pct[85]["total"] == pytest.approx(20.0)
    assert por_pct[85]["tp_cortados"] == 0
    # Stop al 75%: 4384.5, 7.5 puntos x 5 USD.
    assert por_pct[75]["total"] == pytest.approx(-37.5)
    assert por_pct[75]["tp_cortados"] == 1
    assert por_pct[65]["total"] == pytest.approx(-32.5)


def test_un_stop_pierde_menos_y_se_cuenta_desde_el_llenado_real():
    r = evaluar_stop_corto([fila("stop", -52.5, peor=4381.0, lleno=4392.5)], [75])

    escenario = r["escenarios"][0]
    # 4384.5 contra un llenado de 4392.5: 8 puntos, no 7.5.
    assert escenario["total"] == pytest.approx(-40.0)
    assert escenario["stops_achicados"] == 1


def test_sell_al_reves():
    r = evaluar_stop_corto(
        [fila("TP1", 20.0, peor=4389.0, side="SELL", entry=4382.0, sl=4392.0)], [65, 75])

    assert r["filas"][0]["llego"] == pytest.approx(0.7)
    por_pct = {e["pct"]: e for e in r["escenarios"]}
    assert por_pct[75]["total"] == pytest.approx(20.0)
    assert por_pct[65]["tp_cortados"] == 1
    assert por_pct[65]["total"] == pytest.approx(-32.5)


def test_las_que_no_tienen_datos_no_entran_en_ningun_total():
    r = evaluar_stop_corto([fila("TP1", 20.0, peor=4390.0),
                            fila("TP1", 999.0, peor=None)], [75])

    assert r["sin_datos"] == 1
    assert r["total_real"] == pytest.approx(20.0)
    assert r["escenarios"][0]["total"] == pytest.approx(20.0)


# --------------------------------------------------------------------------
# Lo que lee de MetaTrader
# --------------------------------------------------------------------------


class Deal:
    def __init__(self, entry, tipo, time, price=4392.0):
        self.entry, self.type, self.time, self.price = entry, tipo, time, price
        self.symbol, self.volume, self.profit, self.reason = "XAUUSD!", 0.05, 0.0, 5


class Historial(FakeMT5):
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
    DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
    COPY_TICKS_ALL, TIMEFRAME_M1 = -1, 1

    def __init__(self, tipo, ticks=None, velas=None):
        super().__init__({"XAUUSD!": {"bid": 4390.0, "ask": 4390.3}})
        self._deals = [Deal(0, tipo, 1_000), Deal(1, 1 - tipo, 4_600)]
        self._ticks, self._velas = ticks, velas
        self.pedidos = []

    def symbol_info(self, name):
        info = super().symbol_info(name)
        info.trade_contract_size, info.point = 100.0, 0.01
        return info

    def history_deals_get(self, position=None, **_kw):
        return self._deals

    def copy_ticks_range(self, simbolo, desde, hasta, _flags):
        self.pedidos.append((simbolo, desde.timestamp(), hasta.timestamp()))
        return self._ticks

    def copy_rates_range(self, _simbolo, _marco, _desde, _hasta):
        return self._velas

    def order_send(self, request):
        raise AssertionError("evaluar el stop mando una orden: tiene que ser solo lectura")


def recorrido(terminal):
    broker = enchufar(MT5NativeBroker(build_settings(Path(tempfile.mkdtemp()))), terminal)
    return asyncio.run(broker.recorrido_de(123))


def test_buy_el_peor_es_el_bid_mas_bajo_mientras_estuvo_abierta():
    terminal = Historial(0, ticks=[{"bid": 4391.0, "ask": 4391.3},
                                   {"bid": 4384.2, "ask": 4384.5},
                                   {"bid": 4399.0, "ask": 4399.3}])

    r = recorrido(terminal)

    assert r["peor"] == 4384.2
    assert r["usd_por_punto"] == pytest.approx(5.0)
    assert terminal.pedidos == [("XAUUSD!", 1_000, 4_601)], "fuera de la vida de la posicion"


def test_sell_el_peor_es_el_ask_mas_alto():
    terminal = Historial(1, ticks=[{"bid": 4391.0, "ask": 4391.3},
                                   {"bid": 4388.0, "ask": 4388.3}])

    assert recorrido(terminal)["peor"] == 4391.3


def test_sin_ticks_usa_velas_y_al_sell_le_suma_el_spread():
    velas = [{"low": 4380.0, "high": 4395.0, "spread": 30},
             {"low": 4385.0, "high": 4396.0, "spread": 20}]

    compra = recorrido(Historial(0, ticks=[], velas=velas))
    venta = recorrido(Historial(1, ticks=None, velas=velas))

    assert compra["peor"] == 4380.0 and compra["fuente"] == "velas de 1 minuto"
    assert venta["peor"] == pytest.approx(4396.2)


def test_sin_precios_no_inventa_nada():
    assert recorrido(Historial(0, ticks=[], velas=[])) is None


# --------------------------------------------------------------------------
# El comando entero
# --------------------------------------------------------------------------


class BrokerFalso:
    def __init__(self, desenlaces, recorridos):
        self._d, self._r = desenlaces, recorridos

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def desenlace_de(self, ticket):
        return self._d.get(ticket)

    async def recorrido_de(self, ticket):
        return self._r.get(ticket)


def test_el_comando_cuenta_los_tp_que_se_habrian_cortado(tmp_path, monkeypatch, capsys):
    settings = build_settings(tmp_path)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    for ticket, entrada, sl in [(1, 4392.0, 4382.0), (2, 4400.0, 4390.0)]:
        store.append_event("aceptada", {
            "signal": {"symbol": "XAUUSD", "side": "BUY", "entry": entrada,
                       "stop_loss": sl, "take_profits": [entrada + 4],
                       "telegram_message_id": ticket},
            "order": {"ticket": ticket},
        })
    broker = BrokerFalso(
        {1: {"motivo": "tp", "precio": 4396.0, "profit": 20.0, "precio_entrada": 4392.0},
         2: {"motivo": "sl", "precio": 4390.0, "profit": -50.0, "precio_entrada": 4400.0}},
        {1: {"peor": 4384.0, "usd_por_punto": 5.0, "fuente": "ticks"},
         2: {"peor": 4389.9, "usd_por_punto": 5.0, "fuente": "ticks"}},
    )
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr("tct.brokers.base.build_broker", lambda _s: broker)

    codigo = cli.cmd_evaluar_stop(argparse.Namespace(
        env_file=".env.real", horas=200, porcentajes="65,75,85"))

    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "llego al  80%" in salida
    assert "1  llegaron al 75% o mas" in salida
    assert "Resultado real          :   -30.00" in salida
    # Al 75%: el TP se corta (-37.50) y el stop pierde 37.50 en vez de 50.
    assert "Con el stop al 75%     :   -75.00" in salida
    assert "Con el stop al 85%     :   -22.50" in salida
