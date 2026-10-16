"""Teoria, analisis, relatos y pedidos negados no son ordenes.

Auditoria del 16/10, al agregar ESTABLECER para los breakeven del canal: dos
revisores mandaron ~200 mensajes del estilo del canal contra el parser y el
motor. Lo que encontraron, reproducido:

- "Es importante establecer su stop loss en 4150" se leia como MOVE_SL. Con UNA
  sola posicion abierta el stop se AGRANDABA: 8 puntos -> 26, unos 78 USD mas
  de riesgo a 0.03. (Lo habia metido el primer intento del arreglo.)
- "NO CIERREN LA POSICION, ESPERAMOS TP2" y "un cierre de vela por encima de
  4450" CERRABAN todas las posiciones de oro. (Venia de antes.)
- "NO ESTABLEZCAN EL SL EN BE TODAVIA" mandaba todo a breakeven.
- Con dos posiciones nombradas, ganaba la primera aunque fuera la que el
  mensaje solo contaba ("cerro en TP1").
"""

from __future__ import annotations

import pytest

from tct.signals.models import EventType
from tct.signals.parser import parse_signal
from tests.test_auditoria_ejecucion import armar
from tests.test_engine import send

ACCIONES = {EventType.MOVE_SL, EventType.CLOSE, EventType.PARTIAL_CLOSE, EventType.MOVE_TP}


@pytest.mark.parametrize("mensaje", [
    "Si el precio rompe 4420, podemos establecer nuestro SL por debajo de 4400",
    "No establezcan el SL en 4410 todavía, esperen mi señal",
    "El error de ayer fue no establecer el SL en 4415, perdimos la oportunidad",
    "El oro está en una zona clave. Es importante establecer su stop loss por "
    "debajo de 4405 para proteger el capital.",
    "SI EL PRECIO LLEGA A 4440, ESTABLECER SL 4430",
    "Establezcan siempre un stop loss de al menos 8 puntos en el oro",
    "Al operar oro recomiendo establecer el SL en 4150 si compran en esta zona",
    "ESTABLECER EL SL ES LA REGLA NÚMERO 1 DEL TRADING",
    "Establecer un stop loss siempre es importante para proteger tu cuenta",
    "Necesitamos un cierre de vela por encima de 4450 para confirmar la subida del oro",
    "El cierre diario del oro fue en 4185, por encima del soporte",
    "Cierre semanal: el oro terminó en 4210. Buena semana chicos",
    "NO CIERREN LA POSICIÓN, ESPERAMOS TP2",
    "No cierren todavía, mantengan el SL en su lugar",
    "NO ESTABLEZCAN EL SL EN BE TODAVÍA",
    'LA POSICIÓN "BUY 4433": MANTENER EL SL EN SU LUGAR. LA OTRA, ESTABLECER SL 4432',
])
def test_no_es_una_orden(mensaje):
    evento = parse_signal(mensaje)

    assert evento is None or evento.event_type not in ACCIONES, evento


@pytest.mark.parametrize("mensaje", [
    "CIERRE LA POSICIÓN DE ORO", "CIERREN TODO", "Close XAUUSD now", "CERRAR TODO",
])
def test_cerrar_de_verdad_sigue_cerrando(mensaje):
    assert parse_signal(mensaje).event_type is EventType.CLOSE


def test_negar_el_cierre_no_anula_el_breakeven_de_la_misma_linea():
    evento = parse_signal("NO CIERREN, MUEVAN EL SL A BE")

    assert evento.event_type is EventType.MOVE_SL
    assert evento.move_sl_to_breakeven


def test_no_cierren_el_negocio_y_establecer_sl_mueve_ese_stop():
    """'No la cierren, pongan el SL en 4432': antes la CERRABA."""
    evento = parse_signal('NO CIERREN EL NEGOCIO "COMPRA 4432", ESTABLECER SL 4432')

    assert evento.event_type is EventType.MOVE_SL
    assert evento.posicion_entrada == 4432.0


def test_la_posicion_que_se_cuenta_no_es_la_que_se_gestiona():
    evento = parse_signal('EL NEGOCIO "COMPRA 4433" CERRÓ EN TP1. AHORA PARA EL '
                          'NEGOCIO "COMPRA 4432" ESTABLECER SL EN BE')

    assert evento.event_type is EventType.MOVE_SL
    assert evento.posicion_entrada == 4432.0


@pytest.mark.parametrize("mensaje", [
    'PARA EL NEGOCIO "COMPRA 4432" Y EL NEGOCIO "COMPRA 4433" ESTABLECER SL EN BE',
    'PARA EL NEGOCIO "COMPRA 4432" ESTABLECER SL 4432\n'
    'PARA EL NEGOCIO "COMPRA 4433" ESTABLECER SL 4433',
])
def test_dos_negocios_nombrados_van_cada_uno_a_su_breakeven(mensaje):
    evento = parse_signal(mensaje)

    assert evento.event_type is EventType.MOVE_SL
    assert evento.move_sl_to_breakeven and evento.stop_loss is None
    assert evento.posicion_entrada is None, "no se elige una sola"


# --------------------------------------------------------------------------
# En el motor, con la terminal falsa
# --------------------------------------------------------------------------

SENAL = "XAUUSD BUY\nEntry 4432\nSL 4424\nTP 4436"


def una_abierta(tmp_path):
    engine, store, terminal = armar(tmp_path)
    send(engine, SENAL, message_id=100)
    assert len(terminal.posiciones_abiertas()) == 1
    return engine, store, terminal


def test_la_teoria_con_un_precio_no_agranda_el_stop_de_la_unica_posicion(tmp_path):
    engine, _, terminal = una_abierta(tmp_path)

    send(engine, "El oro está en una zona clave. Es importante establecer su stop "
                 "loss en 4400 para proteger el capital.", message_id=300)

    assert terminal.posiciones_abiertas()[0].sl == 4424.0


def test_no_cierren_la_posicion_no_la_cierra(tmp_path):
    engine, _, terminal = una_abierta(tmp_path)

    send(engine, "NO CIERREN LA POSICIÓN, ESPERAMOS TP2", message_id=300)

    assert len(terminal.posiciones_abiertas()) == 1


def test_un_cierre_de_vela_no_cierra_nada(tmp_path):
    engine, _, terminal = una_abierta(tmp_path)

    send(engine, "Necesitamos un cierre de vela por encima de 4450 para confirmar",
         message_id=300)

    assert len(terminal.posiciones_abiertas()) == 1


@pytest.mark.parametrize("mensaje", [
    "NO OLVIDEN MOVER EL SL A BE",
    "No se olviden de mover el stop a breakeven",
    "No duden en mover el SL a BE ahora",
    "NO DEJEN DE MOVER EL SL A BE",
    "Don't forget to move SL to BE",
])
def test_no_olviden_mover_el_stop_es_una_orden(mensaje):
    """Una negacion que pide hacerlo: perderla es un breakeven que no se aplica."""
    assert parse_signal(mensaje).event_type is EventType.MOVE_SL
