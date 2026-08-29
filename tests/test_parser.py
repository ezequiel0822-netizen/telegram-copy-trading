"""Tests del parser con mensajes al estilo de un grupo real.

Los casos con emojis, markdown y comas de miles no son decorativos: cada uno
corresponde a una forma concreta en la que el parser fallaba antes.
"""

from __future__ import annotations

import pytest

from tct.signals.models import EventType, OrderType, Side
from tct.signals.parser import parse_signal


# --------------------------------------------------------------------------
# Aperturas
# --------------------------------------------------------------------------


def test_senal_basica():
    event = parse_signal("XAUUSD BUY\nEntry 2345\nSL 2335\nTP1 2355\nTP2 2365")
    assert event is not None
    assert event.event_type is EventType.OPEN
    assert event.symbol == "XAUUSD"
    assert event.side is Side.BUY
    assert event.entry == 2345.0
    assert event.stop_loss == 2335.0
    assert event.take_profits == [2355.0, 2365.0]
    assert event.warnings == []


def test_alias_gold_se_normaliza_a_xauusd():
    event = parse_signal("GOLD SELL 2350\nSL 2360\nTP 2330")
    assert event.symbol == "XAUUSD"
    assert event.side is Side.SELL


@pytest.mark.parametrize(
    "alias,esperado",
    [
        ("GOLD", "XAUUSD"), ("XAU", "XAUUSD"), ("NAS", "NAS100"),
        ("NASDAQ", "NAS100"), ("US30", "US30"), ("DOW", "US30"),
        ("DAX", "GER40"), ("BTC", "BTCUSD"),
    ],
)
def test_alias_de_simbolos(alias, esperado):
    event = parse_signal(f"{alias} BUY 100\nSL 90\nTP 110")
    assert event.symbol == esperado


def test_pares_de_divisas_con_y_sin_separador():
    assert parse_signal("EURUSD BUY 1.08\nSL 1.07\nTP 1.09").symbol == "EURUSD"
    assert parse_signal("EUR/USD BUY 1.08\nSL 1.07\nTP 1.09").symbol == "EURUSD"


def test_emojis_y_markdown_no_rompen_el_parseo():
    event = parse_signal("\U0001F534 **GOLD SELL** \U0001F4C9\nSL: 2355\nTP: 2335")
    assert event.symbol == "XAUUSD"
    assert event.side is Side.SELL
    assert event.stop_loss == 2355.0


def test_rango_de_entrada():
    event = parse_signal("GOLD SELL LIMIT 2345-2347\nSL: 2355\nTP: 2335 / 2325 / 2315")
    assert event.order_type is OrderType.LIMIT
    assert event.side is Side.SELL, "el masking del tipo de orden no debe comerse el SELL"
    assert event.entry_low == 2345.0
    assert event.entry_high == 2347.0
    assert event.has_entry_range
    assert event.entry == 2346.0, "una entrada por rango se resume en su punto medio"
    assert event.take_profits == [2335.0, 2325.0, 2315.0]


def test_tps_en_una_sola_linea_separados_por_barra():
    event = parse_signal("XAUUSD BUY 2345\nSL 2335\nTP: 2355 / 2365 / 2375")
    assert event.take_profits == [2355.0, 2365.0, 2375.0]


def test_precio_decimal_no_se_confunde_con_indice_de_tp():
    """Regresion: 'TP 1.2700' se leia como TP indice 1 y precio 2700."""
    event = parse_signal("GBPUSD BUY @ 1.2650\nSL 1.2600\nTP 1.2700")
    assert event.entry == pytest.approx(1.2650)
    assert event.stop_loss == pytest.approx(1.2600)
    assert event.take_profits == [pytest.approx(1.2700)]


def test_precio_entero_no_se_come_como_indice_de_tp():
    """Regresion: 'TP 2330' se leia como indice y quedaba sin take profit."""
    event = parse_signal("GOLD SELL 2350\nSL 2360\nTP 2330")
    assert event.take_profits == [2330.0]


def test_separador_de_miles_con_coma():
    event = parse_signal("US30 BUY\nEntry 39,500\nSL 39,300\nTP1 39,800\nTP2 40,000")
    assert event.entry == 39500.0
    assert event.stop_loss == 39300.0
    assert event.take_profits == [39800.0, 40000.0]


