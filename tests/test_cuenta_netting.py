"""Una cuenta NETTING no se opera, y `tct mt5` lo dice antes de fondear.

POR QUE
-------
El bot da por hecho HEDGING: cada senal abre su propia posicion, con su ticket,
su stop y su breakeven. En NETTING, MetaTrader junta todo lo de un simbolo en
una sola posicion: una senal SELL con un BUY abierto de otra senal CIERRA ese
BUY en vez de vender, y el stop de una pisa el de la otra. Con la real en 2
posiciones de oro a la vez, eso es plata.

Con FxPro nunca aparecio porque sus cuentas son hedging. Aparecio la pregunta
al pasar la cuenta real a Bullwaves (28/09): el tipo de cuenta depende del
broker y de lo que se elija al abrirla, y nada lo miraba.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from types import SimpleNamespace

import pytest

from tct import cli
from tct.brokers.mt5_native import MT5NativeBroker, modo_de_la_cuenta
from tests.test_cuanto_entra_en_la_cuenta import MT5Falso, CuentaFalsa, env
from tests.test_engine import build_settings

NETTING, EXCHANGE, HEDGING = 0, 1, 2  # los valores del paquete MetaTrader5


class TerminalFalsa:
    """Una terminal logueada en la cuenta 555, con el modo que se le diga."""

    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_MARGIN_MODE_RETAIL_NETTING = NETTING
    ACCOUNT_MARGIN_MODE_EXCHANGE = EXCHANGE
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = HEDGING

    def __init__(self, margin_mode):
        self.margin_mode = margin_mode

    def initialize(self, **kwargs):
        return True

    def login(self, login, password=None, server=None):
        return True

    def terminal_info(self):
        return SimpleNamespace(trade_allowed=True, path="")

    def account_info(self):
        datos = {
            "login": 555, "server": "Bullwaves-Live", "company": "Bullwaves",
            "name": "Titular", "balance": 500.0, "trade_mode": 2,
            "trade_allowed": True,
        }
        if self.margin_mode is not None:
            datos["margin_mode"] = self.margin_mode
        return SimpleNamespace(_asdict=lambda: datos, **datos)

    def last_error(self):
        return (0, "sin error")

    def shutdown(self):
        pass


def conectar(tmp_path, monkeypatch, terminal):
    settings = build_settings(
        tmp_path, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="secreta", mt5_server="Bullwaves-Live",
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", terminal)
    broker = MT5NativeBroker(settings)
    return broker, asyncio.run(broker.connect())


# --------------------------------------------------------------------------
# El bot
# --------------------------------------------------------------------------


@pytest.mark.parametrize("modo", [NETTING, EXCHANGE])
def test_una_cuenta_netting_no_se_opera(tmp_path, monkeypatch, caplog, modo):
    with caplog.at_level("ERROR"):
        broker, conectado = conectar(tmp_path, monkeypatch, TerminalFalsa(modo))

    assert conectado is False, "opero una cuenta netting"
    assert not broker._ready
    salida = caplog.text
    assert "NETTING" in salida
    assert "HEDGING" in salida, "no dice que cuenta hace falta"


def test_una_cuenta_hedging_conecta(tmp_path, monkeypatch):
    _, conectado = conectar(tmp_path, monkeypatch, TerminalFalsa(HEDGING))

    assert conectado is True


def test_si_la_terminal_no_dice_el_modo_no_se_inventa_un_motivo(tmp_path, monkeypatch):
    """Los MT5 de verdad siempre lo informan; si no viniera, frenar por un dato
    que falta dejaria sin operar una cuenta que anda."""
    _, conectado = conectar(tmp_path, monkeypatch, TerminalFalsa(None))

    assert conectado is True


def test_la_reconexion_tampoco_la_deja_pasar(tmp_path, monkeypatch):
    """Si MetaTrader se reinicia, el bot se reconecta solo (`_reconectar_sync`).
    Por ese camino tambien tiene que frenar: alguien pudo loguear otra cuenta."""
    terminal = TerminalFalsa(HEDGING)
    broker, conectado = conectar(tmp_path, monkeypatch, terminal)
    assert conectado is True

    terminal.margin_mode = NETTING
    terminal.terminal_info = lambda: None  # la terminal se corto

    assert broker._reconectar_sync() is False


@pytest.mark.parametrize("modo,esperado", [
    (NETTING, "netting"), (EXCHANGE, "netting"), (HEDGING, "hedging"), (None, None), (7, None),
])
def test_modo_de_la_cuenta(modo, esperado):
    cuenta = SimpleNamespace() if modo is None else SimpleNamespace(margin_mode=modo)
    assert modo_de_la_cuenta(TerminalFalsa(None), cuenta) == esperado


# --------------------------------------------------------------------------
# tct mt5: se ve ANTES de fondear, no recien al arrancar el bot
# --------------------------------------------------------------------------


@pytest.fixture
def en_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def correr_mt5(tmp_path, monkeypatch, margin_mode):
    cuenta = CuentaFalsa(margin_free=500.0)
    cuenta.margin_mode = margin_mode
    falso = MT5Falso(cuenta=cuenta)
    monkeypatch.setitem(sys.modules, "MetaTrader5", falso)
    return cli.cmd_mt5(argparse.Namespace(env_file=str(env(tmp_path))))


def test_tct_mt5_avisa_una_cuenta_netting(tmp_path, monkeypatch, capsys, en_windows):
    codigo = correr_mt5(tmp_path, monkeypatch, NETTING)

    salida = capsys.readouterr().out
    assert codigo == 1, "una cuenta que el bot no opera no puede terminar en 'todo en orden'"
    assert "Posiciones : NETTING" in salida
    assert "HAY QUE ARREGLAR ESTO" in salida
    assert "HEDGING" in salida


def test_tct_mt5_dice_hedging_y_no_lo_marca(tmp_path, monkeypatch, capsys, en_windows):
    correr_mt5(tmp_path, monkeypatch, HEDGING)

    salida = capsys.readouterr().out
    assert "Posiciones : HEDGING" in salida
    assert "NETTING" not in salida
