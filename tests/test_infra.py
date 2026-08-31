"""Tests de configuracion, almacenamiento y mapeo de simbolos."""

from __future__ import annotations

import json

import pytest

from tct.brokers.symbol_map import from_broker_symbol, to_broker_symbol
from tct.config import ConfigError, load_settings
from tct.store import OpenPosition, Store, utc_now_iso


# --------------------------------------------------------------------------
# Mapeo de simbolos
# --------------------------------------------------------------------------


def test_perfil_por_defecto_no_cambia_el_simbolo():
    assert to_broker_symbol("XAUUSD") == "XAUUSD"


def test_perfil_con_sufijo():
    assert to_broker_symbol("XAUUSD", "exness") == "XAUUSDm"
    assert to_broker_symbol("EURUSD", "roboforex") == "EURUSD.r"


def test_override_gana_sobre_el_sufijo():
    assert to_broker_symbol("NAS100", "exness") == "USTEC"


def test_ida_y_vuelta_del_mapeo():
    for profile in ("default", "exness", "roboforex", "icmarkets"):
        assert from_broker_symbol(to_broker_symbol("XAUUSD", profile), profile) == "XAUUSD"


def test_perfil_desconocido_devuelve_el_simbolo_tal_cual():
    assert to_broker_symbol("XAUUSD", "broker_inventado") == "XAUUSD"


# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------


def write_env(tmp_path, contenido: str):
    path = tmp_path / ".env"
    path.write_text(contenido, encoding="utf-8")
    return path


