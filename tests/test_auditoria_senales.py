"""Senales y estado: lo que encontro la auditoria del 28/09.

Con la real en DOS posiciones de oro a la vez, varios caminos de gestion
tocaban la posicion equivocada, y el bot ejecutaba mensajes viejos. Cada test
reproduce uno de esos casos.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from tct.brokers.mt5_native import MAGIA, MT5NativeBroker
from tct.engine import Engine
from tct.store import Store
from tct.telegram.control import ControlTelegram
from tests.test_auditoria_ejecucion import SENAL, Terminal, armar
from tests.fake_mt5 import enchufar
from tests.test_engine import build_settings, send

OTRA = "XAUUSD BUY\nEntry 4433\nSL 4425\nTP 4437"


def hace(minutos: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()


def sl_en_mt5(terminal):
    return sorted(p.sl for p in terminal.posiciones_abiertas())


# --------------------------------------------------------------------------
# Nada de hace mas de 10 minutos ejecuta
# --------------------------------------------------------------------------


def test_una_edicion_tardia_de_un_mover_sl_no_se_ejecuta(tmp_path):
    """El canal edita horas despues para anotar el resultado; la edicion se
    seguia leyendo como mover el stop, y movia el de OTRA senal."""
    engine, store, terminal = armar(tmp_path, max_positions_per_symbol=2,
                                    max_open_trades=2)
    send(engine, SENAL, message_id=100, date=hace(0))
    antes = sl_en_mt5(terminal)

    resultado = send(engine, "MOVER SL A 4400 ✅ +40 pips", message_id=101,
                     is_edit=True, date=hace(180))

    assert resultado["status"] == "edicion_ignorada"
    assert sl_en_mt5(terminal) == antes


def test_un_mensaje_nuevo_entregado_tarde_no_abre(tmp_path):
    """Al volver internet, Telegram entrega lo perdido con su hora original."""
    engine, store, terminal = armar(tmp_path)

    resultado = send(engine, SENAL, message_id=100, date=hace(40))

    assert resultado["status"] == "ignorado_por_viejo"
    assert terminal.posiciones_abiertas() == []


def test_un_mensaje_reciente_opera_normal(tmp_path):
    engine, store, terminal = armar(tmp_path)

    assert send(engine, SENAL, message_id=100, date=hace(1))["status"] == "aceptada"


def test_simular_reproduce_mensajes_viejos_a_proposito(tmp_path):
    engine, store, terminal = armar(tmp_path)

    resultado = send(engine, SENAL, message_id=100, date=hace(120), reproduccion=True)

    assert resultado["status"] == "aceptada"


# --------------------------------------------------------------------------
# Una respuesta a una senal aplica a ESA senal
# --------------------------------------------------------------------------


def dos_senales(tmp_path):
    engine, store, terminal = armar(tmp_path, max_positions_per_symbol=2,
                                    max_open_trades=2)
    send(engine, SENAL, message_id=100)
    send(engine, OTRA, message_id=200)
    assert len(terminal.posiciones_abiertas()) == 2
    return engine, store, terminal


def test_cerrar_respondiendo_a_una_senal_no_cierra_la_otra(tmp_path):
    engine, store, terminal = dos_senales(tmp_path)

    send(engine, "cerrar", message_id=300, reply_to_message_id=100)

    quedan = store.open_positions()
    assert [p.signal_message_id for p in quedan] == [200]
    assert len(terminal.posiciones_abiertas()) == 1


def test_responder_a_una_senal_que_ya_cerro_no_toca_a_la_otra(tmp_path):
    engine, store, terminal = dos_senales(tmp_path)
    de_la_100 = next(p for p in store.open_positions() if p.signal_message_id == 100)
    del terminal._posiciones[de_la_100.broker_ticket]  # cerro sola en su TP
    antes = sl_en_mt5(terminal)

    resultado = send(engine, "mover a breakeven", message_id=300, reply_to_message_id=100)

    assert resultado["status"] == "rechazada"
    assert sl_en_mt5(terminal) == antes, "le movio el stop a la otra senal"


# --------------------------------------------------------------------------
# Una pendiente viva no se suelta del registro
# --------------------------------------------------------------------------


def test_mover_el_sl_de_una_pendiente_no_la_suelta():
    terminal = Terminal()
    broker = enchufar(MT5NativeBroker(_ajustes()), terminal)
    pendiente = terminal.poner_pendiente(900001, symbol="XAUUSD", volume=0.05)
    pendiente.magic = MAGIA

    movida = asyncio.run(broker.modify_stop_loss(ticket=900001, symbol="XAUUSD",
                                                 stop_loss=4430.0))
    cerrada = asyncio.run(broker.close_position(ticket=900001, symbol="XAUUSD"))

    assert not movida.ok and not movida.raw.get("ausente"), "la daba por inexistente"
    assert cerrada.ok, "cerrar una pendiente es cancelarla"
    assert terminal.orders_get() == ()


def _ajustes():
    class Ajustes:
        mt5_login = ""
        mt5_broker_profile = "default"
        max_lot = 0.05
        is_live = False
        trading_mode = "PAPER_AND_MT5_DEMO"
    return Ajustes()


# --------------------------------------------------------------------------
# Al arrancar, lo que hay en MetaTrader y el registro no tiene
# --------------------------------------------------------------------------


def test_con_el_estado_perdido_las_posiciones_vivas_se_toman_al_arrancar(tmp_path):
    engine, store, terminal = dos_senales(tmp_path)
    settings = engine.settings
    settings.state_path.unlink()  # el state.json se perdio

    nuevo = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    motor = Engine(settings, nuevo, engine.broker)
    asyncio.run(motor.reconciliar_al_arrancar())

    assert len(nuevo.open_positions()) == 2
    assert {p.broker_ticket for p in nuevo.open_positions()} == {
        p.ticket for p in terminal.posiciones_abiertas()}
    # Y cuentan para el tope: la tercera senal no entra.
    assert send(motor, SENAL.replace("4432", "4434"), message_id=300)["status"] == "rechazada"
    assert len(terminal.posiciones_abiertas()) == 2


def test_al_arrancar_no_se_duplica_lo_que_ya_esta_registrado(tmp_path):
    engine, store, terminal = dos_senales(tmp_path)

    asyncio.run(engine.reconciliar_al_arrancar())

    assert len(store.open_positions()) == 2


# --------------------------------------------------------------------------
# La correccion del SL que manda el canal
# --------------------------------------------------------------------------


def test_una_correccion_del_sl_dentro_de_la_ventana_se_aplica(tmp_path):
    engine, store, terminal = armar(tmp_path)
    send(engine, SENAL.replace("SL 4424", "SL 4324"), message_id=100, date=hace(0))

    resultado = send(engine, SENAL, message_id=100, is_edit=True, date=hace(1))

    assert resultado["status"] == "sl_corregido"
    assert sl_en_mt5(terminal) == [4424.0]
    assert store.open_positions()[0].stop_loss == 4424.0


def test_una_correccion_del_sl_del_lado_equivocado_no_se_aplica(tmp_path):
    engine, store, terminal = armar(tmp_path)
    send(engine, SENAL, message_id=100, date=hace(0))

    resultado = send(engine, SENAL.replace("SL 4424", "SL 4440"), message_id=100,
                     is_edit=True, date=hace(1))

    assert resultado["status"] != "sl_corregido"
    assert sl_en_mt5(terminal) == [4424.0]


def test_un_sl_mas_alla_del_tope_no_abre(tmp_path):
    engine, store, terminal = armar(tmp_path, max_stop_distance_pct=0.5)

    resultado = send(engine, SENAL.replace("SL 4424", "SL 4324"), message_id=100)

    assert resultado["status"] == "rechazada"
    assert "MAX_STOP_DISTANCE_PCT" in " ".join(resultado["reasons"])


def test_sin_tope_de_sl_se_abre_como_siempre(tmp_path):
    engine, store, terminal = armar(tmp_path)

    assert send(engine, SENAL.replace("SL 4424", "SL 4324"),
                message_id=100)["status"] == "aceptada"


# --------------------------------------------------------------------------
# La misma senal dos veces, la pausa y /cerrar todo
# --------------------------------------------------------------------------


def test_la_misma_senal_reenviada_no_abre_dos_veces(tmp_path):
    engine, store, terminal = armar(tmp_path, max_positions_per_symbol=2,
                                    max_open_trades=2)
    send(engine, SENAL, message_id=100)

    resultado = send(engine, SENAL, message_id=105)

    assert resultado["status"] == "rechazada"
    assert len(terminal.posiciones_abiertas()) == 1


def test_en_pausa_no_abre_pero_el_breakeven_se_aplica(tmp_path):
    engine, store, terminal = armar(tmp_path)
    send(engine, SENAL, message_id=100)
    store.pause("prueba")

    abrir = send(engine, OTRA, message_id=200)
    mover = send(engine, "MOVER SL A 4432", message_id=201)

    assert abrir["status"] == "pausado"
    assert mover["status"] == "sl_movido", mover
    # 4432 es la entrada: es un breakeven, y va al precio real de llenado.
    assert sl_en_mt5(terminal) == [4432.5]


def test_cerrar_todo_espera_a_la_senal_que_se_esta_abriendo(tmp_path):
    engine, store, terminal = armar(tmp_path)
    control = ControlTelegram(engine.settings, store, engine)

    async def escenario():
        await engine._turno.acquire()  # una senal a medio abrir
        cierre = asyncio.create_task(control._cerrar_todo())
        await asyncio.sleep(0.05)
        esperando = not cierre.done()
        engine._turno.release()
        await cierre
        return esperando

    assert asyncio.run(escenario()), "cerro sin esperar el turno del motor"
