"""La demo de Bullwaves es el ensayo de la cuenta real (28/09).

Pidio probar el bot en una demo de Bullwaves antes de fondear. Sirve solo si
es un ensayo FIEL: los mismos numeros de riesgo que la real. Y como usa el
mismo MetaTrader que la real, las dos no pueden correr a la vez.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

from tct import cli
from tct.archivo_env import es_env_de_un_bot
from tct.config import load_settings

RAIZ = Path(__file__).resolve().parents[1]

# Lo que decide cuanto se arriesga y que senales entran. MAX_SIGNALS_PER_DAY
# queda afuera: la plantilla de la real sugiere 10 y su .env.real tiene 5 (su
# decision); la demo copia su .env.real, no la sugerencia.
RIESGO = ("DEFAULT_LOT", "MAX_LOT", "POSITIONS_PER_SIGNAL", "MAX_POSITIONS_PER_SYMBOL",
          "MAX_OPEN_TRADES", "MAX_DAILY_LOSS_PCT", "REQUIRE_STOP_LOSS",
          "REQUIRE_TAKE_PROFIT", "BREAKEVEN_USES_REAL_ENTRY", "MAX_SPREAD_FROM_ENTRY_PCT",
          "MAX_PENDING_DISTANCE_PCT", "MAX_STOP_DISTANCE_PCT", "ALLOWED_SYMBOLS",
          "OLLAMA_AUTO_EXECUTE", "MT5_BROKER_PROFILE", "INSTANCE_NAMES",
          "ENABLE_TELEGRAM_CONTROL")


def test_la_demo_tiene_los_mismos_numeros_que_la_real():
    real = dotenv_values(RAIZ / ".env.real.example")
    demo = dotenv_values(RAIZ / ".env.bullwaves.example")

    distintos = {k: (real.get(k), demo.get(k)) for k in RIESGO if real.get(k) != demo.get(k)}

    assert distintos == {}, f"la demo ya no ensaya la real: {distintos}"


def test_la_demo_es_demo_y_se_llama_distinto(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    env = tmp_path / ".env.bullwaves"
    shutil.copy(RAIZ / ".env.bullwaves.example", env)

    settings = load_settings(env)

    assert not settings.is_live
    assert settings.instance_name == "bullwaves"
    assert settings.state_path == tmp_path / "data" / "bullwaves" / "state.json"
    assert settings.telegram_session_name.endswith("telegram_copy_trading_bullwaves")


def test_la_real_no_arranca_mientras_la_demo_usa_su_metatrader(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    ruta = r"C:\Program Files\Bullwaves MT5 Terminal\terminal64.exe"
    for nombre in (".env.bullwaves", ".env.real"):
        texto = (RAIZ / f"{nombre}.example").read_text(encoding="utf-8")
        texto = (texto.replace("MT5_PATH=\n", f"MT5_PATH={ruta}\n")
                 .replace("MT5_LOGIN=\n", "MT5_LOGIN=7001\n" if "real" in nombre
                          else "MT5_LOGIN=9001\n")
                 .replace("MT5_PASSWORD=\n", "MT5_PASSWORD=x\n")
                 .replace("MT5_SERVER=\n", "MT5_SERVER=Bullwaves\n"))
        (tmp_path / nombre).write_text(texto, encoding="utf-8")
    real = load_settings(tmp_path / ".env.real")

    choques = cli._choques_con_otras_instancias(real, str(tmp_path / ".env.real"))

    assert choques and ".env.bullwaves" in choques[0]


def test_retirada_la_demo_ya_no_cuenta():
    """El paso para pasar a la real: renombrarla la saca de la carpeta de bots."""
    assert es_env_de_un_bot(".env.bullwaves")
    assert not es_env_de_un_bot(".env.bullwaves.retirada")


def test_el_lanzador_usa_su_archivo():
    bat = (RAIZ / "scripts" / "iniciar_bullwaves.bat").read_bytes()
    assert b"\r\n" in bat, "un .bat sin CRLF se rompe en Windows"
    assert b"--env-file .env.bullwaves run" in bat
    assert b".env.segunda" not in bat