def test_modo_invalido_falla_al_arrancar(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    env = write_env(tmp_path, "TRADING_MODE=MODO_QUE_NO_EXISTE\n")
    with pytest.raises(ConfigError, match="no es valido"):
        load_settings(env)


def test_lote_por_encima_del_maximo_falla(tmp_path):
    env = write_env(tmp_path, "TRADING_MODE=PAPER_ONLY\nDEFAULT_LOT=1.0\nMAX_LOT=0.1\n")
    with pytest.raises(ConfigError, match="no puede superar MAX_LOT"):
        load_settings(env)


def test_live_necesita_las_dos_llaves(tmp_path):
    env = write_env(tmp_path, "TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=false\n")
    with pytest.raises(ConfigError, match="ALLOW_LIVE_TRADING"):
        load_settings(env)


def test_metaapi_exige_sus_credenciales(tmp_path):
    env = write_env(tmp_path, "TRADING_MODE=PAPER_AND_METAAPI_DEMO\nMETAAPI_TOKEN=\n")
    with pytest.raises(ConfigError, match="METAAPI_TOKEN"):
        load_settings(env)


def test_mt5_nativo_se_bloquea_fuera_de_windows(tmp_path, monkeypatch):
    """En la Mac este modo tiene que fallar con un mensaje que explique por que."""
    monkeypatch.setattr("sys.platform", "darwin")
    env = write_env(tmp_path, "TRADING_MODE=PAPER_AND_MT5_DEMO\n")
    with pytest.raises(ConfigError, match="solo existe para Windows"):
        load_settings(env)


# --- Modo AUTO ------------------------------------------------------------
# La promesa del modo AUTO: MT5 demo esta disponible desde el primer arranque,
# y activarlo es completar dos variables del .env. Sin reinstalar, sin cambiar
# TRADING_MODE, sin tocar codigo. Estos tests son esa promesa.


def test_auto_es_el_modo_por_defecto(tmp_path):
    env = write_env(tmp_path, "TELEGRAM_API_ID=1\n")
    settings = load_settings(env)
    assert settings.configured_mode == "AUTO"


def test_auto_sin_credenciales_corre_en_papel(tmp_path):
    settings = load_settings(write_env(tmp_path, "TRADING_MODE=AUTO\n"))
    assert settings.trading_mode == "PAPER_ONLY"
    assert settings.broker_kind == "paper"
    assert settings.executes_orders is False
    assert settings.warnings, "tiene que decir como pasar a demo"


def test_el_aviso_de_papel_nombra_lo_correcto_en_windows(tmp_path, monkeypatch):
    """En Windows el camino es MT5 nativo, no MetaApi. Mandar a la persona a
    crear una cuenta en un servicio de pago que no necesita seria un error."""
    monkeypatch.setattr("sys.platform", "win32")
    settings = load_settings(write_env(tmp_path, "TRADING_MODE=AUTO\n"))
    aviso = " ".join(settings.warnings)
    assert "MT5_LOGIN" in aviso
    assert "METAAPI" not in aviso


def test_el_aviso_de_papel_nombra_lo_correcto_en_mac(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    settings = load_settings(write_env(tmp_path, "TRADING_MODE=AUTO\n"))
    aviso = " ".join(settings.warnings)
    assert "METAAPI_TOKEN" in aviso
    assert "MT5_LOGIN" not in aviso


def test_auto_con_credenciales_metaapi_pasa_a_mt5_demo(tmp_path):
    """El caso central: solo se agregaron dos lineas al .env."""
    env = write_env(tmp_path, "TRADING_MODE=AUTO\nMETAAPI_TOKEN=t\nMETAAPI_ACCOUNT_ID=a\n")
    settings = load_settings(env)
    assert settings.trading_mode == "PAPER_AND_METAAPI_DEMO"
    assert settings.broker_kind == "metaapi"
    assert settings.executes_orders is True


def test_auto_necesita_las_dos_credenciales(tmp_path):
    """Con una sola no alcanza: se queda en papel en vez de fallar al arrancar."""
    settings = load_settings(write_env(tmp_path, "TRADING_MODE=AUTO\nMETAAPI_TOKEN=t\n"))
    assert settings.trading_mode == "PAPER_ONLY"


def test_auto_en_mac_nunca_elige_mt5_nativo(tmp_path, monkeypatch):
    """Aunque haya credenciales MT5: ese paquete no existe para macOS."""
    monkeypatch.setattr("sys.platform", "darwin")
    env = write_env(
        tmp_path, "TRADING_MODE=AUTO\nMT5_LOGIN=1\nMT5_PASSWORD=p\nMT5_SERVER=s\n"
    )
    settings = load_settings(env)
    assert settings.trading_mode == "PAPER_ONLY"


def test_auto_en_windows_con_credenciales_mt5_usa_mt5_nativo(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    env = write_env(
        tmp_path, "TRADING_MODE=AUTO\nMT5_LOGIN=1\nMT5_PASSWORD=p\nMT5_SERVER=s\n"
    )
    assert load_settings(env).trading_mode == "PAPER_AND_MT5_DEMO"


def test_metaapi_le_gana_a_mt5_nativo(tmp_path, monkeypatch):
    """MetaApi primero: es el unico camino que tambien funciona en la Mac."""
    monkeypatch.setattr("sys.platform", "win32")
    env = write_env(
        tmp_path,
        "TRADING_MODE=AUTO\nMETAAPI_TOKEN=t\nMETAAPI_ACCOUNT_ID=a\n"
        "MT5_LOGIN=1\nMT5_PASSWORD=p\nMT5_SERVER=s\n",
    )
    assert load_settings(env).trading_mode == "PAPER_AND_METAAPI_DEMO"


def test_modo_explicito_le_gana_a_las_credenciales(tmp_path):
    """Poner PAPER_ONLY a mano vuelve a papel sin borrar las credenciales."""
    env = write_env(
        tmp_path, "TRADING_MODE=PAPER_ONLY\nMETAAPI_TOKEN=t\nMETAAPI_ACCOUNT_ID=a\n"
    )
    settings = load_settings(env)
    assert settings.trading_mode == "PAPER_ONLY"
    assert settings.was_auto_resolved is False


def test_describe_muestra_la_resolucion_del_modo(tmp_path):
    settings = load_settings(write_env(tmp_path, "TRADING_MODE=AUTO\n"))
    assert "AUTO -> PAPER_ONLY" in settings.describe()

    fijo = load_settings(write_env(tmp_path, "TRADING_MODE=PAPER_ONLY\n"))
    assert "->" not in fijo.describe().splitlines()[0]


def test_paper_only_arranca_sin_credenciales(tmp_path):
    env = write_env(tmp_path, "TRADING_MODE=PAPER_ONLY\n")
    settings = load_settings(env)
    assert settings.trading_mode == "PAPER_ONLY"
    assert settings.executes_orders is False
    assert settings.broker_kind == "paper"


def test_describe_no_filtra_secretos(tmp_path):
    env = write_env(
        tmp_path,
        "TRADING_MODE=PAPER_ONLY\nTELEGRAM_API_HASH=secreto_abc123\n"
        "TELEGRAM_BOT_TOKEN=123:TOKENSECRETO\nMT5_PASSWORD=clave_super_secreta\n",
    )
    salida = load_settings(env).describe()
    for secreto in ("secreto_abc123", "TOKENSECRETO", "clave_super_secreta"):
        assert secreto not in salida


def test_lista_de_simbolos_se_normaliza(tmp_path):
    env = write_env(tmp_path, "TRADING_MODE=PAPER_ONLY\nALLOWED_SYMBOLS= xauusd , eurusd ,\n")
    assert load_settings(env).allowed_symbols == {"XAUUSD", "EURUSD"}


# --------------------------------------------------------------------------
# Almacenamiento
# --------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return Store(
        tmp_path / "events.jsonl", tmp_path / "paper.jsonl", tmp_path / "state.json"
    )


def test_los_eventos_se_agregan_sin_pisarse(store):
    store.append_event("uno", {"a": 1})
    store.append_event("dos", {"b": 2})
    events = store.read_events()
    assert [e["kind"] for e in events] == ["uno", "dos"]
    assert all("ts" in e for e in events)


def test_una_linea_corrupta_no_invalida_el_historial(store):
    store.append_event("bueno", {})
    with store.events_path.open("a", encoding="utf-8") as file:
        file.write("{esto no es json\n")
    store.append_event("otro_bueno", {})
    assert len(store.read_events()) == 2


def test_el_estado_corrupto_se_respalda_y_arranca_limpio(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{roto", encoding="utf-8")

    store = Store(tmp_path / "e.jsonl", tmp_path / "p.jsonl", state_path)

    assert store.open_positions() == []
    assert (tmp_path / "state.corrupt.json").exists(), "el estado roto se guarda para revisarlo"


def test_el_estado_se_guarda_de_forma_atomica(store):
    store.add_position(OpenPosition(
        trade_id="abc", symbol="XAUUSD", side="BUY", lot=0.01,
        entry=2345.0, stop_loss=2335.0, take_profits=[2355.0], opened_at=utc_now_iso(),
    ))
    store.save_state()

    data = json.loads(store.state_path.read_text(encoding="utf-8"))
    assert data["open_positions"][0]["symbol"] == "XAUUSD"
    assert not list(store.state_path.parent.glob(".state-*.tmp")), "no quedan temporales"


def test_la_lista_de_procesados_no_crece_sin_techo(store):
    for i in range(700):
        store.mark_processed(-100, i)
    store.save_state()
    data = json.loads(store.state_path.read_text(encoding="utf-8"))
    assert len(data["processed_message_ids"]) == 500
    assert "-100:699" in data["processed_message_ids"], "se conservan los mas recientes"


def test_buscar_posiciones_por_simbolo(store):
    for symbol in ("XAUUSD", "EURUSD"):
        store.add_position(OpenPosition(
            trade_id=symbol, symbol=symbol, side="BUY", lot=0.01,
            entry=1.0, stop_loss=0.9, take_profits=[1.1], opened_at=utc_now_iso(),
        ))
    assert len(store.find_positions("XAUUSD")) == 1
    assert len(store.find_positions()) == 2, "sin simbolo devuelve todas (caso 'close all')"


def test_el_cupo_diario_se_reinicia_al_cambiar_el_dia(store):
    store.bump_daily_counter()
    store.bump_daily_counter()
    assert store.signals_today() == 2

    store.state.signals_day = "2020-01-01"
    assert store.signals_today() == 0, "otro dia, cupo nuevo"
