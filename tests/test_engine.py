"""Tests de punta a punta del motor, con el broker de papel.

Todo el ciclo (mensaje -> parser -> riesgo -> paper trade -> broker -> estado)
se ejercita sin red y sin credenciales. Es lo que permite verificar el sistema
en la Mac antes de conectar nada.
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.paper import PaperBroker
from tct.config import PAPER_ONLY, Settings
from tct.engine import Engine
from tct.store import Store


def build_settings(tmp_path, **overrides) -> Settings:
    defaults = dict(
        trading_mode=PAPER_ONLY,
        telegram_api_id=1, telegram_api_hash="hash",
        telegram_session_name="test", telegram_source_chats=["-100"],
        telegram_bot_token="", telegram_notify_chat_id="",
        metaapi_token="", metaapi_account_id="", metaapi_region="new-york",
        mt5_login="", mt5_password="", mt5_server="", mt5_path="",
        mt5_broker_profile="default",
        default_lot=0.01, max_lot=0.10,
        allowed_symbols={"XAUUSD", "EURUSD", "US30"},
        max_open_trades=5, max_signals_per_day=20,
        require_stop_loss=True, require_take_profit=True,
        max_spread_from_entry_pct=0.5, allow_live_trading=False,
        enable_ocr=False, dry_run=False, poll_interval_seconds=5,
        data_dir=tmp_path,
        paper_trades_path=tmp_path / "paper_trades.jsonl",
        events_path=tmp_path / "events.jsonl",
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "tct.log",
        warnings=[],
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def engine(tmp_path):
    settings = build_settings(tmp_path)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return Engine(settings, store, PaperBroker())


def send(engine: Engine, text: str, **meta) -> dict:
    meta.setdefault("message_id", id(text) % 100000)
    meta.setdefault("chat_id", -100)
    return asyncio.run(engine.handle_message(text, meta))


# --------------------------------------------------------------------------


def test_senal_valida_se_acepta_y_se_registra(engine):
    result = send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP1 2355\nTP2 2365")

    assert result["status"] == "aceptada"
    assert result["order"]["ok"] is True

    trades = engine.store.read_paper_trades()
    assert len(trades) == 1
    assert trades[0]["symbol"] == "XAUUSD"
    assert trades[0]["status"] == "PAPER_OPENED"
    assert trades[0]["take_profits"] == [2355.0, 2365.0]

    assert len(engine.store.open_positions()) == 1


def test_el_paper_trade_se_registra_aunque_el_broker_falle(tmp_path):
    """Regla del CONTEXTO MAESTRO: siempre se guarda el paper trade."""

    class BrokerRoto(PaperBroker):
        async def is_ready(self) -> bool:
            return False

    settings = build_settings(tmp_path)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, BrokerRoto())

    result = send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    assert result["status"] == "aceptada"
    assert result["order"]["ok"] is False, "el broker fallo..."
    assert len(store.read_paper_trades()) == 1, "...pero el paper trade quedo igual"


def test_simbolo_fuera_de_la_lista_blanca_se_rechaza(engine):
    result = send(engine, "GBPUSD BUY\nEntry 1.26\nSL 1.25\nTP 1.27")
    assert result["status"] == "rechazada"
    assert any("ALLOWED_SYMBOLS" in r for r in result["reasons"])
    assert engine.store.read_paper_trades() == []


def test_senal_sin_stop_loss_se_rechaza(engine):
    result = send(engine, "XAUUSD BUY\nEntry 2345\nTP 2355")
    assert result["status"] == "rechazada"
    assert any("stop loss" in r.lower() for r in result["reasons"])


def test_sl_del_lado_equivocado_se_rechaza(engine):
    result = send(engine, "XAUUSD BUY\nEntry 2345\nSL 2355\nTP 2365")
    assert result["status"] == "rechazada"
    assert any("SL" in r for r in result["reasons"])


def test_no_se_abren_dos_posiciones_en_el_mismo_simbolo(engine):
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    result = send(engine, "XAUUSD BUY\nEntry 2346\nSL 2336\nTP 2356")
    assert result["status"] == "rechazada"
    assert any("Ya hay una posicion" in r for r in result["reasons"])


def test_tope_de_operaciones_abiertas(tmp_path):
    settings = build_settings(
        tmp_path, max_open_trades=2, allowed_symbols={"XAUUSD", "EURUSD", "US30"}
    )
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker())

    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    send(engine, "EURUSD BUY\nEntry 1.08\nSL 1.07\nTP 1.09")
    result = send(engine, "US30 BUY\nEntry 39500\nSL 39300\nTP 39800")

    assert result["status"] == "rechazada"
    assert any("MAX_OPEN_TRADES" in r for r in result["reasons"])


def test_mensajes_duplicados_no_operan_dos_veces(engine):
    texto = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"
    primero = send(engine, texto, message_id=7)
    segundo = send(engine, texto, message_id=7)

    assert primero["status"] == "aceptada"
    assert segundo["status"] == "duplicado"
    assert len(engine.store.read_paper_trades()) == 1


def test_la_charla_no_genera_nada(engine):
    result = send(engine, "Buen dia gente, arranca la semana")
    assert result["status"] == "ignorado"
    assert engine.store.read_paper_trades() == []


def test_mensaje_ambiguo_se_registra_y_no_opera(engine):
    result = send(engine, "BUY GOLD")
    assert result["status"] == "ambiguo"
    assert engine.store.read_paper_trades() == []
    assert any(e["kind"] == "ambiguo" for e in engine.store.read_events())


# --------------------------------------------------------------------------
# Gestion
# --------------------------------------------------------------------------


def test_cierre_total(engine):
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    result = send(engine, "Close XAUUSD now")

    assert result["status"] == "cerrada"
    assert engine.store.open_positions() == []
    assert any(t["status"] == "PAPER_CLOSED" for t in engine.store.read_paper_trades())


def test_cierre_parcial_deja_la_posicion_viva(engine):
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    result = send(engine, "Close 50% XAUUSD")

    assert result["status"] == "cierre_parcial"
    assert result["fraction"] == 0.5
    positions = engine.store.open_positions()
    assert len(positions) == 1
    assert positions[0].remaining_fraction == 0.5


def test_dos_cierres_parciales_se_componen(engine):
    """Dos 'close 50%' dejan 25%, no 0%: la fraccion es sobre lo que queda."""
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    send(engine, "Close 50% XAUUSD", message_id=101)
    send(engine, "Close 50% XAUUSD", message_id=102)

    positions = engine.store.open_positions()
    assert len(positions) == 1
    assert positions[0].remaining_fraction == pytest.approx(0.25)


def test_mover_sl_a_breakeven_usa_la_entrada_de_la_posicion(engine):
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    result = send(engine, "TP1 hit, move SL to BE")

    assert result["status"] == "sl_movido"
    assert engine.store.open_positions()[0].stop_loss == 2345.0


def test_gestion_sin_posiciones_abiertas_se_rechaza(engine):
    result = send(engine, "Close 50% XAUUSD")
    assert result["status"] == "rechazada"
    assert any("No hay posiciones" in r for r in result["reasons"])


# --------------------------------------------------------------------------
# Modos
# --------------------------------------------------------------------------


def test_dry_run_no_toca_nada(tmp_path):
    settings = build_settings(tmp_path, dry_run=True)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker())

    result = send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    assert result["status"] == "dry_run"
    assert store.read_paper_trades() == [], "DRY_RUN observa, no registra operaciones"
    assert store.open_positions() == []
    assert any(e["kind"] == "dry_run" for e in store.read_events()), "pero si deja rastro"


def test_el_estado_sobrevive_a_un_reinicio(tmp_path):
    settings = build_settings(tmp_path)

    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker())
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355", message_id=55)

    # Se simula un reinicio releyendo el estado desde disco.
    store2 = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    assert len(store2.open_positions()) == 1
    assert store2.open_positions()[0].symbol == "XAUUSD"
    assert store2.already_processed(-100, 55), "el mensaje ya procesado sigue marcado"
