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
