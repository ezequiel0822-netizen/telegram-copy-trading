"""Cada grupo con su forma de operar, en el mismo bot (20/10).

Lo pidio para la demo de FxPro:
- David: "al segundo tp en 0.02" -> dos posiciones (TP1 y TP2) de 0.02, y "el
  SL de david ponlo al 65% de el que el manda": abre en 4130 con el SL del
  canal en 4140 -> SL en 4136.50 (CHANNEL_SL_PER_CHAT).
- TRADING ZONE: todos los TP a 0.04, con el SL del canal.
- Genesis: todos los TP a 0.03, con el SL artificial al 90% del TP1.
- Sebastian: todos los TP a 0.03, con el SL del canal.

POSITIONS_PER_CHAT, ARTIFICIAL_SL_PER_CHAT y CHANNEL_SL_PER_CHAT se escriben
como LOT_PER_CHAT: <numero del grupo>:<valor>, separados por comas.
"""

from __future__ import annotations

import pytest

from tct.brokers.paper import PaperBroker
from tct.config import POSICIONES_TODAS, ConfigError, load_settings
from tct.engine import Engine
from tct.store import Store
from tests.test_engine import build_settings, send

DAVID, SEBASTIAN, ZONA, GENESIS = (-1004363872187, -1003831574671, -1001666520346,
                                   -1003729772063)
FUENTES = [str(DAVID), str(SEBASTIAN), str(ZONA), str(GENESIS)]


class BrokerConCotizacion(PaperBroker):
    def __init__(self, bid, ask):
        super().__init__()
        self.cot = (bid, ask)

    async def market_price(self, symbol):
        return (self.cot[0] + self.cot[1]) / 2

    async def quote(self, symbol):
        return self.cot


def la_demo(tmp_path, bid=4130.0, ask=4130.2):
    """La demo de FxPro como la pidio el 20/10."""
    settings = build_settings(
        tmp_path, allowed_symbols={"XAUUSD"}, telegram_source_chats=FUENTES,
        default_lot=0.03, max_lot=0.04, max_open_trades=50, max_positions_per_symbol=30,
        lot_per_chat={"4363872187": 0.02, "3831574671": 0.03, "1666520346": 0.04,
                      "3729772063": 0.03},
        positions_per_chat={"4363872187": 2, "3831574671": POSICIONES_TODAS,
                            "1666520346": POSICIONES_TODAS, "3729772063": POSICIONES_TODAS},
        artificial_sl_per_chat={"3729772063": 90.0},
        channel_sl_per_chat={"4363872187": 65.0})
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return Engine(settings, store, BrokerConCotizacion(bid, ask))


def abiertas(engine):
    return sorted(engine.broker._positions.values(), key=lambda p: p["take_profit"])


VENTA = "XAUUSD SELL\nEntry 4130\nSL 4140\nTP 4125\nTP 4120\nTP 4115"


def test_david_dos_posiciones_de_002_con_el_sl_al_65_por_ciento(tmp_path):
    engine = la_demo(tmp_path)

    resultado = send(engine, VENTA, chat_id=DAVID)

    assert resultado["status"] == "aceptada"
    ps = abiertas(engine)
    # Del bid 4130 al SL del canal 4140 hay 10: el 65% son 6.5 -> 4136.50.
    assert [p["take_profit"] for p in ps] == [4120, 4125]  # TP2 y TP1; el TP3 (4115) no
    assert all(p["lot"] == 0.02 and p["stop_loss"] == pytest.approx(4136.5) for p in ps)


def test_trading_zone_todos_los_tp_a_004_con_el_sl_del_canal(tmp_path):
    engine = la_demo(tmp_path)

    send(engine, VENTA, chat_id=ZONA)

    ps = abiertas(engine)
    assert len(ps) == 3
    assert all(p["lot"] == 0.04 and p["stop_loss"] == 4140 for p in ps)


def test_genesis_todos_los_tp_a_003_con_el_sl_artificial(tmp_path):
    engine = la_demo(tmp_path)

    send(engine, VENTA, chat_id=GENESIS)

    ps = abiertas(engine)
    # Del bid 4130 al TP1 4125 faltan 5: el 90% son 4.5 -> 4134.50.
    assert len(ps) == 3
    assert all(p["lot"] == 0.03 and p["stop_loss"] == pytest.approx(4134.5) for p in ps)


