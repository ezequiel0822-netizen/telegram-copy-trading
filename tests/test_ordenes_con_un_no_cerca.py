"""Una orden con un NO cerca sigue siendo una orden; un pedido negado no.

Segunda revision del 16/10. La primera regla de negacion miraba toda la
clausula, y el canal junta oraciones sin puntuar: "YA NO HAY RIESGO MUEVAN EL
SL A BE" perdia el breakeven. Contra 324 mensajes del estilo del canal, la
regla final se equivoca en 57 (el codigo de antes, en 141) y en NINGUNO hace
peor que el codigo de antes. Estos son los que el primer intento rompia.
"""

from __future__ import annotations

import pytest

from tct.signals.models import EventType
from tct.signals.parser import parse_signal

ACCIONES = {EventType.MOVE_SL, EventType.CLOSE, EventType.PARTIAL_CLOSE, EventType.MOVE_TP}


@pytest.mark.parametrize("mensaje, tipo", [
    ("YA NO HAY RIESGO MUEVAN EL SL A BE", EventType.MOVE_SL),
    ("TP1 ✅ NO HAY RIESGO 🔒 SL A BE", EventType.MOVE_SL),
    ("NO MÁS RIESGO 👉 SL A BE", EventType.MOVE_SL),
    ("NO QUEREMOS PERDER LO GANADO ASÍ QUE MUEVAN EL SL A BE", EventType.MOVE_SL),
    ("Así que chicos, el oro no llegó al TP2 todavía Muevan su SL a BE", EventType.MOVE_SL),
    ("SI TODAVÍA NO MOVIERON EL SL A BE, HÁGANLO AHORA", EventType.MOVE_SL),
    ("QUIEN NO HAYA MOVIDO EL SL, MUÉVALO A BE", EventType.MOVE_SL),
    ("NO CIERREN 🙏 MUEVAN EL SL A BE", EventType.MOVE_SL),
    ("NO CIERREN TODAVIA PERO MUEVAN EL SL A BE", EventType.MOVE_SL),
    ("QUE NO SE LES OLVIDE MOVER EL SL A BE", EventType.MOVE_SL),
    ("NO ME GUSTA COMO SE MUEVE EL ORO 👉 CERRAR TODO", EventType.CLOSE),
    ("EL PRECIO NO RESPETÓ EL SOPORTE CERRAR LA POSICION AHORA", EventType.CLOSE),
    ("NO TENGAN MIEDO DE CERRAR LA POSICION AHORA", EventType.CLOSE),
    ("El precio no se mueve Mejor cerrar ahora", EventType.CLOSE),
    ("CIERRE DEL ORO AHORA", EventType.CLOSE),
    ("PROCEDAN AL CIERRE DE LA OPERACIÓN", EventType.CLOSE),
])
def test_sigue_siendo_una_orden(mensaje, tipo):
    assert parse_signal(mensaje).event_type is tipo


@pytest.mark.parametrize("mensaje, entrada", [
    ('PARA LA POSICIÓN "BUY 4185" NO HAY RIESGO MOVER SL A 4185', 4185.0),
    ('POSICIÓN "BUY 4433": MANTENGAN, PERO MUEVAN EL SL A 4433', 4433.0),
    ('LA POSICIÓN "BUY 4185" ALCANZÓ TP1, MUEVAN SU SL A 4185', 4185.0),
    ('EL NEGOCIO "COMPRA 4184" TOCÓ TP1, ESTABLECER SL 4184', 4184.0),
])
def test_una_sola_posicion_nombrada_es_la_destinataria(mensaje, entrada):
    evento = parse_signal(mensaje)

    assert evento.event_type is EventType.MOVE_SL
    assert evento.posicion_entrada == entrada


@pytest.mark.parametrize("mensaje", [
    "NO CIERREN LA MITAD, VAMOS POR EL TP2",
    "TP1 ✅ NO TOMEN PARCIALES TODAVÍA",
    "¿MOVEMOS EL SL A BE?",
    "¿CERRAR AHORA O ESPERAR?",
    "DON´T CLOSE YET",
    "EL ORO NECESITA CERRAR POR ENCIMA DE 4450 PARA SEGUIR SUBIENDO",
    "CIERRE H4 CONFIRMADO POR ENCIMA DE 4450",
    "BUEN CIERRE CHICOS 🔥",
    "OTRO CIERRE EN TP1 ✅",
    "NO QUIERO QUE CIERREN",
    "NO HAY QUE CERRAR TODAVIA",
    "ESTABLEZCAN EL SL EN 4400 SI QUIEREN DARLE MÁS ESPACIO A LA OPERACIÓN",
    "ESTABLECER SL EN 4150 ES LO QUE YO HARÍA",
])
def test_no_es_una_orden(mensaje):
    evento = parse_signal(mensaje)

    assert evento is None or evento.event_type not in ACCIONES, evento


def test_establezcan_al_principio_y_terminando_en_el_precio_si():
    evento = parse_signal("TP1 ✅\nESTABLEZCAN SU SL EN 4184")

    assert evento.event_type is EventType.MOVE_SL
    assert evento.stop_loss == 4184.0
