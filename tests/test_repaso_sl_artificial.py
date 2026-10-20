"""El repaso con SL artificial y una posicion por TP, sin tocar el .env (19/10).

`tct repaso --posiciones todas --sl-artificial 90`: lo que habria pasado si el
bot abria todos los TP con el SL al 90% de la distancia al TP1. Es el mismo
motor del bot, asi que lo que se mide es lo que haria en vivo.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import pytest

from tct.config import POSICIONES_TODAS
from tct.store import Store
from tests import test_repaso as base
from tests.test_engine import build_settings

SENAL = "XAUUSD BUY 4392\nSL 4382\nTP 4396\nTP 4398"
# Sube al TP1 (4396) sin llegar al TP2 (4398), y despues baja al SL artificial.
CAMINO = [(0, 4392), (20, 4397), (40, 4386), (60, 4386)]


def test_abre_una_por_tp_con_el_sl_artificial(tmp_path):
    filas = base.correr(tmp_path, CAMINO, [(0, SENAL, {})],
                        artificial_sl_pct=90.0, positions_per_signal=POSICIONES_TODAS)

    posiciones = [f["posicion"] for f in base.solo(filas)]
    assert sorted(p.tp for p in posiciones) == [4396, 4398]
    # Del ask 4392.1 al TP1 4396 faltan 3.9: el SL va 3.51 abajo.
    assert all(p.sl == pytest.approx(4388.59) for p in posiciones)
    por_tp = {p.tp: p for p in posiciones}
    assert por_tp[4396].cerrada["motivo"] == "tp"
    assert por_tp[4398].cerrada["motivo"] == "sl"
    assert por_tp[4398].cerrada["precio"] == pytest.approx(4388.59, abs=0.02)


def test_sin_los_ajustes_es_lo_de_siempre(tmp_path):
    filas = base.correr(tmp_path, CAMINO, [(0, SENAL, {})])

    [fila] = base.solo(filas)
    assert fila["posicion"].sl == 4382 and fila["posicion"].tp == 4396


@pytest.mark.parametrize("posiciones, sl, esperado", [
    ("todas", "90", (POSICIONES_TODAS, 90.0)),
    ("3", None, (3, 0.0)),
    (None, "90,5", (1, 90.5)),
    (None, None, (1, 0.0)),
])
def test_los_ajustes_a_probar(tmp_path, posiciones, sl, esperado):
    from tct.cli import _ajustes_a_probar

    ajustes, problema = _ajustes_a_probar(build_settings(tmp_path), posiciones, sl)

    assert problema is None
    assert (ajustes.positions_per_signal, ajustes.artificial_sl_pct) == esperado


@pytest.mark.parametrize("posiciones, sl", [("0", None), ("muchas", None), (None, "-1"),
                                            (None, "noventa"), (None, "nan")])
def test_un_ajuste_raro_no_corre(tmp_path, posiciones, sl):
    from tct.cli import _ajustes_a_probar

    _, problema = _ajustes_a_probar(build_settings(tmp_path), posiciones, sl)

    assert problema


def test_el_comando_entero(tmp_path, monkeypatch, capsys):
    from tct import cli
    from tct.brokers.mt5_native import MT5NativeBroker

    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)
    monkeypatch.setattr(base, "T0", t0)
    camino = base.Camino(CAMINO)
    settings = build_settings(tmp_path, default_lot=0.05, max_spread_from_entry_pct=0.05,
                              allowed_symbols={"XAUUSD"}, max_open_trades=20)
    Store(settings.events_path, settings.paper_trades_path, settings.state_path).append_event(
        "aceptada", {"signal": {"symbol": "XAUUSD"}, "order": {"ticket": 77}})
    ts_del_bot = Store(settings.events_path, settings.paper_trades_path,
                       settings.state_path).read_events()[-1]["ts"]
    terminal = base.TerminalConHistoria(camino, 77, ts_del_bot)

    async def conectar(self):
        self._mt5, self._ready, self._symbol_cache = terminal, True, {}
        return True

    async def desconectar(self):
        pass

    async def historia(_settings, _dias):
        return [(SENAL, {"message_id": 1, "chat_id": 1, "is_edit": False,
                         "date": t0.isoformat()})]

    monkeypatch.setattr(MT5NativeBroker, "connect", conectar)
    monkeypatch.setattr(MT5NativeBroker, "disconnect", desconectar)
    monkeypatch.setattr("tct.telegram.reader.fetch_history", historia)
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)

    codigo = cli.cmd_repaso(argparse.Namespace(
        env_file=".env.segunda", verbose=False, dias=40, lotes="0.02", detalle=True,
        posiciones="todas", sl_artificial="90"))

    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "Por senal: una posicion por cada TP de la senal" in salida
    assert "SL       : artificial, al 90% de la distancia al TP1" in salida
    assert "1 senales operadas (2 posiciones), 0 que el bot no habria abierto" in salida
    assert "cuentan POSICIONES" in salida
    # El detalle: cada posicion con su TP y su SL, y el mensaje una sola vez.
    assert "TP1 sl=4388.59 tp" in salida and "TP2 sl=4388.59 sl" in salida
    assert salida.count("mensaje : XAUUSD BUY 4392") == 1
    assert "POR TP, a lote 0.02 cada posicion:" in salida
    assert "TP1:   1 posiciones,   1 ganadas,   0 perdidas" in salida
    assert "TP2:   1 posiciones,   0 ganadas,   1 perdidas" in salida
    # Con otra forma de operar, el "que habria pasado con las tardias" no aplica.
    assert "QUE LLEGARON TARDE" not in salida


# --- lo que encontro la revision (19/10) ------------------------------------------------

def test_una_perdida_chica_del_sl_artificial_cuenta_como_perdida(tmp_path):
    # TP1 a 0.6 del ask: el SL artificial queda a 0.54. Medio punto adentro de
    # la franja del breakeven, pero es una perdida de verdad.
    from tct.repaso import resumir

    filas = base.correr(tmp_path, [(0, 4392), (10, 4389), (20, 4389)],
                        [(0, "XAUUSD BUY 4392\nSL 4382\nTP 4392.7\nTP 4396", {})],
                        artificial_sl_pct=90.0, positions_per_signal=POSICIONES_TODAS)

    r = resumir(filas, 0.05, [0.05], 100.0, por_motivo=True)
    assert (r["ganadas"], r["perdidas"], r["breakeven"]) == (0, 2, 0)


def test_con_el_sl_del_canal_se_cuenta_como_siempre(tmp_path):
    # Sin SL artificial, una ganancia chica en el TP sigue siendo breakeven:
    # los numeros de los grupos ya medidos no cambian (19/10).
    from tct.repaso import resumir

    filas = base.correr(tmp_path, [(0, 4392.6), (10, 4393.4), (20, 4393.4)],
                        [(0, "XAUUSD BUY\nEntry 4392\nSL 4382\nTP 4393", {})])

    r = resumir(filas, 0.05, [0.05], 100.0)
    assert (r["ganadas"], r["breakeven"]) == (0, 1)


def test_el_por_tp_cuenta_con_el_tp_de_la_apertura(tmp_path):
    # El canal mueve el TP de la del TP1 a 4398: sigue siendo la del TP1.
    from tct.cli import _numero_de_tp

    filas = base.correr(tmp_path, [(0, 4392), (20, 4401), (30, 4401)],
                        [(0, "XAUUSD BUY 4392\nSL 4382\nTP 4396\nTP 4398\nTP 4400", {}),
                         (1, "MOVER TP A 4398", {})],
                        artificial_sl_pct=90.0, positions_per_signal=POSICIONES_TODAS)

    posiciones = base.solo(filas)
    assert sorted(f["posicion"].tp for f in posiciones) == [4398, 4398, 4400]  # se movio
    assert sorted(_numero_de_tp(f) for f in posiciones) == [1, 2, 3]


def test_la_tabla_de_grupos_cuenta_senales(tmp_path, monkeypatch, capsys):
    from tct import cli

    monkeypatch.chdir(tmp_path)
    datos = {"cerradas": 16, "mensajes": 10, "operadas": 16, "senales_operadas": 4,
             "no_abiertas": 2, "ganadas": 10, "perdidas": 6, "pct_ganadas": 62.5,
             "pct_equilibrio": 50.0, "peor_racha": 3, "titulo": "TRADING ZONE",
             "por_lote": [{"lote": 0.02, "total": 10.0, "peor_caida": 5.0}]}

    cli._tabla_de_grupos([("-100", datos)], 0.03, [0.02])

    salida = capsys.readouterr().out
    fila = next(l for l in salida.splitlines() if l.strip().startswith("TRADING ZONE"))
    assert fila.split()[3] == "4" and "(pocas)" in fila
    assert "OPER cuenta senales" in salida and "comparten MAX_OPEN_TRADES" in salida


def correr_el_comando(tmp_path, monkeypatch, capsys, mensajes, puntos, **args):
    from tct import cli
    from tct.brokers.mt5_native import MT5NativeBroker

    t0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)
    monkeypatch.setattr(base, "T0", t0)
    camino = base.Camino(puntos)
    settings = build_settings(tmp_path, default_lot=0.05, max_spread_from_entry_pct=0.05,
                              allowed_symbols={"XAUUSD"}, max_open_trades=20)
    Store(settings.events_path, settings.paper_trades_path, settings.state_path).append_event(
        "aceptada", {"signal": {"symbol": "XAUUSD"}, "order": {"ticket": 77}})
    ts_del_bot = Store(settings.events_path, settings.paper_trades_path,
                       settings.state_path).read_events()[-1]["ts"]
    terminal = base.TerminalConHistoria(camino, 77, ts_del_bot)

    async def conectar(self):
        self._mt5, self._ready, self._symbol_cache = terminal, True, {}
        return True

    async def desconectar(self):
        pass

    async def historia(_settings, _dias):
        return [(texto, {"message_id": i + 1, "chat_id": 1, "is_edit": False,
                         "date": (t0 + timedelta(minutes=m)).isoformat()})
                for i, (m, texto) in enumerate(mensajes)]

    monkeypatch.setattr(MT5NativeBroker, "connect", conectar)
    monkeypatch.setattr(MT5NativeBroker, "disconnect", desconectar)
    monkeypatch.setattr("tct.telegram.reader.fetch_history", historia)
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    codigo = cli.cmd_repaso(argparse.Namespace(
        env_file=".env.segunda", verbose=False, dias=40, lotes="0.02", detalle=True, **args))
    salida = capsys.readouterr().out
    assert codigo == 0, salida
    return salida


def test_el_detalle_muestra_lo_que_el_canal_movio_y_lo_que_no(tmp_path, monkeypatch, capsys):
    salida = correr_el_comando(
        tmp_path, monkeypatch, capsys,
        [(0, SENAL), (5, "MOVER SL A 4380"), (10, "MOVER SL A 4392")],
        [(0, 4392), (5, 4393), (10, 4394), (20, 4397), (40, 4390), (60, 4390)],
        posiciones="todas", sl_artificial="90")

    # El primero lo alejaba: no se aplico, y se ve. El segundo lo acerco.
    assert "NO movio el SL a 4380 (lo alejaba)" in salida
    assert "sl=4388.59->" in salida
