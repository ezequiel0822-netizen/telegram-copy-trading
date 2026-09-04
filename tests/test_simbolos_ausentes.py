"""Simbolos de ALLOWED_SYMBOLS que el broker conectado no expone.

Caso real: el canal del usuario opera BTCUSD y la demo de MetaQuotes a la que
esta conectado no tiene cripto. Eso no es un error de configuracion —es
normal que un broker no tenga todo— pero se callaba hasta que llegaba la
primera senal de ese instrumento, y ahi aparecia un "apertura_fallida" suelto
sin ninguna pista de que iba a pasar SIEMPRE con ese simbolo.
"""

from __future__ import annotations

import asyncio
import logging

from tct.brokers.mt5_native import MT5NativeBroker
from tct.brokers.paper import PaperBroker
from tct.cli import _avisar_simbolos_que_el_broker_no_opera
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings

SOLO_ORO = {"XAUUSD": {"bid": 4482.0, "ask": 4482.3}}


def avisar(settings, broker) -> None:
    asyncio.run(_avisar_simbolos_que_el_broker_no_opera(settings, broker))


def test_avisa_los_que_faltan_al_arrancar(tmp_path, caplog):
    settings = build_settings(tmp_path, allowed_symbols={"XAUUSD", "BTCUSD", "US30"})
    broker = enchufar(MT5NativeBroker(settings), FakeMT5(SOLO_ORO))

    with caplog.at_level(logging.WARNING):
        avisar(settings, broker)

    salida = caplog.text
    assert "BTCUSD" in salida
    assert "US30" in salida
    assert "XAUUSD" not in salida, "nombro un simbolo que el broker si opera"


def test_el_aviso_dice_que_las_senales_igual_se_registran(tmp_path, caplog):
    """Es la parte que evita el malentendido: no se pierde la senal, se pierde
    la ejecucion. El paper trade es lo que despues permite evaluar el canal."""
    settings = build_settings(tmp_path, allowed_symbols={"XAUUSD", "BTCUSD"})
    broker = enchufar(MT5NativeBroker(settings), FakeMT5(SOLO_ORO))

    with caplog.at_level(logging.WARNING):
        avisar(settings, broker)

    assert "REGISTRAR" in caplog.text
    assert "paper trade" in caplog.text


def test_si_estan_todos_no_dice_nada(tmp_path, caplog):
    """Un aviso que sale siempre deja de leerse."""
    settings = build_settings(tmp_path, allowed_symbols={"XAUUSD"})
    broker = enchufar(MT5NativeBroker(settings), FakeMT5(SOLO_ORO))

    with caplog.at_level(logging.WARNING):
        avisar(settings, broker)

    assert caplog.text == ""


def test_con_el_broker_de_papel_no_opina(tmp_path, caplog):
    """El broker de papel acepta cualquier simbolo: no tiene catalogo contra el
    cual comparar, y avisar ahi seria inventar un problema."""
    settings = build_settings(tmp_path, allowed_symbols={"XAUUSD", "BTCUSD"})

    with caplog.at_level(logging.WARNING):
        avisar(settings, PaperBroker())

    assert caplog.text == ""


def test_si_la_consulta_falla_no_rompe_el_arranque(tmp_path, caplog):
    """Es un aviso, no una validacion: nunca puede impedir que el bot arranque."""
    settings = build_settings(tmp_path, allowed_symbols={"XAUUSD", "BTCUSD"})
    broker = enchufar(MT5NativeBroker(settings), FakeMT5(SOLO_ORO))

    def revienta(_simbolo):
        raise RuntimeError("la terminal se cayo justo ahora")

    broker._resolver_contra_broker = revienta

    with caplog.at_level(logging.WARNING):
        avisar(settings, broker)  # no debe lanzar

    assert "BTCUSD" not in caplog.text
