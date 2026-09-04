"""Que pasa cuando el broker RECHAZA una orden.

Estos tests existen por un punto ciego concreto: todo el testing corria contra
el broker de papel, que nunca devuelve ok=False. La rama de error del motor
nunca se ejecutaba, y por eso 183 tests en verde convivian con bugs que dejan
plata corriendo sin registro.

Un broker rechaza ordenes todo el tiempo por motivos normales: mercado
cerrado, margen insuficiente, requote, precio invalido, AutoTrading apagado.
No es un caso raro.
"""

from __future__ import annotations

import pytest

from tct.brokers.base import OrderResult
from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.store import Store
from tests.test_engine import build_settings, send


class BrokerQueRechaza(PaperBroker):
    """Broker que acepta o rechaza segun se le indique, operacion por operacion."""

    def __init__(self, *, abrir=True, cerrar=True, mover_sl=True) -> None:
        super().__init__()
        self.permite = {"abrir": abrir, "cerrar": cerrar, "mover_sl": mover_sl}
        self.intentos: list[str] = []

    async def open_order(self, **kwargs) -> OrderResult:
        self.intentos.append("abrir")
        if not self.permite["abrir"]:
            return OrderResult(
                False, "open", "margen insuficiente", symbol=kwargs.get("symbol")
            )
        return await super().open_order(**kwargs)

    async def close_position(self, **kwargs) -> OrderResult:
        self.intentos.append("cerrar")
        if not self.permite["cerrar"]:
            return OrderResult(
                False, "close", "mercado cerrado", symbol=kwargs.get("symbol")
            )
        return await super().close_position(**kwargs)

    async def modify_stop_loss(self, **kwargs) -> OrderResult:
        self.intentos.append("mover_sl")
        if not self.permite["mover_sl"]:
            return OrderResult(
                False, "modify_sl", "stop invalido", symbol=kwargs.get("symbol")
            )
        return await super().modify_stop_loss(**kwargs)


def armar(tmp_path, broker=None, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, broker or BrokerQueRechaza())
    return settings, store, engine


SENAL = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"


# --------------------------------------------------------------------------
# Apertura rechazada: no debe quedar una posicion fantasma
# --------------------------------------------------------------------------


def test_si_el_broker_rechaza_la_apertura_no_se_registra_la_posicion(tmp_path):
    """Sin esto queda una posicion que existe en el estado y no en el broker:
    bloquea el simbolo para siempre y ocupa cupo de MAX_OPEN_TRADES."""
    _, store, engine = armar(tmp_path, BrokerQueRechaza(abrir=False))

    resultado = send(engine, SENAL)

    assert resultado["status"] != "aceptada", "el broker rechazo, no puede decir aceptada"
    assert store.open_positions() == [], "quedo una posicion que el broker nunca abrio"


def test_la_senal_rechazada_queda_registrada_igual(tmp_path):
    """No operar no puede significar no dejar rastro."""
    _, store, engine = armar(tmp_path, BrokerQueRechaza(abrir=False))
    send(engine, SENAL)

    eventos = store.read_events()
    assert eventos, "no quedo ningun evento de la senal rechazada"
    assert any("margen insuficiente" in str(e) for e in eventos)


def test_tras_un_rechazo_la_misma_senal_se_puede_reintentar(tmp_path):
    """Si la posicion fantasma quedara, el simbolo quedaba bloqueado por la
    regla de 'ya hay una posicion abierta'."""
    _, store, engine = armar(tmp_path, BrokerQueRechaza(abrir=False))
    send(engine, SENAL, message_id=1)

    engine.broker.permite["abrir"] = True
    resultado = send(engine, SENAL, message_id=2)

    assert resultado["status"] == "aceptada"
    assert len(store.open_positions()) == 1


# --------------------------------------------------------------------------
# Cierre rechazado: la posicion sigue viva, no se puede borrar del estado
# --------------------------------------------------------------------------


def test_si_el_broker_rechaza_el_cierre_la_posicion_sigue_registrada(tmp_path):
    """Borrarla dejaria la operacion corriendo en el broker sin ningun
    registro: ningun cierre posterior la encontraria."""
    _, store, engine = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    assert len(store.open_positions()) == 1

    engine.broker.permite["cerrar"] = False
    resultado = send(engine, "Close XAUUSD now", message_id=2)

    assert len(store.open_positions()) == 1, "se borro del estado y sigue viva en el broker"
    assert resultado["status"] != "cerrada", "informo un cierre que no ocurrio"


def test_tras_un_cierre_fallido_se_puede_reintentar(tmp_path):
    _, store, engine = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    engine.broker.permite["cerrar"] = False
    send(engine, "Close XAUUSD now", message_id=2)

    engine.broker.permite["cerrar"] = True
    send(engine, "Close XAUUSD now", message_id=3)

    assert store.open_positions() == [], "el reintento tenia que cerrarla"


