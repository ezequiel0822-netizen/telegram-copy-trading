"""El detalle del repaso dice que le hizo la gestion del canal a cada operacion (17/10).

Una venta de David del 12/10 en el repaso perdio 28 puntos, y en vivo el bot la
habia cerrado a 7. El detalle solo mostraba la senal y como termino: no habia
forma de ver que mensaje le movio el stop o la cerro, ni a que hora, para
encontrar donde se separaba el repaso de lo que paso de verdad.
"""

from __future__ import annotations

from tct import cli
from tests.test_engine import engine, send  # noqa: F401 - engine es un fixture

SENAL = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"


def test_cada_operacion_lleva_su_gestion_con_la_hora_del_mensaje(engine):  # noqa: F811
    send(engine, SENAL, message_id=1)
    send(engine, "MOVER SL A 2340", message_id=2)
    send(engine, "Close XAUUSD now", message_id=3)
    mensajes = [
        (SENAL, {"message_id": 1, "date": "2026-10-12T11:38:00+00:00"}),
        ("MOVER SL A 2340", {"message_id": 2, "date": "2026-10-12T11:50:00+00:00"}),
        ("Close XAUUSD now", {"message_id": 3, "date": "2026-10-12T12:02:00+00:00"}),
    ]

    lineas = cli._gestion_por_ticket(engine.store.read_events(), mensajes)

    [ticket] = lineas
    assert len(lineas[ticket]) == 2
    movio, cerro = lineas[ticket]
    assert "movio el SL a 2340" in movio and "<- MOVER SL A 2340" in movio
    assert "la cerro" in cerro and "<- Close XAUUSD now" in cerro
    # La hora es la del mensaje, no la de la PC al correr el repaso.
    assert "12/10" in movio and "12/10" in cerro


def test_sin_gestion_no_hay_lineas(engine):  # noqa: F811
    send(engine, SENAL, message_id=1)

    assert cli._gestion_por_ticket(engine.store.read_events(),
                                   [(SENAL, {"message_id": 1, "date": None})]) == {}