def test_coma_decimal_en_espanol():
    event = parse_signal("XAUUSD BUY\nEntrada 2345,50\nSL 2335\nTP 2360")
    assert event.entry == pytest.approx(2345.50)


@pytest.mark.parametrize(
    "texto,tipo",
    [
        ("XAUUSD BUY NOW 2345\nSL 2335\nTP 2355", OrderType.MARKET),
        ("XAUUSD BUY LIMIT 2345\nSL 2335\nTP 2355", OrderType.LIMIT),
        ("XAUUSD SELL STOP 2345\nSL 2355\nTP 2335", OrderType.STOP),
        ("XAUUSD BUY 2345\nSL 2335\nTP 2355", OrderType.MARKET),
    ],
)
def test_tipos_de_orden(texto, tipo):
    event = parse_signal(texto)
    assert event.order_type is tipo
    assert event.side is not None, "el lado nunca debe perderse al detectar el tipo de orden"


def test_buy_stop_no_confunde_stop_con_stop_loss():
    event = parse_signal("XAUUSD BUY STOP 2350\nSL 2340\nTP 2360")
    assert event.order_type is OrderType.STOP
    assert event.entry == 2350.0
    assert event.stop_loss == 2340.0, "el 2350 del 'BUY STOP' no es el stop loss"


def test_palabra_close_dentro_de_una_senal_no_la_convierte_en_cierre():
    event = parse_signal("GOLD SELL 2350, close below 2340 invalidates\nSL 2360\nTP 2330")
    assert event.event_type is EventType.OPEN


# --------------------------------------------------------------------------
# Gestion
# --------------------------------------------------------------------------


def test_cierre_parcial_con_porcentaje():
    event = parse_signal("Close 50% XAUUSD")
    assert event.event_type is EventType.PARTIAL_CLOSE
    assert event.close_fraction == 0.5
    assert event.symbol == "XAUUSD"


def test_cierre_parcial_con_la_palabra_half():
    event = parse_signal("Close half and secure profits")
    assert event.event_type is EventType.PARTIAL_CLOSE
    assert event.close_fraction == 0.5


def test_mover_sl_a_breakeven():
    event = parse_signal("TP1 hit. Move SL to BE")
    assert event.event_type is EventType.MOVE_SL
    assert event.move_sl_to_breakeven is True


def test_mover_sl_a_un_precio_concreto():
    event = parse_signal("Move SL to 2350")
    assert event.event_type is EventType.MOVE_SL
    assert event.stop_loss == 2350.0
    assert event.move_sl_to_breakeven is False


def test_cierre_total():
    for texto in ("Close all positions", "Cerrar todo ahora", "Exit now"):
        assert parse_signal(texto).event_type is EventType.CLOSE


def test_porcentaje_no_se_lee_como_precio():
    event = parse_signal("Close 50% XAUUSD")
    assert event.take_profits == []
    assert event.stop_loss is None


# --------------------------------------------------------------------------
# Descarte
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "Buenos dias grupo, como andan?",
        "Hoy no hay senales, mercado lateral",
        "",
        "   ",
        "Gracias maestro!!",
    ],
)
def test_charla_se_ignora(texto):
    assert parse_signal(texto) is None


def test_buy_sin_ningun_precio_queda_ambiguo():
    event = parse_signal("BUY GOLD")
    assert event.event_type is EventType.UNKNOWN
    assert event.warnings


# --------------------------------------------------------------------------
# Avisos de coherencia
# --------------------------------------------------------------------------


def test_avisa_si_el_sl_esta_del_lado_equivocado():
    event = parse_signal("XAUUSD BUY\nEntry 2345\nSL 2355\nTP 2365")
    assert any("SL" in w for w in event.warnings)


def test_avisa_si_un_tp_esta_del_lado_equivocado():
    event = parse_signal("XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2340")
    assert any("TP" in w for w in event.warnings)


# --------------------------------------------------------------------------
# Metadatos
# --------------------------------------------------------------------------


def test_los_metadatos_de_telegram_se_conservan():
    event = parse_signal(
        "XAUUSD BUY 2345\nSL 2335\nTP 2355",
        message_id=42, chat_id=-100123, is_edit=True, source="caption",
    )
    assert event.telegram_message_id == 42
    assert event.telegram_chat_id == -100123
    assert event.is_edit is True
    assert event.source == "caption"
    assert "XAUUSD BUY" in event.raw_message, "el mensaje original queda para auditar"
