"""`tct volumen`: el requisito del canal (0.50 compra + 0.50 venta, 30 min).

Lo pidio el 29/09 para entrar al grupo PRO del canal. Es la cuenta REAL y son
0.50 lotes: lo que importa es que nunca quede una de las dos sola, que no se
abra nada sin su SI, y que no corra con el bot andando.
"""

from __future__ import annotations

import argparse
import asyncio

from tct import cli
from tct.brokers.mt5_native import MT5NativeBroker
from tests.fake_mt5 import FakeMT5, FakeResult, enchufar
from tests.test_auditoria_ejecucion import Terminal
from tests.test_engine import build_settings


class ConEurusd(Terminal):
    def __init__(self):
        super().__init__()
        self.simbolos["EURUSD"] = {"bid": 1.17000, "ask": 1.17015}
        self.cuenta_login = 4049290

    def symbol_info(self, name):
        info = super().symbol_info(name)
        if info is not None:
            info.trade_contract_size = 100000
        return info

    def order_calc_margin(self, _tipo, _simbolo, lote, precio):
        return lote * 100000 * precio / 500

    def account_info(self):
        cuenta = super().account_info()
        cuenta.margin_free = 1250.0
        return cuenta


def ajustes(tmp_path):
    return build_settings(tmp_path, trading_mode="LIVE", allow_live_trading=True,
                          mt5_login="4049290", mt5_password="x", mt5_server="BullWaves-LIVE",
                          max_lot=0.05)


def correr(tmp_path, monkeypatch, terminal, confirmar=True, lote=0.5):
    monkeypatch.setitem(__import__("sys").modules, "MetaTrader5", terminal)
    esperas = []

    async def esperar(segundos):
        esperas.append(segundos)

    codigo = asyncio.run(cli._volumen_async(
        ajustes(tmp_path), simbolo="EURUSD", lote=lote, minutos=30,
        confirmar=lambda: confirmar, esperar=esperar))
    return codigo, esperas


def aperturas(terminal):
    return [r for r in terminal.enviados if "position" not in r]


def test_abre_las_dos_las_deja_30_minutos_y_las_cierra(tmp_path, monkeypatch, capsys):
    terminal = ConEurusd()

    codigo, esperas = correr(tmp_path, monkeypatch, terminal)

    salida = capsys.readouterr().out
    assert codigo == 0, salida
    abiertas = aperturas(terminal)
    assert [r["volume"] for r in abiertas] == [0.5, 0.5], "MAX_LOT de las senales no aplica"
    assert {r["type"] for r in abiertas} == {terminal.ORDER_TYPE_BUY, terminal.ORDER_TYPE_SELL}
    assert sum(esperas) == 30 * 60
    assert terminal.posiciones_abiertas() == []
    assert "PRIMERA CAPTURA" in salida and "SEGUNDA CAPTURA" in salida
    assert "~15.00 USD" in salida  # spread 0.00015 x 100000 x 0.5, por cada una de las dos


def test_si_la_venta_no_entra_la_compra_no_queda_sola(tmp_path, monkeypatch):
    terminal = ConEurusd()
    original = FakeMT5.order_send

    def venta_rechazada(request):
        if "position" not in request and request["type"] == terminal.ORDER_TYPE_SELL:
            return FakeResult(10019, comment="No money")
        return original(terminal, request)
    terminal.order_send = venta_rechazada

    codigo, _ = correr(tmp_path, monkeypatch, terminal)

    assert codigo == 1
    assert terminal.posiciones_abiertas() == [], "quedo 0.50 sin su pareja"


def test_sin_el_si_no_abre_nada(tmp_path, monkeypatch):
    terminal = ConEurusd()

    codigo, _ = correr(tmp_path, monkeypatch, terminal, confirmar=False)

    assert codigo == 1
    assert aperturas(terminal) == []


def test_sin_margen_no_abre_nada(tmp_path, monkeypatch):
    terminal = ConEurusd()

    codigo, _ = correr(tmp_path, monkeypatch, terminal, lote=10.0)

    assert codigo == 1
    assert aperturas(terminal) == []


def test_con_el_bot_andando_no_corre(tmp_path, monkeypatch, capsys):
    from tct.lockfile import lock_para

    import types

    import tct.lockfile

    settings = ajustes(tmp_path)
    # El candado de Windows usa msvcrt: el candado corre como en Linux.
    monkeypatch.setattr(tct.lockfile, "sys", types.SimpleNamespace(platform="linux"))
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr(cli, "_exigir_clave", lambda *_a: True)

    def no_deberia(*_a, **_k):
        raise AssertionError("opero con el bot andando")
    monkeypatch.setattr(cli, "_volumen_async", no_deberia)
    del_bot = lock_para(settings)
    del_bot.tomar()
    try:
        codigo = cli.cmd_volumen(argparse.Namespace(
            env_file=".env.real", verbose=False, simbolo="EURUSD", lote=0.5, minutos=30))
    finally:
        del_bot.soltar()

    assert codigo == 1
    assert "ANDANDO" in capsys.readouterr().out
