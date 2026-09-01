"""Regresiones de mensajes que el parser interpretaba MAL y ejecutaba.

Todos estos venian de una revision que los verifico de punta a punta contra el
motor: no eran teoricos, abrian posiciones. Un mensaje que no se entiende es
barato (se descarta o va a la IA); uno que se entiende AL REVES abre una
operacion que nadie pidio.
"""

from __future__ import annotations

import pytest

from tct.signals.models import EventType
from tct.signals.parser import parse_signal


# --------------------------------------------------------------------------
# Recaps y resultados: el canal cuenta lo que YA paso, no pide nada
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mensaje",
    [
        "\u2705 CERRADA EN GANANCIA\nGOLD SELL 2350\nSL 2360\nTP 2340\n+100 pips",
        "RESULTADO: XAUUSD BUY 2345 SL 2335 TP 2355 -> TP1 alcanzado \u2705",
        "\u274c SL alcanzado. GOLD BUY 2345 SL 2335 TP 2355. Seguimos",
        "TP2 ALCANZADO \u2705 XAUUSD BUY 2345 SL 2335 TP 2365",
        "Operacion cerrada en profit. GOLD SELL 2350 SL 2360 TP 2340",
        "\u2705\u2705 GOLD BUY 2345 SL 2335 TP 2355 | +250 pips esta semana",
    ],
)
def test_un_recap_no_abre_una_operacion(mensaje):
    evento = parse_signal(mensaje)
    assert evento is None or evento.event_type is not EventType.OPEN, (
        f"un mensaje de resultado se interpreto como senal nueva: {evento}"
    )


def test_una_senal_normal_con_un_tilde_sigue_siendo_senal():
    """El tilde solo no puede desactivar las senales: los canales lo usan de adorno."""
    evento = parse_signal("\u2705 XAUUSD BUY\nEntry 2345\nSL 2335\nTP1 2355\nTP2 2365")
    assert evento.event_type is EventType.OPEN
    assert evento.entry == 2345.0


# --------------------------------------------------------------------------
# Mover a breakeven: los pips no son el stop loss
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mensaje",
    [
        "Move SL to BE now, +80 pips",
        "Muevan SL a BE, ya llevamos 50 pips",
        "SL a breakeven, +45 pips",
        "TP1 done, SL to BE. 55 pips secured",
        "Mover SL a BE, llevamos 120 pips",
    ],
)
def test_mover_a_breakeven_no_toma_los_pips_como_stop(mensaje):
    evento = parse_signal(mensaje)
    assert evento.event_type is EventType.MOVE_SL
    assert evento.move_sl_to_breakeven is True, "el numero desactivo el breakeven"
    assert evento.stop_loss is None, f"tomo {evento.stop_loss} como stop loss"


def test_mover_el_sl_a_un_precio_concreto_sigue_funcionando():
    evento = parse_signal("Move SL to 2350")
    assert evento.stop_loss == 2350.0
    assert evento.move_sl_to_breakeven is False


# --------------------------------------------------------------------------
# El simbolo es el de la senal, no el que se menciona al pasar
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mensaje,esperado",
    [
        ("Mientras el gold descansa, BTC BUY 65000\nSL 64000\nTP 67000", "BTCUSD"),
        ("ETH BUY 3500\nSL 3400\nTP 3700\nEl oro lo dejamos quieto", "ETHUSD"),
        ("El oro sigue lateral. DAX SELL 18200\nSL 18300\nTP 18000", "GER40"),
    ],
)
def test_gana_el_simbolo_de_la_senal_y_no_el_mencionado_al_pasar(mensaje, esperado):
    evento = parse_signal(mensaje)
    assert evento.symbol == esperado, (
        f"se quedo con el instrumento equivocado: {evento.symbol}"
    )


