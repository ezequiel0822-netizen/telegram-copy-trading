"""'PARA LA POSICION "BUY 4187", MOVA SU SL...': el breakeven que nombra su posicion.

El 30/09 el canal mando dos de estos (a la de 4187 y a la de 4185) y el bot
los leyo como senales nuevas sin simbolo ni TP: los rechazo y el stop NUNCA se
movio, en las dos cuentas. Ese dia llegaron a TP igual; si el precio se daba
vuelta, cerraban en el stop del canal en vez de en la entrada.
"""

from __future__ import annotations

from tct.signals.models import EventType, Side
from tct.signals.parser import parse_signal
from tests.test_auditoria_ejecucion import SENAL, armar
from tests.test_engine import send

OTRA = "XAUUSD BUY\nEntry 4433\nSL 4425\nTP 4437"

# Los dos mensajes del 30/09, tal cual los mostro el informe.
DEL_CANAL = [
    'PARA LA POSICIÓN "BUY 4187", MOVA SU SL A SER EL SL RESULTANTE ES 4187 BE',
    "PARA LA POSICIÓN “BUY 4185”, MOVA SU SL PARA QUE EL SL RESULTANTE SEA 4185 (BE)",
]


def test_los_mensajes_del_canal_son_mover_el_stop_de_esa_posicion():
    for mensaje, entrada in zip(DEL_CANAL, [4187.0, 4185.0]):
        evento = parse_signal(mensaje)

        assert evento.event_type is EventType.MOVE_SL, mensaje
        assert evento.side is None, "el BUY de la referencia no es una senal nueva"
        assert evento.stop_loss == entrada
        assert (evento.posicion_lado, evento.posicion_entrada) == (Side.BUY, entrada)


def test_a_be_sin_numero_tambien():
    evento = parse_signal('PARA LA POSICIÓN "SELL 4187", MUEVA SU SL A BE')

    assert evento.event_type is EventType.MOVE_SL
    assert evento.move_sl_to_breakeven
    assert (evento.posicion_lado, evento.posicion_entrada) == (Side.SELL, 4187.0)


def test_una_apertura_con_la_palabra_trade_sigue_siendo_apertura():
    evento = parse_signal("TRADE BUY 4187 SL 4180 TP 4195")

    assert evento.event_type is EventType.OPEN
    assert evento.posicion_entrada is None


def test_mantener_el_sl_no_mueve_nada():
    assert parse_signal(
        "LA POSICIÓN QUE TOMAMOS AL PRECIO DE 4191, MANTENER EL SL EN SU LUGAR"
    ) is None


def dos_abiertas(tmp_path):
    engine, store, terminal = armar(tmp_path, max_positions_per_symbol=2,
                                    max_open_trades=2)
    send(engine, SENAL, message_id=100)   # BUY 4432
    send(engine, OTRA, message_id=200)    # BUY 4433
    assert len(terminal.posiciones_abiertas()) == 2
    # El precio subio: el breakeven entra sin chocar con la distancia minima.
    terminal.simbolos["XAUUSD"] = {"bid": 4440.0, "ask": 4441.0}
    return engine, store, terminal


def stop_de(store, terminal, message_id):
    posicion = next(p for p in store.open_positions() if p.signal_message_id == message_id)
    return next(p.sl for p in terminal.posiciones_abiertas()
                if p.ticket == posicion.broker_ticket)


def test_mueve_a_breakeven_solo_la_posicion_nombrada(tmp_path):
    engine, store, terminal = dos_abiertas(tmp_path)
    otra_antes = stop_de(store, terminal, 200)

    resultado = send(engine, 'PARA LA POSICIÓN "BUY 4432", MOVA SU SL A SER EL SL '
                             "RESULTANTE ES 4432 BE", message_id=300)

    assert resultado["status"] == "sl_movido", resultado
    nombrada = next(p for p in store.open_positions() if p.signal_message_id == 100)
    # Al precio de LLENADO, como todo breakeven: no al 4432 del mensaje.
    assert stop_de(store, terminal, 100) == nombrada.entry_real
    assert stop_de(store, terminal, 200) == otra_antes, "le movio el stop a la otra"


def test_si_la_nombrada_ya_cerro_no_toca_a_la_otra(tmp_path):
    engine, store, terminal = dos_abiertas(tmp_path)
    nombrada = next(p for p in store.open_positions() if p.signal_message_id == 100)
    del terminal._posiciones[nombrada.broker_ticket]  # cerro sola en su TP
    otra_antes = stop_de(store, terminal, 200)

    resultado = send(engine, 'PARA LA POSICIÓN "BUY 4432", MOVA SU SL A BE', message_id=300)

    assert resultado["status"] == "rechazada", resultado
    assert stop_de(store, terminal, 200) == otra_antes


def test_si_el_lado_no_coincide_no_toca_nada(tmp_path):
    engine, store, terminal = dos_abiertas(tmp_path)
    antes = sorted(p.sl for p in terminal.posiciones_abiertas())

    resultado = send(engine, 'PARA LA POSICIÓN "SELL 4432", MOVA SU SL A BE', message_id=300)

    assert resultado["status"] == "rechazada", resultado
    assert sorted(p.sl for p in terminal.posiciones_abiertas()) == antes
