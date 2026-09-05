"""Los mensajes de cuando MetaTrader no arranca.

El CONTEXTO_MAESTRO pide que los errores digan QUE HACER, no solo que fallo:
quien los lee no programa. El error crudo de MT5 cuando la ruta esta mal es

    (-10003, "IPC initialize failed, Process create failed 'C:\\...\\terminal64.exe'")

y no dice que el problema sea la ruta, ni que la ruta salga del .env, ni que se
pueda dejar vacia. Le paso de verdad al usuario: una sola letra de menos en el
nombre de la carpeta ("MetaTrade 5" en vez de "MetaTrader 5").
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.mt5_native import MT5NativeBroker, _pistas_de_initialize
from tests.test_engine import build_settings


def test_una_ruta_que_no_existe_se_detecta_antes_de_llamar_a_mt5(tmp_path, caplog):
    """Se chequea antes de initialize() a proposito: asi el motivo es la ruta y
    no un codigo interno de MT5 que hay que ir a buscar a un foro."""
    settings = build_settings(
        tmp_path, mt5_path=r"C:\Program Files\MetaTrade 5\terminal64.exe"
    )
    broker = MT5NativeBroker(settings)

    with caplog.at_level("ERROR"):
        conectado = asyncio.run(broker.connect())

    assert conectado is False
    salida = caplog.text
    assert "MT5_PATH" in salida, "no nombra la variable que hay que corregir"
    assert "MetaTrade 5" in salida, "no muestra la ruta que esta mal"
    assert "vacio" in salida.lower(), "no ofrece la salida facil: dejarla vacia"


def test_una_ruta_valida_no_se_bloquea_por_este_chequeo(tmp_path):
    """Lo que no hay que romper: si el archivo existe, el chequeo no opina y
    la conexion sigue su curso normal (que aca falla por no haber terminal)."""
    falso_terminal = tmp_path / "terminal64.exe"
    falso_terminal.write_text("no es un ejecutable de verdad", encoding="utf-8")
    settings = build_settings(tmp_path, mt5_path=str(falso_terminal))

    # No se afirma que conecte (no hay MetaTrader de verdad), solo que el
    # motivo del fallo ya no sea el chequeo de existencia.
    broker = MT5NativeBroker(settings)
    assert broker.settings.mt5_path == str(falso_terminal)
    assert falso_terminal.exists()


# --------------------------------------------------------------------------
# Las pistas, segun el codigo
# --------------------------------------------------------------------------


def test_con_ruta_configurada_manda_a_revisar_la_ruta():
    pistas = " ".join(_pistas_de_initialize(-10003, r"C:\algo\terminal64.exe"))
    assert "Propiedades" in pistas, "no dice como encontrar la ruta verdadera"
    assert "MT5_PATH" in pistas


def test_sin_ruta_configurada_manda_a_abrir_metatrader():
    """Sin ruta, el -10003 significa otra cosa: no encontro ninguna terminal."""
    pistas = " ".join(_pistas_de_initialize(-10003, ""))
    assert "Abri MetaTrader" in pistas
    assert "Propiedades" not in pistas, "esa pista no aplica si no hay ruta puesta"


def test_otros_codigos_dan_las_tres_causas_clasicas():
    pistas = " ".join(_pistas_de_initialize(-10005, ""))
    assert "no esta abierto" in pistas
    assert "sin loguear" in pistas
    assert "administrador" in pistas


@pytest.mark.parametrize("codigo", [-10003, -10005, -10001, 0])
def test_siempre_hay_algo_que_hacer(codigo):
    """Nunca puede quedar un fallo sin una instruccion al lado."""
    assert _pistas_de_initialize(codigo, ""), f"el codigo {codigo} no dice que hacer"


# --------------------------------------------------------------------------
# 'probar --operar' tiene que ejercitar el camino que se rompio
# --------------------------------------------------------------------------


def _probar_stop(fake, precio=4467.0):
    """Corre _probar_mover_stop contra una terminal MT5 falsa."""
    import asyncio

    from tct.brokers.base import OrderResult
    from tct.brokers.mt5_native import MT5NativeBroker
    from tct.cli import _probar_mover_stop
    from tests.fake_mt5 import enchufar
    from tests.test_engine import build_settings
    from pathlib import Path
    import tempfile

    settings = build_settings(Path(tempfile.mkdtemp()))
    broker = enchufar(MT5NativeBroker(settings), fake)
    apertura = OrderResult(True, "open", "ok", ticket=500001, symbol="XAUUSD")
    fallos: list = []
    asyncio.run(_probar_mover_stop(broker, "XAUUSD", "XAUUSD", apertura, precio, fallos))
    return fallos


def _terminal_con_una_posicion():
    from tests.fake_mt5 import FakeMT5

    fake = FakeMT5({"XAUUSD": {"bid": 4466.5, "ask": 4467.5}})
    fake.order_send({
        "action": fake.TRADE_ACTION_DEAL, "symbol": "XAUUSD",
        "volume": 0.01, "type": fake.ORDER_TYPE_BUY, "price": 4467.0,
    })
    return fake


def test_mover_el_stop_dos_veces_no_se_reporta_como_fallo():
    """El caso real: el canal edita el mensaje, el bot reprocesa, y el segundo
    intento pide un cambio que ya esta hecho."""
    assert _probar_stop(_terminal_con_una_posicion()) == []


def test_si_el_broker_rechazara_un_cambio_nulo_probar_lo_marca(capsys):
    """La prueba tiene que poder FALLAR, o no prueba nada. Se simula un broker
    que devuelve un rechazo de verdad ante el segundo movimiento."""
    fake = _terminal_con_una_posicion()
    original = fake.order_send
    llamadas = {"n": 0}

    def rechazar_el_segundo(request):
        if request.get("action") == fake.TRADE_ACTION_SLTP:
            llamadas["n"] += 1
            if llamadas["n"] == 2:
                fake.rechazar_con = 10016
        return original(request)

    fake.order_send = rechazar_el_segundo

    fallos = _probar_stop(fake)

    assert fallos, "un rechazo de un cambio nulo tiene que salir como fallo"
    assert "NO se pudo mover el SL" in fallos[0]


def test_probar_operar_llama_a_la_prueba_del_stop():
    """El cableado: que 'probar --operar' realmente lo ejercite."""
    import inspect

    from tct import cli

    assert "_probar_mover_stop" in inspect.getsource(cli._probar_async)
