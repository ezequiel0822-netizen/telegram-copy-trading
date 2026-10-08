"""`tct repaso`: los mensajes de los ultimos dias contra los precios reales.

Lo pidio el 08/10 para decidir el lote con mas de 17 operaciones. Lo que tiene
que cumplir: usar el MOTOR del bot (no una copia de sus reglas), cerrar cada
posicion en el tick en que toco su stop o su TP, y no mandar nada a ningun
lado.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from tct.engine import Engine
from tct.repaso import BrokerDeRepaso, a_ms, limpiar_resultado, repasar, resumir
from tct.store import Store
from tests.test_engine import build_settings

T0 = datetime(2026, 9, 1, 5, 0, tzinfo=timezone.utc)


def en(minutos: float) -> int:
    return a_ms(T0 + timedelta(minutes=minutos))


class Camino:
    """Un precio que pasa por los puntos dados, un tick por segundo, spread 0.2."""

    def __init__(self, puntos: list[tuple[float, float]]):
        self._ticks = []
        for (m1, p1), (m2, p2) in zip(puntos, puntos[1:]):
            pasos = max(int((m2 - m1) * 60), 1)
            for i in range(pasos):
                medio = p1 + (p2 - p1) * i / pasos
                self._ticks.append((en(m1) + i * 1000, round(medio - 0.1, 2), round(medio + 0.1, 2)))
        m, p = puntos[-1]
        self._ticks.append((en(m), p - 0.1, p + 0.1))

    def ticks(self, desde_ms, hasta_ms):
        return [t for t in self._ticks if desde_ms <= t[0] <= hasta_ms]


def correr(tmp_path, puntos, mensajes, **ajustes):
    settings = build_settings(tmp_path, default_lot=0.05, max_spread_from_entry_pct=0.05,
                              max_open_trades=15, **ajustes)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    broker = BrokerDeRepaso({"XAUUSD": Camino(puntos)}, {"XAUUSD": 100.0})
    engine = Engine(settings, store, broker)
    con_meta = [(texto, {"message_id": i + 1, "chat_id": -100,
                         "date": (T0 + timedelta(minutes=m)).isoformat(), **extra})
                for i, (m, texto, extra) in enumerate(mensajes)]
    fin = max(p[0] for p in puntos)
    return asyncio.run(repasar(engine, broker, con_meta, en(fin)))


def solo(filas):
    return [f for f in filas if f.get("posicion") is not None]


def test_un_tp_se_cierra_en_el_tick_que_lo_toca(tmp_path):
    filas = correr(tmp_path, [(0, 4392), (5, 4386), (20, 4397), (30, 4397)],
                   [(0, "XAUUSD BUY 4392\nSL 4382\nTP 4396\nTP 4398", {})])

    pos = solo(filas)[0]["posicion"]
    assert pos.entrada == pytest.approx(4392.1)          # entra al ask
    assert pos.cerrada["motivo"] == "tp"
    assert pos.cerrada["precio"] == pytest.approx(4396.0, abs=0.02)
    assert pos.resultado == pytest.approx((4396.0 - 4392.1) * 5, abs=0.2)


def test_un_stop_se_cierra_con_el_precio_que_lo_toco(tmp_path):
    filas = correr(tmp_path, [(0, 4400), (10, 4409), (20, 4409)],
                   [(0, "XAUUSD SELL 4400\nSL 4408\nTP 4396", {})])

    pos = solo(filas)[0]["posicion"]
    assert pos.cerrada["motivo"] == "sl"
    assert pos.resultado == pytest.approx(-(4408.0 - 4399.9) * 5, abs=0.2)


def test_el_breakeven_del_canal_se_aplica_con_las_reglas_del_bot(tmp_path):
    """'PARA LA POSICION "BUY 4380"...' mueve al precio de LLENADO, como en vivo."""
    filas = correr(
        tmp_path, [(0, 4380), (10, 4383.5), (20, 4379), (40, 4372)],
        [(0, "XAUUSD BUY 4380\nSL 4372\nTP 4386", {}),
         (10, 'PARA LA POSICIÓN "BUY 4380", MOVA SU SL A SER EL SL RESULTANTE ES 4380 BE', {})])

    pos = solo(filas)[0]["posicion"]
    assert pos.sl == pytest.approx(4380.1)
    assert pos.cerrada["motivo"] == "sl"
    assert abs(pos.resultado) < 1.0, "cerro en breakeven, no en el stop del canal"


def test_un_breakeven_rechazado_por_distancia_se_reintenta_como_en_vivo(tmp_path):
    """Con el precio todavia debajo de la entrada, MT5 lo rechaza; el bot insiste."""
    filas = correr(
        tmp_path, [(0, 4380), (5, 4379.5), (10, 4379.5), (15, 4384), (25, 4379), (40, 4379)],
        [(0, "XAUUSD BUY 4380\nSL 4372\nTP 4390", {}),
         (6, "mover SL a BE", {})])

    pos = solo(filas)[0]["posicion"]
    assert pos.sl == pytest.approx(4380.1), "el reintento no entro"
    assert pos.cerrada["motivo"] == "sl" and abs(pos.resultado) < 1.0


def test_la_senal_lejos_del_precio_no_abre_igual_que_en_vivo(tmp_path):
    filas = correr(tmp_path, [(0, 4380), (10, 4380)],
                   [(0, "XAUUSD BUY 4300\nSL 4290\nTP 4305", {})])

    assert solo(filas) == []
    assert filas[0]["rechazo"]


def test_una_senal_editada_con_el_resultado_se_recupera(tmp_path):
    texto = "XAUUSD BUY 4392\nSL 4382\nTP 4396\nTP1 HIT ✅ +40 pips"
    filas = correr(tmp_path, [(0, 4392), (20, 4397), (30, 4397)],
                   [(0, texto, {"editado": True})])

    assert solo(filas)[0]["reconstruida"]
    assert solo(filas)[0]["posicion"].cerrada["motivo"] == "tp"


def test_limpiar_no_toca_lo_que_no_tiene_resultado():
    assert limpiar_resultado("XAUUSD BUY 4392\nSL 4382\nTP 4396") is None


def test_el_resumen_cuenta_ganadas_equilibrio_racha_y_caida(tmp_path):
    filas = correr(
        tmp_path,
        [(0, 4392), (20, 4397), (60, 4400), (70, 4409), (120, 4400), (130, 4409),
         (180, 4392), (200, 4397), (240, 4397)],
        [(0, "XAUUSD BUY 4392\nSL 4382\nTP 4396", {}),
         (60, "XAUUSD SELL 4400\nSL 4408\nTP 4396", {}),
         (120, "XAUUSD SELL 4400\nSL 4408\nTP 4396", {}),
         (180, "XAUUSD BUY 4392\nSL 4382\nTP 4396", {})])

    r = resumir(filas, lote=0.05, lotes=[0.05, 0.10])

    assert (r["ganadas"], r["perdidas"], r["peor_racha"]) == (2, 2, 2)
    assert r["pct_ganadas"] == pytest.approx(50.0)
    # Gana ~19.5 y pierde ~40.5: hace falta ganar ~67% para no perder.
    assert r["pct_equilibrio"] == pytest.approx(67.5, abs=1.0)
    assert r["por_lote"][1]["peor_caida"] == pytest.approx(2 * r["por_lote"][0]["peor_caida"])
    assert r["por_lote"][0]["peor_caida"] == pytest.approx(81.0, abs=1.0)


# --------------------------------------------------------------------------
# El comando entero, con una terminal cuyo reloj va en UTC+3
# --------------------------------------------------------------------------


class TerminalConHistoria:
    """MT5 con ticks de historial en hora de SERVIDOR (UTC+3), como Bullwaves."""

    DEAL_ENTRY_IN, COPY_TICKS_ALL, TIMEFRAME_M1 = 0, -1, 1
    DESFASE_MS = 3 * 3_600_000

    def __init__(self, camino: Camino, ticket_del_bot: int, ts_del_bot: str):
        self._camino = camino
        self._ticket, self._ts = ticket_del_bot, ts_del_bot

    def symbols_get(self):
        return [type("S", (), {"name": "XAUUSD!"})()]

    def symbol_info(self, name):
        if name != "XAUUSD!":
            return None
        return type("I", (), {"name": name, "visible": True, "point": 0.01,
                              "trade_contract_size": 100.0})()

    def symbol_select(self, *_a):
        return True

    def history_deals_get(self, position=None, **_k):
        if position != self._ticket:
            return []
        hora_servidor = a_ms(self._ts) // 1000 + 3 * 3600 + 1
        return [type("D", (), {"entry": 0, "time": hora_servidor})()]

    def symbol_info_tick(self, _name):
        return None

    def copy_ticks_range(self, _simbolo, desde, hasta, _flags):
        d = int(desde.timestamp() * 1000) - self.DESFASE_MS
        h = int(hasta.timestamp() * 1000) - self.DESFASE_MS
        return [{"time_msc": t + self.DESFASE_MS, "bid": b, "ask": a}
                for t, b, a in self._camino.ticks(d, h)]

    def copy_rates_range(self, *_a):
        return []

    def account_info(self):
        return type("C", (), {"balance": 563.0})()

    def order_send(self, _request):
        raise AssertionError("el repaso mando una orden")


def test_el_comando_mide_con_la_hora_del_servidor_y_resume(tmp_path, monkeypatch, capsys):
    import argparse

    from tct import cli
    from tct.brokers.mt5_native import MT5NativeBroker

    import sys

    monkeypatch.setattr(sys.modules[__name__], "T0",
                        datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2))
    camino = Camino([(0, 4392), (20, 4397), (60, 4400), (70, 4409), (90, 4409)])
    settings = build_settings(tmp_path, default_lot=0.05, max_spread_from_entry_pct=0.05,
                              allowed_symbols={"XAUUSD"})
    # Una operacion del bot, para medir el desfase del servidor.
    Store(settings.events_path, settings.paper_trades_path, settings.state_path).append_event(
        "aceptada", {"signal": {"symbol": "XAUUSD"}, "order": {"ticket": 77}})
    ts_del_bot = Store(settings.events_path, settings.paper_trades_path,
                       settings.state_path).read_events()[-1]["ts"]
    terminal = TerminalConHistoria(camino, 77, ts_del_bot)

    async def conectar(self):
        self._mt5, self._ready, self._symbol_cache = terminal, True, {}
        return True

    async def desconectar(self):
        pass

    async def historia(_settings, _dias):
        return [(texto, {"message_id": i, "chat_id": 1, "is_edit": False,
                         "date": (T0 + timedelta(minutes=m)).isoformat()})
                for i, (m, texto) in enumerate([
                    (0, "XAUUSD BUY 4392\nSL 4382\nTP 4396"),
                    (60, "XAUUSD SELL 4400\nSL 4408\nTP 4396")])]

    monkeypatch.setattr(MT5NativeBroker, "connect", conectar)
    monkeypatch.setattr(MT5NativeBroker, "disconnect", desconectar)
    monkeypatch.setattr("tct.telegram.reader.fetch_history", historia)
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)

    codigo = cli.cmd_repaso(argparse.Namespace(env_file=".env.real", verbose=False, dias=40,
                                               lotes="0.05,0.10", detalle=True))

    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "UTC+3 (medido con una operacion del bot)" in salida
    assert "2 senales operadas, 0 que el bot no habria abierto" in salida
    assert "Ganadas      : 1 de 2  (50%)" in salida
    assert "Lote 0.10" in salida and "% de 563)" in salida