# --------------------------------------------------------------------------
# Un @usuario no es un precio de entrada
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mensaje,entrada",
    [
        ("GOLD BUY LIMIT 2340\nSL 2330\nTP 2360\nCanal @gold2345", 2340.0),
        ("XAUUSD BUY LIMIT 2340\nSL 2330\nTP 2360\n@fx2350club", 2340.0),
        ("GOLD BUY 2345\nSL 2335\nTP 2360\n@vipsignals2024", 2345.0),
    ],
)
def test_un_arroba_de_usuario_no_pisa_la_entrada(mensaje, entrada):
    evento = parse_signal(mensaje)
    assert evento.entry == entrada, f"un @usuario cambio la entrada a {evento.entry}"


def test_el_arroba_como_precio_sigue_funcionando():
    """'BUY @ 2345' es formato legitimo y tiene que seguir andando."""
    evento = parse_signal("GBPUSD BUY @ 1.2650\nSL 1.2600\nTP 1.2700")
    assert evento.entry == pytest.approx(1.2650)


# --------------------------------------------------------------------------
# Los pips no son precios
# --------------------------------------------------------------------------


def test_los_pips_no_se_leen_como_take_profit():
    evento = parse_signal("XAUUSD BUY 2345\nSL 2335\nTP 2355\nObjetivo 100 pips")
    assert evento.take_profits == [2355.0], f"se colo un pip: {evento.take_profits}"


def test_texto_de_cierre_al_final_no_contamina_los_tp():
    evento = parse_signal(
        "XAUUSD BUY 2345\nSL 2335\nTP1 2355\nTP2 2365\n\nValido 24hs. Grupo VIP 2024"
    )
    assert evento.take_profits == [2355.0, 2365.0], (
        f"el texto del final se colo como TP: {evento.take_profits}"
    )


# --------------------------------------------------------------------------
# Mensajes reales del canal del usuario
# --------------------------------------------------------------------------
# Salieron de correr `tct simular` contra el grupo de verdad. El del "dia
# magico" se clasificaba como CLOSE y habria cerrado todas las posiciones
# abiertas: la palabra "cerrar" estaba ahi, pero contando, no pidiendo.


@pytest.mark.parametrize(
    "mensaje",
    [
        "Hoy es simplemente un dia magico. Pudimos cerrar otra operacion en ganancia",
        "Cerramos todo por hoy muchachos, buen dia",
        "Logramos cerrar en TP2, felicitaciones a todos",
        "Conseguimos cerrar 3 operaciones seguidas hoy",
        "We closed another one in profit today",
    ],
)
def test_una_cronica_no_es_una_orden(mensaje):
    """Narrar que se cerro algo no puede cerrar nada."""
    evento = parse_signal(mensaje)
    assert evento is None or evento.event_type is not EventType.CLOSE, (
        f"un mensaje que narra se interpreto como orden: {evento}"
    )


@pytest.mark.parametrize(
    "mensaje,esperado",
    [
        ("Cerrar todo ahora", EventType.CLOSE),
        ("Cierren la mitad del oro", EventType.PARTIAL_CLOSE),
        ("Close all positions", EventType.CLOSE),
        ("Close 50% XAUUSD", EventType.PARTIAL_CLOSE),
        ("MOVER SL A 4444", EventType.MOVE_SL),
    ],
)
def test_las_ordenes_de_verdad_siguen_funcionando(mensaje, esperado):
    """El filtro de cronicas no puede tragarse las ordenes imperativas."""
    evento = parse_signal(mensaje)
    assert evento is not None, f"se descarto una orden legitima: {mensaje}"
    assert evento.event_type is esperado


def test_el_formato_deal_del_canal_se_lee_completo():
    """Formato real: 'DEAL | GOLD (XAU/USD) BUY XAUUSD 4456'."""
    evento = parse_signal(
        "DEAL | GOLD (XAU/USD) BUY XAUUSD 4456\n"
        "Parameters:\nTP1: 4460\nTP2: 4462\nTP3: 4464\nSL: 4448"
    )
    assert evento.event_type is EventType.OPEN
    assert evento.symbol == "XAUUSD"
    assert evento.entry == 4456.0
    assert evento.stop_loss == 4448.0
    assert evento.take_profits == [4460.0, 4462.0, 4464.0]
