"""Una ventana en "Seleccionar" no puede congelar al bot.

Auditoria del 27/09: en la consola de Windows, un clic en la ventana la pone en
modo seleccion y todo lo que se escribe en ella queda frenado hasta apretar Esc
o Enter. El bot escribia sus logs desde el mismo hilo que lee Telegram y manda
las ordenes: la proxima linea de log lo congelaba entero, sin limite. Pasa sin
querer, al copiar lineas para pegarlas en un chat.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from tct import cli


class ConsolaTrabada(logging.Handler):
    """Una consola en "Seleccionar": escribir en ella no vuelve hasta que se suelta."""

    def __init__(self):
        super().__init__()
        self.suelta = threading.Event()
        self.escrito: list[str] = []

    def emit(self, record):
        self.suelta.wait(5)
        self.escrito.append(record.getMessage())


def test_con_la_consola_trabada_loguear_no_frena(monkeypatch):
    raiz = logging.getLogger()
    antes = list(raiz.handlers)
    consola = ConsolaTrabada()
    for h in antes:
        raiz.removeHandler(h)
    raiz.addHandler(consola)
    try:
        with cli._logs_sin_frenar_al_bot():
            inicio = time.perf_counter()
            logging.getLogger("tct").warning("una senal entro")
            demora = time.perf_counter() - inicio
            consola.suelta.set()
        assert demora < 0.5, f"el log freno al bot {demora:.1f} s"
        # Al salir se vacio la cola: la linea no se perdio.
        assert consola.escrito == ["una senal entro"]
        assert raiz.handlers == [consola], "no dejo los logs como estaban"
    finally:
        raiz.removeHandler(consola)
        for h in antes:
            raiz.addHandler(h)


def test_apagar_la_seleccion_fuera_de_una_consola_no_rompe():
    cli._sin_seleccion_con_el_mouse()


def test_el_vigilante_revisa_con_el_turno_tomado():
    """Nunca le habla a MetaTrader a la vez que una orden."""
    from tct.engine import Engine

    vista = {}

    class Broker:
        async def revisar_conexion(self):
            vista["turno_tomado"] = motor._turno.locked()

    motor = Engine.__new__(Engine)
    motor.broker = Broker()
    motor._turno = asyncio.Lock()
    motor._sin_confirmar = []

    asyncio.run(motor.revisar_el_broker())

    assert vista == {"turno_tomado": True}