def test_sebastian_todos_los_tp_a_003_con_el_sl_del_canal(tmp_path):
    engine = la_demo(tmp_path)

    send(engine, VENTA, chat_id=SEBASTIAN)

    ps = abiertas(engine)
    assert len(ps) == 3 and all(p["lot"] == 0.03 and p["stop_loss"] == 4140 for p in ps)


def test_el_65_por_ciento_se_mide_desde_donde_entra(tmp_path):
    # BUY 4130, SL 4120: entra al ask 4131 -> 11 puntos al SL, el 65% son 7.15.
    engine = la_demo(tmp_path, bid=4130.8, ask=4131.0)

    send(engine, "XAUUSD BUY\nEntry 4130\nSL 4120\nTP 4135\nTP 4140", chat_id=DAVID)

    assert all(p["stop_loss"] == pytest.approx(4123.85) for p in abiertas(engine))


def test_si_el_precio_ya_paso_el_sl_del_canal_no_abre(tmp_path):
    engine = la_demo(tmp_path, bid=4119.0, ask=4119.2)

    resultado = send(engine, "XAUUSD BUY\nEntry 4130\nSL 4120\nTP 4135", chat_id=DAVID)

    assert resultado["status"] == "rechazada"
    assert any("ya paso el SL del canal" in r for r in resultado["reasons"])


def test_un_mover_sl_de_david_que_lo_aleja_no_se_aplica(tmp_path):
    engine = la_demo(tmp_path)
    send(engine, VENTA, chat_id=DAVID, message_id=1)

    send(engine, "MOVER SL A 4139", chat_id=DAVID, message_id=2)

    assert all(p["stop_loss"] == pytest.approx(4136.5) for p in abiertas(engine))


def test_el_aviso_dice_cual_sl(tmp_path, caplog):
    import logging

    engine = la_demo(tmp_path)
    with caplog.at_level(logging.INFO, logger="tct"):
        send(engine, VENTA, chat_id=DAVID)

    assert ("(artificial, al 65% de la distancia del SL del canal; el canal decia 4140)"
            in caplog.text)


def test_el_arranque_dice_como_opera_cada_grupo(tmp_path):
    texto = la_demo(tmp_path).settings.describe()

    # Con cuanto lote suma una senal: MAX_LOT es por orden y no lo ve (8 x 0.04).
    assert ("lote de -1004363872187: 0.02, hasta 2 posiciones, una por TP (= 0.04 de lote por "
            "senal), SL artificial, al 65% de la distancia del SL del canal") in texto
    assert ("lote de -1001666520346: 0.04, una posicion por cada TP de la senal (una de 8 TP = "
            "0.32 de lote), SL el del canal") in texto
    assert "Por senal       : el de cada grupo (arriba), max 30 por instrumento; sin el suyo:" in texto
    assert ("lote de -1003729772063: 0.03, una posicion por cada TP de la senal (una de 8 TP = "
            "0.24 de lote), SL artificial, al 90%") in texto


# --- leerlo del .env --------------------------------------------------------------------

def escribir_env(tmp_path, **valores) -> str:
    base = {"TRADING_MODE": "PAPER_ONLY", "DEFAULT_LOT": "0.03", "MAX_LOT": "0.04",
            "TELEGRAM_SOURCE_CHATS": ",".join(FUENTES), "DATA_DIR": str(tmp_path / "data")}
    base.update(valores)
    ruta = tmp_path / ".env.prueba"
    ruta.write_text("".join(f"{k}={v}\n" for k, v in base.items()), encoding="utf-8")
    return str(ruta)


@pytest.fixture
def sin_entorno(monkeypatch):
    for clave in ("LOT_PER_CHAT", "DEFAULT_LOT", "MAX_LOT", "TELEGRAM_SOURCE_CHATS",
                  "POSITIONS_PER_CHAT", "ARTIFICIAL_SL_PER_CHAT", "CHANNEL_SL_PER_CHAT",
                  "POSITIONS_PER_SIGNAL", "ARTIFICIAL_SL_PCT", "CHANNEL_SL_PCT"):
        monkeypatch.delenv(clave, raising=False)


