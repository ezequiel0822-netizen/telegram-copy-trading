"""Con dinero real, la cuenta que se opera tiene que ser la que dice el .env.

EL AGUJERO
----------
Eran tres cosas que se apilaban, y las tres estaban en el camino exacto de
alguien copiando `.env.real.example` y completandolo a mano:

  1. `_validate_mode_requirements` no exigia NADA para LIVE salvo estar en
     Windows. MetaApi exige sus credenciales; MT5 no exigia ninguna.
  2. `mt5_native.connect()` solo llama a `login()` si estan las TRES
     credenciales. Si falta una, no hay `else`: se saltea el login en silencio
     y se opera la cuenta que la terminal ya tuviera cargada.
  3. Nadie comparaba nunca la cuenta conectada contra MT5_LOGIN.

Arriba de todo eso, `_ensure_demo` no opina porque con las dos llaves puestas
da por autorizado todo. Resultado medido con la plantilla tal cual, sin tocar
una sola credencial:

    tct check  ->  "Ejecucion: [OK] Modo LIVE."
    connect()  ->  True, enganchado a MetaQuotes-Demo #98600

Con dos MetaTrader instalados y dos cuentas del mismo broker -que es la
configuracion de esta maquina- "la terminal que encuentre" no tiene respuesta
correcta.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.config import ConfigError, load_settings
from tests.test_engine import build_settings

BASE = (
    "TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\n"
    "TELEGRAM_SESSION_NAME=s\nTELEGRAM_SOURCE_CHATS=-100\n"
    "TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=true\n"
)

CREDENCIALES = "MT5_LOGIN=555\nMT5_PASSWORD=secreta\nMT5_SERVER=FxPro-MT5\n"


def cargar(tmp_path, extra):
    (tmp_path / ".env").write_text(BASE + extra, encoding="utf-8")
    return load_settings(tmp_path / ".env")


# --------------------------------------------------------------------------
# Primera red: la configuracion no deja arrancar sin credenciales completas
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "falta, resto",
    [
        ("MT5_LOGIN", "MT5_PASSWORD=secreta\nMT5_SERVER=FxPro-MT5\n"),
        ("MT5_PASSWORD", "MT5_LOGIN=555\nMT5_SERVER=FxPro-MT5\n"),
        ("MT5_SERVER", "MT5_LOGIN=555\nMT5_PASSWORD=secreta\n"),
    ],
)
def test_live_sin_alguna_credencial_no_arranca(tmp_path, falta, resto):
    """Falta UNA sola y el login se saltea entero. No es un caso de borde:
    es lo que pasa copiando la plantilla y olvidandose de un renglon."""
    with pytest.raises(ConfigError) as exc:
        cargar(tmp_path, resto)

    assert falta in str(exc.value), "no dice cual falta"


def test_live_sin_ninguna_credencial_las_nombra_a_todas(tmp_path):
    """La plantilla recien copiada: las tres vacias."""
    with pytest.raises(ConfigError) as exc:
        cargar(tmp_path, "")

    mensaje = str(exc.value)
    for clave in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        assert clave in mensaje


def test_el_error_dice_que_hacer(tmp_path):
    """Quien lo lee no programa: tiene que salir con una accion, no con un
    nombre de variable."""
    with pytest.raises(ConfigError) as exc:
        cargar(tmp_path, "")

    mensaje = str(exc.value)
    assert "tct mt5" in mensaje, "no dice de donde sacar los datos"
    assert "MASTER" in mensaje, "no avisa que la de inversor no opera"


def test_live_con_las_tres_arranca(tmp_path):
    settings = cargar(tmp_path, CREDENCIALES)

    assert settings.is_live is True
    assert settings.mt5_login == "555"


def test_los_modos_demo_siguen_sin_exigir_nada(tmp_path):
    """Lo que no hay que romper: en demo, credenciales vacias es una funcion
    -se engancha a la terminal abierta-, no un error. Es como arranca todo el
    mundo la primera vez."""
    (tmp_path / ".env").write_text(
        "TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\n"
        "TELEGRAM_SESSION_NAME=s\nTELEGRAM_SOURCE_CHATS=-100\n"
        "TRADING_MODE=PAPER_ONLY\n",
        encoding="utf-8",
    )

    settings = load_settings(tmp_path / ".env")

    assert settings.is_live is False


# --------------------------------------------------------------------------
# Segunda red: el ejecutor verifica a que cuenta LLEGO
# --------------------------------------------------------------------------


class TerminalFalsa:
    """Una terminal MT5 ya logueada en `login`. `initialize()` se engancha a
    la que haya, que es justo el comportamiento que hace falta atajar."""

    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, login, server="FxPro-MT5", trade_mode=2):
        self._login = login
        self._server = server
        self._trade_mode = trade_mode
        self.login_llamado = False

    def initialize(self, **kwargs):
        return True

    def login(self, login, password=None, server=None):
        self.login_llamado = True
        return True

    def terminal_info(self):
        return SimpleNamespace(trade_allowed=True, path="")

    def account_info(self):
        datos = {
            "login": self._login,
            "server": self._server,
            "company": "FxPro Financial Services Ltd",
            "name": "Titular",
            "balance": 500.0,
            "trade_mode": self._trade_mode,
            "trade_allowed": True,
        }
        return SimpleNamespace(_asdict=lambda: datos, **datos)

    def last_error(self):
        return (0, "sin error")

    def shutdown(self):
        pass


def conectar(monkeypatch, settings, terminal):
    monkeypatch.setitem(sys.modules, "MetaTrader5", terminal)
    return asyncio.run(MT5NativeBroker(settings).connect())


def test_una_cuenta_distinta_a_la_del_env_no_opera(tmp_path, monkeypatch, caplog):
    """El caso de esta maquina: dos terminales, dos cuentas del mismo broker.
    El .env pide la real y la terminal quedo en otra."""
    settings = build_settings(
        tmp_path, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="secreta", mt5_server="FxPro-MT5",
    )

    with caplog.at_level("ERROR"):
        conectado = conectar(monkeypatch, settings, TerminalFalsa(login=98600))

    assert conectado is False, "opero una cuenta que no es la del .env"
    salida = caplog.text
    assert "555" in salida, "no dice cual pedia"
    assert "98600" in salida, "no dice a cual llego"
    assert "MT5_PATH" in salida, "no dice como arreglarlo"


def test_la_cuenta_correcta_conecta(tmp_path, monkeypatch):
    settings = build_settings(
        tmp_path, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="secreta", mt5_server="FxPro-MT5",
    )

    assert conectar(monkeypatch, settings, TerminalFalsa(login=555)) is True


def test_tambien_protege_a_las_demo_que_declaran_login(tmp_path, monkeypatch):
    """No es una guarda solo de dinero real. Las dos instancias demo tienen
    MT5_LOGIN puesto, y el aviso de MT5_PATH vacio ya describia este peligro
    ('cada uno en la del otro') sin que nada lo impidiera."""
    settings = build_settings(
        tmp_path, trading_mode="PAPER_AND_MT5_DEMO",
        mt5_login="98600", mt5_password="x", mt5_server="MetaQuotes-Demo",
    )

    terminal = TerminalFalsa(login=109600, server="FxPro-MT5", trade_mode=0)

    assert conectar(monkeypatch, settings, terminal) is False


def test_sin_login_declarado_el_chequeo_no_opina(tmp_path, monkeypatch):
    """Sin MT5_LOGIN no hay contra que comparar, y engancharse a la terminal
    abierta sigue siendo valido en demo."""
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO")

    terminal = TerminalFalsa(login=12345, server="MetaQuotes-Demo", trade_mode=0)

    assert conectar(monkeypatch, settings, terminal) is True
