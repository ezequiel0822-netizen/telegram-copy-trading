"""Las dos llaves del dinero real tienen que ser DOS, en las dos direcciones.

EL AGUJERO
----------
Hasta la v1.3.0, `config.py` validaba una sola direccion: TRADING_MODE=LIVE sin
ALLOW_LIVE_TRADING=true daba error. La otra no:

    TRADING_MODE=AUTO + credenciales de una cuenta REAL + ALLOW_LIVE_TRADING=true

AUTO resolvia a modo demo, la validacion no saltaba, y el ejecutor salteaba el
chequeo de cuenta demo porque miraba solo ALLOW_LIVE_TRADING. El bot operaba
la cuenta REAL creyendo que era demo: sin el cartel de dinero real, sin
"*** REAL ***" en /estado, y sin la guarda que no deja arrancar una cuenta real
sin control por Telegram. Todo eso mira `is_live`, que exige LIVE.

Y era exactamente el camino natural para pasar a real, el que el usuario
describio: cambiar las credenciales en el .env de la demo de FxPro y prender
ALLOW_LIVE_TRADING. Se encontro revisando justo antes de que lo hiciera.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.config import ConfigError, load_settings
from tests.test_engine import build_settings

BASE = (
    "TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\n"
    "TELEGRAM_SESSION_NAME=s\nTELEGRAM_SOURCE_CHATS=-100\n"
    "MT5_LOGIN=123\nMT5_PASSWORD=x\nMT5_SERVER=FxPro-MT5 Live\n"
)

CUENTA_REAL = {"trade_mode": 2, "trade_allowed": True, "server": "FxPro-MT5 Live",
               "company": "FxPro Markets Ltd.", "name": "Titular"}
CUENTA_DEMO = {"trade_mode": 0, "trade_allowed": True, "server": "FxPro-MT5 Demo",
               "company": "FxPro Markets Ltd.", "name": "Titular"}


def cargar(tmp_path, extra):
    (tmp_path / ".env").write_text(BASE + extra, encoding="utf-8")
    return load_settings(tmp_path / ".env")


def ejecutor(settings):
    broker = MT5NativeBroker(settings)
    broker._mt5 = SimpleNamespace(ACCOUNT_TRADE_MODE_DEMO=0)
    return broker


# --------------------------------------------------------------------------
# Primera red: la configuracion
# --------------------------------------------------------------------------

def test_auto_con_allow_live_no_arranca(tmp_path):
    """El camino exacto del agujero."""
    with pytest.raises(ConfigError) as exc:
        cargar(tmp_path, "TRADING_MODE=AUTO\nALLOW_LIVE_TRADING=true\n")

    assert "TRADING_MODE=LIVE" in str(exc.value), "no dice como arreglarlo"


@pytest.mark.parametrize("modo", ["PAPER_ONLY", "PAPER_AND_MT5_DEMO"])
def test_ningun_modo_demo_acepta_allow_live(tmp_path, modo):
    with pytest.raises(ConfigError):
        cargar(tmp_path, f"TRADING_MODE={modo}\nALLOW_LIVE_TRADING=true\n")


def test_live_sin_allow_sigue_sin_arrancar(tmp_path):
    """La mitad que ya existia no se puede perder."""
    with pytest.raises(ConfigError, match="ALLOW_LIVE_TRADING"):
        cargar(tmp_path, "TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=false\n")


def test_las_dos_llaves_juntas_si_arrancan(tmp_path):
    settings = cargar(tmp_path, "TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=true\n")

    assert settings.is_live is True


def test_la_demo_de_siempre_sigue_igual(tmp_path):
    settings = cargar(tmp_path, "TRADING_MODE=AUTO\nALLOW_LIVE_TRADING=false\n")

    assert settings.is_live is False


# --------------------------------------------------------------------------
# Segunda red: el ejecutor
# --------------------------------------------------------------------------

def test_el_ejecutor_rechaza_una_real_sin_las_dos_llaves(tmp_path):
    """Settings armados sin pasar por `load_settings` no pueden saltearse el
    chequeo. Con solo ALLOW_LIVE_TRADING, una cuenta real se rechaza."""
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO",
                              allow_live_trading=True)

    ok, _ = ejecutor(settings)._ensure_demo(CUENTA_REAL)

    assert ok is False


def test_el_ejecutor_acepta_una_real_con_las_dos_llaves(tmp_path):
    settings = build_settings(tmp_path, trading_mode="LIVE", allow_live_trading=True)

    ok, _ = ejecutor(settings)._ensure_demo(CUENTA_REAL)

    assert ok is True


def test_el_ejecutor_sigue_aceptando_la_demo(tmp_path):
    ok, _ = ejecutor(build_settings(tmp_path))._ensure_demo(CUENTA_DEMO)

    assert ok is True


def test_el_rechazo_dice_que_hacer(tmp_path):
    _, motivo = ejecutor(build_settings(tmp_path))._ensure_demo(CUENTA_REAL)

    assert "TRADING_MODE=LIVE" in motivo and "ALLOW_LIVE_TRADING=true" in motivo


def test_metaapi_tiene_la_misma_red(tmp_path):
    modulo = pytest.importorskip("tct.brokers.metaapi")
    clase = next(
        v for v in vars(modulo).values()
        if isinstance(v, type) and "_ensure_demo" in vars(v)
    )
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_METAAPI_DEMO",
                              allow_live_trading=True)

    ok, _ = clase._ensure_demo(
        SimpleNamespace(settings=settings),
        {"type": "cloud-g2", "server": "FxPro-Live", "broker": "FxPro", "name": "x"},
    )

    assert ok is False