def test_se_lee_del_env_como_lo_pidio(tmp_path, sin_entorno):
    ruta = escribir_env(
        tmp_path,
        LOT_PER_CHAT=f"{DAVID}:0.02,{SEBASTIAN}:0.03,{ZONA}:0.04,{GENESIS}:0.03",
        POSITIONS_PER_CHAT=f"{DAVID}:2,{SEBASTIAN}:todas,{ZONA}:todas,{GENESIS}:todas",
        ARTIFICIAL_SL_PER_CHAT=f"{GENESIS}:90",
        CHANNEL_SL_PER_CHAT=f"{DAVID}:65")

    s = load_settings(ruta)

    assert s.posiciones_para(DAVID) == 2 and s.posiciones_para(1666520346) == POSICIONES_TODAS
    assert s.sl_canal_para(DAVID) == 65 and s.sl_artificial_para(DAVID) == 0
    assert s.sl_artificial_para(GENESIS) == 90 and s.sl_canal_para(GENESIS) == 0
    assert not s.tiene_sl_propio(ZONA) and not s.tiene_sl_propio(SEBASTIAN)


@pytest.mark.parametrize("variable, valor, dice", [
    ("POSITIONS_PER_CHAT", f"{DAVID}:muchas", "cuantas posiciones"),
    ("POSITIONS_PER_CHAT", "-100999:2", "no esta en TELEGRAM_SOURCE_CHATS"),
    ("POSITIONS_PER_CHAT", f"{DAVID}:2,{DAVID}:3", "dos veces"),
    ("ARTIFICIAL_SL_PER_CHAT", f"{GENESIS}:600", "de 0 a 500"),
    ("CHANNEL_SL_PER_CHAT", f"{DAVID}:120", "de 0 a 100"),
    ("CHANNEL_SL_PER_CHAT", "@david:65", "NUMERO del grupo"),
])
def test_un_valor_raro_no_arranca(tmp_path, sin_entorno, variable, valor, dice):
    with pytest.raises(ConfigError, match=dice):
        load_settings(escribir_env(tmp_path, **{variable: valor}))


def test_un_grupo_con_las_dos_formas_de_sl_no_arranca(tmp_path, sin_entorno):
    ruta = escribir_env(tmp_path, ARTIFICIAL_SL_PER_CHAT=f"{DAVID}:90",
                        CHANNEL_SL_PER_CHAT=f"{DAVID}:65")

    with pytest.raises(ConfigError, match="las dos formas"):
        load_settings(ruta)


def test_lo_del_grupo_pisa_lo_de_todos(tmp_path, sin_entorno):
    # Todos al 90% del TP1, pero David al 65% del SL del canal: vale.
    s = load_settings(escribir_env(tmp_path, ARTIFICIAL_SL_PCT="90",
                                   CHANNEL_SL_PER_CHAT=f"{DAVID}:65"))

    assert s.sl_canal_para(DAVID) == 65 and s.sl_artificial_para(DAVID) == 0
    assert s.sl_artificial_para(ZONA) == 90


def test_tct_cambiar_conoce_las_variables(tmp_path):
    from tct.archivo_env import _problema_con

    ruta = tmp_path / ".env"
    for nombre in ("POSITIONS_PER_CHAT", "ARTIFICIAL_SL_PER_CHAT", "CHANNEL_SL_PER_CHAT"):
        assert _problema_con(nombre, f"{DAVID}:2", ruta) is None
    assert _problema_con("CHANNEL_SL_PCT", "65", ruta) is None


# --- el repaso ----------------------------------------------------------------------------

def test_el_repaso_dice_como_opera_cada_grupo(tmp_path):
    from tct.cli import _modo_del_repaso

    lineas = _modo_del_repaso(la_demo(tmp_path).settings)

    assert lineas[0] == "  Cada grupo opera distinto:"
    assert any(str(DAVID) in l and "65%" in l for l in lineas)


def test_un_solo_grupo_en_el_repaso_dice_lo_suyo(tmp_path):
    import dataclasses

    from tct.cli import _modo_del_repaso

    s = dataclasses.replace(la_demo(tmp_path).settings, telegram_source_chats=[str(DAVID)])

    assert _modo_del_repaso(s) == [
        "  Por senal: hasta 2 posiciones, una por TP",
        "  SL       : artificial, al 65% de la distancia del SL del canal"]


def test_los_flags_del_repaso_pisan_lo_de_cada_grupo(tmp_path):
    from tct.cli import _ajustes_a_probar

    s, problema = _ajustes_a_probar(la_demo(tmp_path).settings, "1", "0")

    assert problema is None
    assert s.posiciones_para(ZONA) == 1 and not s.tiene_sl_propio(DAVID)


