"""Una senal no espera a que la IA termine de pensar otro mensaje.

Medido en la auditoria del 27/09, antes de fondear: el motor consultaba a la IA
con el turno tomado, y la senal que llegaba detras de un mensaje que el parser
no entendio esperaba lo que tardara la IA. En la PC del usuario -sin placa de
video- son ~15 segundos; con el timeout, 45; con una edicion del mismo mensaje,
90; y con los tres bots en cola sobre el mismo Ollama, la real quedaba tercera.
En una de las pruebas el precio corrio 2,7 puntos durante la espera y el filtro
de entrada tarde RECHAZO la senal.

Sin OLLAMA_AUTO_EXECUTE la IA nunca opera: solo anota. Ahora corre de fondo.
"""

from __future__ import annotations

import asyncio
import time

from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.store import Store
from tests.test_engine import build_settings

CHARLA = "Chicos, ya estoy en línea y listo para operar EMPEZAREMOS EN 20 MINUTOS"
SENAL = ("DEAL | GOLD (XAU/USD) BUY XAUUSD 4432 Parameters: TP1: 4436 TP2: 4438 "
         "TP3: 4440 SL: 4424")


class IALenta:
    def __init__(self, segundos):
        self.segundos = segundos
        self.consultas = 0

    async def interpretar(self, _texto, _metadata):
        self.consultas += 1
        await asyncio.sleep(self.segundos)
        return None


def test_la_senal_no_espera_a_la_ia(tmp_path):
    settings = build_settings(tmp_path, enable_ollama=True)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    ia = IALenta(2.0)
    engine = Engine(settings, store, PaperBroker(), ollama=ia)

    async def charla_y_senal():
        charla = asyncio.create_task(
            engine.handle_message(CHARLA, {"chat_id": -100, "message_id": 1}))
        await asyncio.sleep(0.05)  # la senal llega 50 ms despues
        antes = time.perf_counter()
        resultado = await engine.handle_message(SENAL, {"chat_id": -100, "message_id": 2})
        demora = time.perf_counter() - antes
        await charla
        await engine.esperar_la_ia()
        return resultado, demora

    resultado, demora = asyncio.run(charla_y_senal())

    assert ia.consultas == 1, "la charla tenia que ir a la IA: el test no prueba nada"
    assert resultado["status"] == "aceptada"
    assert demora < 0.5, f"la senal espero {demora:.1f} s a la IA"


def test_con_auto_execute_la_ia_sigue_dentro_del_turno(tmp_path):
    """Si la IA puede operar, su interpretacion tiene que entrar en orden con
    las demas: ahi si se la espera (y la real no lo permite: .env.real.example)."""
    settings = build_settings(tmp_path, enable_ollama=True, ollama_auto_execute=True)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    ia = IALenta(0.3)
    engine = Engine(settings, store, PaperBroker(), ollama=ia)

    async def charla_y_senal():
        charla = asyncio.create_task(
            engine.handle_message(CHARLA, {"chat_id": -100, "message_id": 1}))
        await asyncio.sleep(0.05)
        antes = time.perf_counter()
        await engine.handle_message(SENAL, {"chat_id": -100, "message_id": 2})
        demora = time.perf_counter() - antes
        await charla
        return demora

    assert asyncio.run(charla_y_senal()) >= 0.2
