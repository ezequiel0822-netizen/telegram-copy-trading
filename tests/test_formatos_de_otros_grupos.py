"""Los formatos de dos grupos que el bot no entendia (16/10, `tct mensajes`).

De los 7 grupos que el repaso no podia leer, dos escriben las senales en texto
y con todos los precios, solo que con otra forma:

- Gold Signals 98% Sure: "TP1. 4154" (un punto despues del numero de TP). El
  bot leia la entrada y el SL pero ningun TP.
- Sebastian | Banco Plata: el lado es "LARGO" / "CORTO", solo en la primera
  linea. Sin lado, el bot leia el "Stop: 4158.26" como un UPDATE del stop.

Y lo que esos grupos mandan que NO es una senal: "TARGET 4 COMPLETE 330+ PIPS
DONE" (se leia como una apertura con TP 330), la publicidad con "cerrar
posiciones" adentro (se leia como CERRAR) y "Don,t close your buy" con una
coma por apostrofo (se leia como CERRAR).

Nada de esto toca como se lee el canal de David: el resto de los tests sigue
igual, y se compararon los ~2500 textos de los tests con el parser anterior.
"""

from __future__ import annotations

import pytest

from tct.signals.models import EventType, Side
from tct.signals.parser import parse_signal

GOLD_SIGNALS = (
    "XAUUSD Sell 4158/4161\n"
    "بيع الذهب\n"
    "TP1. 4154\n"
    "TP2. 4151\n"
    "TP3. 4147\n"
    "TP4. 4131\n"
    "SL.   4171\n"
    "استخدام إدارة الأموال\n"
    "Use Money Management."
)

SEBASTIAN_CORTO = (
    "CORTO\n"
    "GOLD | ORO | XAUUSD\n"
    "Zona de entrada: 4149.97\n"
    "Objetivos:\n"
    "→ TP1: 4145.82\n"
    "→ TP2: 4141.67\n"
    "→ TP3: 4137.52\n"
    "Stop: 4158.26\n"
    "#SOFT"
)

SEBASTIAN_LARGO = (
    "LARGO\n"
    "GOLD | ORO | XAUUSD\n"
    "Zona de entrada: 4164.56\n"
    "Objetivos:\n"
    "→ TP1: 4168.72\n"
    "→ TP2: 4172.88\n"
    "→ TP3: 4177.05\n"
    "Stop: 4156.23\n"
    "#SOFT"
)

PUBLICIDAD = (
    "“Tengo una cuenta pequeña. ¿De verdad vale la pena entrar al grupo de trading?”\n"
    "Mi respuesta es simple: sí.\n"
    "Y no porque sea el típico gurú de TikTok que te quiere vender algo.\n"
    "➡️Igual hay un mínimo para arrancar: unos $350–500.\n"
    "Eso alcanza para aprender a abrir y copiar trades, manejar el lotaje y "
    "cerrar posiciones como corresponde mientras sigues el sistema.\n"
    "🔘Todas las reseñas acá: https://t.me/+xxxxxxxx\n"
    "✔️El grupo es gratis. La decisión es tuya.\n"
    "Escríbeme y te añadiré al grupo de trading gratis: @un_usuario"
)


def test_gold_signals_lee_los_tp_con_punto():
    e = parse_signal(GOLD_SIGNALS)

    assert e.event_type is EventType.OPEN
    assert (e.symbol, e.side) == ("XAUUSD", Side.SELL)
    assert (e.entry_low, e.entry_high, e.stop_loss) == (4158, 4161, 4171)
    assert e.take_profits == [4154, 4151, 4147, 4131]


@pytest.mark.parametrize("mensaje, lado, entrada, sl, tps", [
    (SEBASTIAN_CORTO, Side.SELL, 4149.97, 4158.26, [4145.82, 4141.67, 4137.52]),
    (SEBASTIAN_LARGO, Side.BUY, 4164.56, 4156.23, [4168.72, 4172.88, 4177.05]),
])
def test_sebastian_largo_y_corto_son_el_lado(mensaje, lado, entrada, sl, tps):
    e = parse_signal(mensaje)

    assert e.event_type is EventType.OPEN
    assert (e.symbol, e.side) == ("XAUUSD", lado)
    assert (e.entry, e.stop_loss, e.take_profits) == (entrada, sl, tps)


@pytest.mark.parametrize("mensaje", [
    # En una frase, "largo" y "corto" no son un lado.
    "XAUUSD a largo plazo sigue alcista, zona 4100 SL 4090 TP 4120",
    "XAUUSD: el camino corto es hacia 4100, SL 4120 TP 4080",
])
def test_largo_y_corto_en_una_frase_no_son_un_lado(mensaje):
    e = parse_signal(mensaje)

    assert e is None or e.side is None


@pytest.mark.parametrize("mensaje, tp", [
    ("TP1 2355", 2355),        # el 1 es el numero de TP
    ("TP 1.2700", 1.27),       # el 1 es parte del precio
    ("TP1. 4154", 4154),       # el punto suelto no es un decimal
    ("TP 2330", 2330),
])
def test_el_numero_del_tp_y_el_precio(mensaje, tp):
    e = parse_signal(f"XAUUSD BUY 2340\nSL 2330\n{mensaje}" if tp > 100
                     else f"GBPUSD BUY 1.2650\nSL 1.2600\n{mensaje}")

    assert e.take_profits == [tp]


@pytest.mark.parametrize("mensaje", [
    "XAUUSD Sell💥\nTARGET ⁴ COMPLETE 330+ PIPS DONE  💯✌️✌️💪💪 🔥🔥",
    "(#XAUUSD Sell💥\nAll TARGET COMPLETE 300+ PIPS DONE  💯✌️✌️💪💪🔥🔥",
    "XAUUSD Sell💥\nTARGET ¹ COMPLETE 40+ PIPS DONE",
    "Gold Sell Running 260+ Pips",
])
def test_un_resultado_con_pips_no_es_una_apertura(mensaje):
    e = parse_signal(mensaje)

    assert e is None or e.event_type is not EventType.OPEN


def test_la_publicidad_no_cierra_nada():
    assert parse_signal(PUBLICIDAD) is None


@pytest.mark.parametrize("mensaje, tipo", [
    # Una orden corta sigue siendo orden aunque nombre a alguien o traiga link.
    ("Cierren todo ya @un_usuario", EventType.CLOSE),
    ("Cierren todas las posiciones de oro\nhttps://t.me/xxxx", EventType.CLOSE),
    ("Muevan el SL a breakeven\nya aseguramos\nvamos por TP2\n@un_usuario",
     EventType.MOVE_SL),
])
def test_una_orden_corta_con_contacto_sigue_siendo_orden(mensaje, tipo):
    assert parse_signal(mensaje).event_type is tipo


@pytest.mark.parametrize("mensaje", [
    "Don,t close your buy Guys, hold it also while you try the sell",
    "Don`t close your buy guys",
])
def test_don_t_con_coma_es_una_negacion(mensaje):
    e = parse_signal(mensaje)

    assert e is None or e.event_type is not EventType.CLOSE