# --- lo que encontro la revision (20/10) -------------------------------------------------

def _hace(minutos):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()


@pytest.mark.parametrize("sl_nuevo, esperado", [
    (4135, 4133.25),   # 65% de 5 desde 4130
    (4138, 4135.2),    # 65% de 8: mas cerca que 4136.50, se aplica
    (4145, 4136.5),    # 65% de 15 = 4139.75 lo alejaria: no se aplica
])
def test_una_correccion_de_david_tambien_va_al_65_por_ciento(tmp_path, sl_nuevo, esperado):
    engine = la_demo(tmp_path)
    send(engine, VENTA, chat_id=DAVID, message_id=100, date=_hace(0))

    send(engine, VENTA.replace("SL 4140", f"SL {sl_nuevo}"), chat_id=DAVID, message_id=100,
         is_edit=True, date=_hace(1))

    assert all(p["stop_loss"] == pytest.approx(esperado) for p in abiertas(engine))


def test_una_posicion_con_sl_artificial_sin_grupo_tampoco_se_aleja(tmp_path):
    # Confirmada tarde y ambigua: queda sin grupo, pero abrio con SL artificial.
    # Con UNA posicion: con varias, la regla de "no alejar con varias" ya lo frena.
    engine = la_demo(tmp_path)
    send(engine, "XAUUSD SELL\nEntry 4130\nSL 4140\nTP 4125", chat_id=GENESIS, message_id=1)
    for p in engine.store.open_positions():
        p.grupo = None

    send(engine, "MOVER SL A 4139", chat_id=SEBASTIAN, message_id=2)

    assert all(p["stop_loss"] == pytest.approx(4134.5) for p in abiertas(engine))


def test_un_cero_por_grupo_apaga_el_sl_artificial_de_ese_grupo(tmp_path, sin_entorno):
    s = load_settings(escribir_env(tmp_path, CHANNEL_SL_PCT="65",
                                   ARTIFICIAL_SL_PER_CHAT=f"{SEBASTIAN}:0"))

    assert not s.tiene_sl_propio(SEBASTIAN) and s.sl_canal_para(DAVID) == 65


def test_las_lineas_por_grupo_salen_sin_lot_per_chat(tmp_path, sin_entorno):
    texto = load_settings(escribir_env(tmp_path, POSITIONS_PER_CHAT=f"{DAVID}:2")).describe()

    assert "lote de -1004363872187: 0.03 (DEFAULT_LOT), hasta 2 posiciones" in texto


def test_con_varios_grupos_el_repaso_da_lo_de_cada_uno_a_su_lote(capsys, tmp_path):
    from types import SimpleNamespace

    from tct.cli import _imprimir_como_esta_puesto

    def fila(chat, resultado, ms):
        return {"chat": chat, "posicion": SimpleNamespace(
            resultado=resultado, cerrada={"cerrada_ms": ms})}

    # El repaso abre a DEFAULT_LOT (0.03): David +3 -> a 0.02 son +2; TZ -3 -> a 0.04, -4.
    _imprimir_como_esta_puesto([fila(4363872187, 3.0, 1), fila(1666520346, -3.0, 2)],
                               la_demo(tmp_path).settings, 500.0)

    assert "Como esta puesto (cada grupo a su lote): resultado     -2.00   peor caida     -4.00" in (
        capsys.readouterr().out)


def test_el_detalle_dice_de_que_grupo(tmp_path):
    from tct.cli import _nombre_corto

    assert _nombre_corto("𝗫𝗔𝗨𝗨𝗦𝗗 TRADING ZONE", 1666520346) == "XAUUSD TRADING Z"
    assert _nombre_corto(None, 1666520346) == "1666520346"


def test_el_repaso_con_arroba_y_modo_por_grupo_pide_el_numero(tmp_path, monkeypatch, capsys):
    import argparse

    from tct import cli

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: la_demo(tmp_path).settings)
    codigo = cli.cmd_repaso(argparse.Namespace(env_file=".env.segunda", verbose=False, dias=40,
                                               lotes="0.02", detalle=False, chat="@davidforex"))

    assert codigo == 1 and "con el NUMERO de cada grupo" in capsys.readouterr().out
