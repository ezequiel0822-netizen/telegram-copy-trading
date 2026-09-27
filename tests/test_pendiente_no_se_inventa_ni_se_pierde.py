"""Una orden PENDIENTE: ni se inventa por una palabra, ni se da por cerrada.

POR QUE LAS DOS COSAS JUNTAS
----------------------------
Encadenadas son el unico camino por el que este canal puede dejar una posicion
REAL viva que el bot no gestiona, y se encontraron auditando el camino de la
cuenta real, con la plata lista para entrar:

1. Cualquier "LIMIT" o "STOP" suelto ANTES del lado convertia una orden a
   mercado en PENDIENTE. El documento decia que hacia falta la palabra en
   ingles y suelta, o sea raro. Pero **"stop" tambien lo disparaba**, y este
   canal habla del stop loss todo el tiempo y a veces le pone una frase adelante
   al mensaje de apertura ("Senal 2 de hoy. DEAL | ..."), asi que de raro nada.

2. `posicion_existe` preguntaba SOLO por posiciones. Una pendiente viva no
   aparece ahi, asi que el motor la daba por "se cerro sola en el broker" y la
   sacaba del registro. La orden seguia en la cuenta, se disparaba mas tarde, y
   abria una posicion sin breakeven, sin parcial, sin cierre y sin ocupar lugar
   en MAX_OPEN_TRADES.
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.signals.models import OrderType
from tct.signals.parser import parse_signal
from tests.fake_mt5 import FakeMT5, enchufar

APERTURA = ("DEAL | GOLD (XAU/USD) BUY XAUUSD 4432 "
            "Parameters: TP1: 4436 TP2: 4438 TP3: 4440 SL: 4424")


# --------------------------------------------------------------------------
# No se inventa una pendiente
# --------------------------------------------------------------------------


@pytest.mark.parametrize("delante", [
    "Ojo con el stop de ayer.",            # el canal habla del stop loss
    "Recuerden mover el stop a BE.",
    "Atencion: hay un limit importante en 4450.",
    "Se acerca al limit de ayer.",
])
def test_una_palabra_suelta_no_convierte_la_senal_en_pendiente(delante):
    evento = parse_signal(f"{delante} {APERTURA}")

    assert evento.order_type is OrderType.MARKET, (
        "una orden a mercado quedo PENDIENTE por una palabra de la frase de adelante")


@pytest.mark.parametrize("texto,esperado", [
    ("XAUUSD BUY LIMIT 2345\nSL 2335\nTP 2355", OrderType.LIMIT),
    ("XAUUSD SELL STOP 2345\nSL 2355\nTP 2335", OrderType.STOP),
    ("GOLD SELL LIMIT 2345-2347\nSL: 2355\nTP: 2335", OrderType.LIMIT),
    # La forma dada vuelta tambien se reconoce: el tipo pegado al lado.
    ("LIMIT BUY XAUUSD 2345\nSL 2335\nTP 2355", OrderType.LIMIT),
    ("STOP ORDER SELL XAUUSD 2345\nSL 2355\nTP 2335", OrderType.STOP),
])
def test_una_pendiente_de_verdad_se_sigue_reconociendo(texto, esperado):
    assert parse_signal(texto).order_type is esperado


def test_el_precio_de_la_frase_si_se_lleva_la_entrada_pero_la_senal_queda_marcada():
    """Esto NO se arreglo, y es el punto 17 del §8: un numero delante del
    "DEAL |" se lleva puesta la entrada. Lo que cambio es que ya no ademas
    convierte la orden en pendiente.

    Sigue siendo barato porque falla del lado seguro: la senal queda con la
    geometria dada vuelta (los TP por debajo de la entrada en un BUY) y
    `risk.py` la rechaza. El test fija las dos cosas: que el numero se cuela, y
    que la senal viene marcada. Si algun dia se arregla el parser, este test
    avisa que hay que actualizar el §8."""
    evento = parse_signal(f"Atencion: hay un limit importante en 4450. {APERTURA}")

    assert evento.entry == 4450.0, "si esto cambio, tachar el punto 17 del §8"
    assert evento.order_type is OrderType.MARKET, "pero ya no queda pendiente"
    assert any("por debajo de la entrada" in aviso for aviso in evento.warnings), (
        "sin la marca de geometria, risk.py no tendria como rechazarla")


# --------------------------------------------------------------------------
# No se da por cerrada una pendiente viva
# --------------------------------------------------------------------------


class Ajustes:
    mt5_login = ""
    mt5_password = ""
    mt5_server = ""
    mt5_path = ""
    mt5_broker_profile = "default"
    max_lot = 0.01
    default_lot = 0.01
    allow_live_trading = False
    trading_mode = "PAPER_AND_MT5_DEMO"
    is_live = False


def armar():
    fake = FakeMT5({"XAUUSD": {"bid": 4431.5, "ask": 4432.0}})
    return enchufar(MT5NativeBroker(Ajustes()), fake), fake


def test_una_pendiente_viva_no_cuenta_como_cerrada():
    broker, fake = armar()
    fake.poner_pendiente(ticket=777)

    assert asyncio.run(broker.posicion_existe(777)) is True, (
        "la daba por cerrada y la soltaba del registro, viva en la cuenta")


def test_una_posicion_abierta_sigue_contando():
    broker, fake = armar()
    resultado = asyncio.run(broker.open_order(
        symbol="XAUUSD", side=__import__("tct.signals.models", fromlist=["Side"]).Side.BUY,
        order_type=OrderType.MARKET, lot=0.01, entry=4432.0,
        stop_loss=4424.0, take_profit=4436.0))

    assert asyncio.run(broker.posicion_existe(resultado.ticket)) is True


def test_lo_que_no_esta_en_ninguna_de_las_dos_listas_si_se_cerro():
    """La reconciliacion tiene que seguir funcionando: este canal no manda
    mensajes de cierre y sin esto se pierde casi una senal de cada dos (§9)."""
    broker, _ = armar()

    assert asyncio.run(broker.posicion_existe(999)) is False


def test_si_no_se_puede_preguntar_no_se_borra_nada():
    """None es "no pude preguntar", y ahi la posicion puede estar viva."""
    broker, fake = armar()

    fake.positions_get = lambda ticket=None: None

    assert asyncio.run(broker.posicion_existe(777)) is None


def test_si_falla_la_consulta_de_pendientes_tampoco_se_borra():
    broker, fake = armar()

    def revienta(ticket=None):
        raise RuntimeError("terminal caida")

    fake.orders_get = revienta

    assert asyncio.run(broker.posicion_existe(777)) is None
