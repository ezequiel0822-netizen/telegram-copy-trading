"""Tres bots en una PC y el camino que solo usa la cuenta real (auditoria 28/09).

La real va en Bullwaves y corre al lado de dos demos. Estos tests cubren lo que
podia hacer que un bot operara la cuenta de otro, que la real arrancara sin
poder operar, o que un comando o un diagnostico dijera algo falso.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from types import SimpleNamespace

import pytest

from tct import cli
from tct.brokers.mt5_native import MT5NativeBroker, elegir_nombre_de_simbolo
from tct.config import ConfigError, load_settings
from tct.signals.models import OrderType, Side
from tct.telegram.control import ControlTelegram
from tests.fake_mt5 import FakeMT5, FakeResult, enchufar
from tests.test_auditoria_ejecucion import SENAL, Terminal, armar
from tests.test_engine import build_settings, send


@pytest.fixture
def en_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


def conectar(settings, terminal, monkeypatch):
    monkeypatch.setitem(sys.modules, "MetaTrader5", terminal)
    broker = MT5NativeBroker(settings)
    return broker, asyncio.run(broker.connect())


def abrir(broker):
    return asyncio.run(broker.open_order(
        symbol="XAUUSD", side=Side.BUY, order_type=OrderType.MARKET, lot=0.01,
        entry=4432.0, stop_loss=4424.0, take_profit=4436.0))


# --------------------------------------------------------------------------
# Un bot nunca opera la cuenta de otro
# --------------------------------------------------------------------------


def test_una_demo_sin_mt5_login_no_opera_si_la_terminal_cambio_de_cuenta(
        tmp_path, monkeypatch):
    """La real le hace login() a la terminal compartida: la demo, sin
    MT5_LOGIN, mandaba sus ordenes a la cuenta REAL con ok=True."""
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO")
    terminal = Terminal()
    broker, conectado = conectar(settings, terminal, monkeypatch)
    assert conectado

    terminal.cuenta_login = 516648640  # la real le cambio la cuenta

    resultado = abrir(broker)

    assert not resultado.ok, "opero la cuenta de otra instancia"
    assert terminal.posiciones_abiertas() == []


def test_la_real_con_password_de_inversor_no_arranca(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, trading_mode="LIVE", allow_live_trading=True,
                              mt5_login="555", mt5_password="x", mt5_server="Bullwaves-Live")
    terminal = Terminal()
    original = terminal.account_info

    def sin_permiso():
        cuenta = original()
        datos = {**cuenta._asdict(), "trade_allowed": False}
        cuenta._asdict = lambda: datos
        return cuenta
    terminal.account_info = sin_permiso

    _, conectado = conectar(settings, terminal, monkeypatch)

    assert conectado is False


def test_metatrader_con_el_trading_por_api_deshabilitado_no_arranca(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO")
    terminal = Terminal()
    terminal.terminal_info = lambda: SimpleNamespace(trade_allowed=True,
                                                     tradeapi_disabled=True)

    _, conectado = conectar(settings, terminal, monkeypatch)

    assert conectado is False


def test_la_real_con_varias_instancias_exige_mt5_path(tmp_path, en_windows):
    env = tmp_path / ".env.real"
    env.write_text("TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=true\nINSTANCE_NAME=real\n"
                   "INSTANCE_NAMES=demo,fxpro,real\nMT5_LOGIN=555\nMT5_PASSWORD=x\n"
                   "MT5_SERVER=Bullwaves-Live\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="MT5_PATH"):
        load_settings(env)


def test_dos_env_con_la_misma_terminal_se_detectan(tmp_path):
    ruta = r"C:\Program Files\FxPro - MetaTrader 5\terminal64.exe"
    (tmp_path / ".env.segunda").write_text(
        f"INSTANCE_NAME=fxpro\nMT5_PATH={ruta}\nDATA_DIR=data/fxpro\n"
        "TELEGRAM_SESSION_NAME=sesion_fxpro\n", encoding="utf-8")
    real = tmp_path / ".env.real"
    real.write_text(f"INSTANCE_NAME=real\nMT5_PATH={ruta}\nDATA_DIR=data/real\n"
                    "TELEGRAM_SESSION_NAME=sesion_real\n", encoding="utf-8")
    settings = load_settings(real)

    choques = cli._choques_con_otras_instancias(settings, str(real))

    assert len(choques) == 1 and ".env.segunda" in choques[0]
    assert "MT5_PATH" in choques[0]


def test_env_distintos_no_chocan(tmp_path):
    (tmp_path / ".env.segunda").write_text(
        "INSTANCE_NAME=fxpro\nMT5_PATH=C:\\FxPro\\terminal64.exe\nDATA_DIR=data/fxpro\n"
        "TELEGRAM_SESSION_NAME=sesion_fxpro\n", encoding="utf-8")
    real = tmp_path / ".env.real"
    real.write_text("INSTANCE_NAME=real\nMT5_PATH=C:\\Bullwaves\\terminal64.exe\n"
                    "DATA_DIR=data/real\nTELEGRAM_SESSION_NAME=sesion_real\n",
                    encoding="utf-8")

    assert cli._choques_con_otras_instancias(load_settings(real), str(real)) == []


def test_las_rutas_del_env_son_relativas_al_env_y_no_a_la_carpeta_actual(
        tmp_path, monkeypatch):
    env = tmp_path / "bot" / ".env.real"
    env.parent.mkdir()
    env.write_text("DATA_DIR=data/real\nTELEGRAM_SESSION_NAME=sesion_real\n",
                   encoding="utf-8")
    otra = tmp_path / "otra"
    otra.mkdir()
    monkeypatch.chdir(otra)

    settings = load_settings(env)

    assert settings.state_path == env.parent / "data" / "real" / "state.json"
    assert settings.telegram_session_name == str(env.parent / "sesion_real")


def test_un_env_file_que_no_existe_es_un_error(tmp_path):
    with pytest.raises(ConfigError, match="No existe"):
        load_settings(tmp_path / ".env.reall")


def test_tct_run_sale_con_1_si_metatrader_no_conecta(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO")

    class NoConecta:
        name = "mt5"

        async def connect(self):
            return False

    monkeypatch.setattr("tct.brokers.base.build_broker", lambda _s: NoConecta())

    assert asyncio.run(cli._run_async(settings)) == 1


# --------------------------------------------------------------------------
# Los comandos dicen que la real no escucha
# --------------------------------------------------------------------------


def control_de(tmp_path, nombre):
    settings = build_settings(tmp_path / nombre, instance_name=nombre,
                              instance_names=("demo", "fxpro", "real"))
    from tct.brokers.paper import PaperBroker
    from tct.engine import Engine
    from tct.store import Store
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return ControlTelegram(settings, store, Engine(settings, store, PaperBroker()),
                           sin_control=["real"])


def test_pausa_todos_dice_que_la_real_no_se_entero(tmp_path):
    respuesta = asyncio.run(control_de(tmp_path, "demo").manejar("/pausa todos"))

    assert "PAUSADO" in respuesta.upper()
    assert "REAL NO escucha" in respuesta


def test_pausa_real_la_contesta_una_sola_instancia(tmp_path):
    demo = asyncio.run(control_de(tmp_path, "demo").manejar("/pausa real"))
    fxpro = asyncio.run(control_de(tmp_path, "fxpro").manejar("/pausa real"))

    assert demo and "NO escucha" in demo
    assert fxpro is None


def test_las_instancias_sin_control_se_leen_de_los_otros_env(tmp_path):
    (tmp_path / ".env.real").write_text("INSTANCE_NAME=real\nENABLE_TELEGRAM_CONTROL=false\n",
                                        encoding="utf-8")
    (tmp_path / ".env.segunda").write_text("INSTANCE_NAME=fxpro\n", encoding="utf-8")

    assert cli._instancias_sin_control(str(tmp_path / ".env")) == ["real"]


# --------------------------------------------------------------------------
# Bullwaves: el nombre del oro, el modo de llenado y el breakeven rechazado
# --------------------------------------------------------------------------


@pytest.mark.parametrize("nombre", ["XAUUSDpro", "XAUUSDecn", "XAUUSDraw", "#XAUUSD",
                                    "XAUUSD.pro", "XAUUSD+", "XAUUSDm"])
def test_nombres_del_oro_de_distintos_brokers(nombre):
    assert elegir_nombre_de_simbolo("XAUUSD", ["EURUSD", nombre]) == nombre


def test_un_sufijo_desconocido_largo_no_se_toma():
    assert elegir_nombre_de_simbolo("XAUUSD", ["XAUUSDTEST"]) is None


def test_el_modo_de_llenado_que_funciono_va_primero(tmp_path):
    """Un broker que solo acepta RETURN gastaba dos rechazos en cada orden."""
    settings = build_settings(tmp_path)
    terminal = Terminal()
    broker = enchufar(MT5NativeBroker(settings), terminal)
    original = FakeMT5.order_send

    def solo_return(request):
        if request.get("type_filling") != terminal.ORDER_FILLING_RETURN:
            terminal.enviados.append(dict(request))
            return FakeResult(10030, comment="Unsupported filling mode")
        return original(terminal, request)
    terminal.order_send = solo_return

    assert abrir(broker).ok
    antes = len(terminal.enviados)
    assert abrir(broker).ok
    assert len(terminal.enviados) - antes == 1, "volvio a probar los modos que no sirven"


def test_un_breakeven_rechazado_por_distancia_se_reintenta_solo(tmp_path):
    engine, store, terminal = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    original = FakeMT5.order_send
    rechazar = {"si": True}

    def distancia_minima(request):
        if request["action"] == terminal.TRADE_ACTION_SLTP and rechazar["si"]:
            return FakeResult(10016, comment="Invalid stops")
        return original(terminal, request)
    terminal.order_send = distancia_minima

    send(engine, "mover a breakeven", message_id=2)
    assert terminal.posiciones_abiertas()[0].sl == 4424.0

    rechazar["si"] = False  # el precio se alejo
    asyncio.run(engine.revisar_el_broker())

    assert terminal.posiciones_abiertas()[0].sl == 4432.5
    assert store.open_positions()[0].stop_loss == 4432.5
    assert engine._sl_pendientes == {}


# --------------------------------------------------------------------------
# tct mt5 y tct probar el dia de fondear
# --------------------------------------------------------------------------


def test_tct_mt5_marca_como_problema_que_no_este_el_oro(tmp_path, monkeypatch, capsys,
                                                       en_windows):
    from tests.test_cuanto_entra_en_la_cuenta import MT5Falso

    falso = MT5Falso(simbolos=["EURUSD"])
    env = tmp_path / ".env.real"
    env.write_text("ALLOWED_SYMBOLS=XAUUSD\nDEFAULT_LOT=0.05\nMAX_LOT=0.05\n",
                   encoding="utf-8")
    monkeypatch.setitem(sys.modules, "MetaTrader5", falso)

    codigo = cli.cmd_mt5(argparse.Namespace(env_file=str(env)))

    salida = capsys.readouterr().out
    assert codigo == 1
    assert "HAY QUE ARREGLAR" in salida and "XAUUSD" in salida


def test_tct_mt5_cuenta_las_que_entran_en_total_con_una_abierta(tmp_path, monkeypatch,
                                                              capsys, en_windows):
    """Con una abierta el margen libre ya la descuenta: pedia bajar el tope a 1
    en una cuenta donde entran 2."""
    from tests.test_cuanto_entra_en_la_cuenta import CuentaFalsa, MT5Falso

    cuenta = CuentaFalsa(margin_free=900.0)
    cuenta.margin = 870.0  # una posicion abierta
    falso = MT5Falso(cuenta=cuenta)
    env = tmp_path / ".env.real"
    env.write_text("ALLOWED_SYMBOLS=XAUUSD\nMAX_OPEN_TRADES=2\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "MetaTrader5", falso)

    cli.cmd_mt5(argparse.Namespace(env_file=str(env)))

    salida = capsys.readouterr().out
    assert "entran 2" in salida
    assert "Baja MAX_OPEN_TRADES" not in salida
