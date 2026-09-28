"""`tct ensayo`: un minuto de la cuenta real, contra una cuenta DEMO (28/09).

Antes de poner las credenciales de la real quiere ver "que todo entre bien"
en Bullwaves, sin otro bot corriendo dias. Lo que tiene que cumplir:
recorrer abrir -> mover el SL -> cerrar la mitad -> cerrar con los numeros de
.env.real, no dejar nada abierto, no escribir en los datos de la real, y
NUNCA operar una cuenta real.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

from tct import cli
from tests.test_auditoria_ejecucion import Terminal

RAIZ = Path(__file__).resolve().parents[1]


def env_real(tmp_path, con_ruta=True) -> Path:
    terminal = tmp_path / "Bullwaves" / "terminal64.exe"
    terminal.parent.mkdir()
    terminal.write_text("no es un ejecutable", encoding="utf-8")
    texto = (RAIZ / ".env.real.example").read_text(encoding="utf-8")
    if con_ruta:
        texto = texto.replace("MT5_PATH=\n", f"MT5_PATH={terminal}\n")
    env = tmp_path / ".env.real"
    env.write_text(texto, encoding="utf-8")
    return env


class CuentaReal(Terminal):
    ACCOUNT_TRADE_MODE_DEMO = 0

    def account_info(self):
        cuenta = super().account_info()
        cuenta.server = "Bullwaves-Live"
        datos = {"login": cuenta.login, "server": "Bullwaves-Live", "trade_mode": 2}
        cuenta._asdict = lambda: datos
        return cuenta


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def ensayar(monkeypatch, env, terminal):
    monkeypatch.setitem(sys.modules, "MetaTrader5", terminal)
    return cli.cmd_ensayo(argparse.Namespace(env_file=str(env), verbose=False))


def test_en_una_demo_recorre_todo_y_no_deja_nada_abierto(tmp_path, monkeypatch, capsys,
                                                       windows):
    terminal = Terminal()

    codigo = ensayar(monkeypatch, env_real(tmp_path), terminal)

    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "TODO ENTRA BIEN" in salida
    assert terminal.posiciones_abiertas() == []
    apertura = terminal.aperturas()[0]
    assert apertura["volume"] == 0.05, "no uso el lote de .env.real"
    assert apertura["sl"] and apertura["tp"]
    movidas = [r for r in terminal.enviados if r["action"] == terminal.TRADE_ACTION_SLTP]
    assert movidas, "no probo mover el stop"
    cierres = [r for r in terminal.enviados if "position" in r
               and r["action"] == terminal.TRADE_ACTION_DEAL]
    assert len(cierres) == 2, "la mitad y el resto"


def test_en_una_cuenta_real_no_manda_nada(tmp_path, monkeypatch, capsys, windows):
    terminal = CuentaReal()

    codigo = ensayar(monkeypatch, env_real(tmp_path), terminal)

    assert codigo == 1
    assert terminal.enviados == [], "el ensayo opero una cuenta REAL"
    assert "DEMO" in capsys.readouterr().out


def test_sin_la_ruta_de_bullwaves_no_arranca(tmp_path, monkeypatch, capsys, windows):
    terminal = Terminal()

    codigo = ensayar(monkeypatch, env_real(tmp_path, con_ruta=False), terminal)

    assert codigo == 1
    assert terminal.enviados == []
    assert "MT5_PATH=" in capsys.readouterr().out


def test_no_escribe_en_los_datos_de_la_real(tmp_path, monkeypatch, windows):
    ensayar(monkeypatch, env_real(tmp_path), Terminal())

    assert not (tmp_path / "data" / "real").exists()
    assert any((tmp_path / "data" / "ensayo").iterdir())


def test_si_el_stop_no_se_mueve_lo_dice(tmp_path, monkeypatch, capsys, windows):
    """Lo que mas importa saber de un broker nuevo: su distancia minima."""
    from tests.fake_mt5 import FakeMT5, FakeResult

    terminal = Terminal()
    original = FakeMT5.order_send

    def stop_rechazado(request):
        if request["action"] == terminal.TRADE_ACTION_SLTP:
            return FakeResult(10016, comment="Invalid stops")
        return original(terminal, request)
    terminal.order_send = stop_rechazado

    codigo = ensayar(monkeypatch, env_real(tmp_path), terminal)

    salida = capsys.readouterr().out
    assert codigo == 1
    assert "No se movio el stop" in salida
    assert terminal.posiciones_abiertas() == [], "dejo abierta la posicion del ensayo"