# --------------------------------------------------------------------------
# Mover el SL rechazado: el estado no puede mentir sobre donde esta el stop
# --------------------------------------------------------------------------


def test_si_falla_mover_el_sl_el_estado_conserva_el_anterior(tmp_path):
    _, store, engine = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    assert store.open_positions()[0].stop_loss == 2335.0

    engine.broker.permite["mover_sl"] = False
    send(engine, "Move SL to BE", message_id=2)

    assert store.open_positions()[0].stop_loss == 2335.0, (
        "el estado dice que el stop se movio y en el broker sigue donde estaba"
    )


# --------------------------------------------------------------------------
# Una edicion no puede reabrir una operacion ya cerrada
# --------------------------------------------------------------------------


def test_editar_el_mensaje_original_no_reabre_la_operacion(tmp_path):
    """Los canales editan el mensaje viejo para marcar el resultado. Sin esta
    guarda, esa edicion mandaba una orden nueva horas despues, a precio de
    mercado y con el SL del mensaje original."""
    _, store, engine = armar(tmp_path)

    send(engine, SENAL, message_id=555)
    assert len(store.open_positions()) == 1

    send(engine, "Close XAUUSD now", message_id=556)
    assert store.open_positions() == []

    resultado = send(engine, SENAL + "\nTP2 2370", message_id=555, is_edit=True)

    assert resultado["status"] != "aceptada", "una edicion reabrio la operacion"
    assert store.open_positions() == []


def test_una_edicion_de_un_mensaje_que_nunca_opero_si_se_procesa(tmp_path):
    """Si la senal original fue rechazada y el grupo la corrige editandola,
    esa correccion tiene que poder ejecutarse."""
    _, store, engine = armar(tmp_path)

    # SL del lado equivocado: se rechaza.
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2355\nTP 2365", message_id=777)
    assert store.open_positions() == []

    resultado = send(engine, SENAL, message_id=777, is_edit=True)

    assert resultado["status"] == "aceptada", "la correccion tenia que poder operar"


# --------------------------------------------------------------------------
# Dos senales a la vez no pueden saltearse los topes
# --------------------------------------------------------------------------


def test_dos_senales_simultaneas_respetan_el_tope_de_abiertas(tmp_path):
    """El riesgo se evalua antes de un await y la posicion se registra despues:
    sin candado, dos mensajes casi simultaneos abren dos operaciones donde el
    limite es una."""
    import asyncio

    settings = build_settings(tmp_path, max_open_trades=1,
                              allowed_symbols={"XAUUSD", "EURUSD"})
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker())

    async def correr():
        return await asyncio.gather(
            engine.handle_message(SENAL, {"message_id": 1, "chat_id": -100}),
            engine.handle_message(
                "EURUSD BUY\nEntry 1.08\nSL 1.07\nTP 1.09",
                {"message_id": 2, "chat_id": -100},
            ),
        )

    asyncio.run(correr())

    assert len(store.open_positions()) <= 1, (
        f"se abrieron {len(store.open_positions())} con MAX_OPEN_TRADES=1"
    )


# --------------------------------------------------------------------------
# Una senal que nunca llego a operar no puede gastar el cupo del dia
# --------------------------------------------------------------------------


def test_una_apertura_fallida_no_gasta_cupo_diario(tmp_path):
    """MAX_SIGNALS_PER_DAY limita cuantas OPERACIONES toma el bot por dia. Una
    senal que el broker rechazo no es una operacion.

    El caso real: el canal manda senales de BTCUSD y el broker conectado no
    expone ese instrumento. Cada una fallaba al abrir y aun asi consumia un
    lugar del cupo, dejando sin lugar a las senales que si podian operar.
    """
    _, store, engine = armar(tmp_path, BrokerQueRechaza(abrir=False))

    send(engine, SENAL)

    assert store.signals_today() == 0, (
        "una senal que no abrio ninguna posicion gasto cupo del dia"
    )


def test_una_apertura_exitosa_si_gasta_cupo(tmp_path):
    """Lo que no hay que romper: el tope tiene que seguir frenando de verdad."""
    _, store, engine = armar(tmp_path)

    send(engine, SENAL)

    assert store.signals_today() == 1


def test_un_simbolo_que_el_broker_no_opera_no_agota_el_dia(tmp_path):
    """La consecuencia practica, con el cupo chico que usa el usuario."""
    _, store, engine = armar(
        tmp_path, BrokerQueRechaza(abrir=False),
        max_signals_per_day=2, allowed_symbols={"XAUUSD", "EURUSD"},
    )

    for i in range(5):
        send(engine, SENAL, message_id=100 + i)

    engine.broker.permite["abrir"] = True
    resultado = send(engine, "EURUSD BUY\nEntry 1.08\nSL 1.07\nTP 1.09", message_id=200)

    assert resultado["status"] == "aceptada", (
        "cinco senales que nunca operaron agotaron el cupo de las que si podian"
    )
