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


# --------------------------------------------------------------------------
# Academia de Trading Genesis (17/10)
# --------------------------------------------------------------------------
#
# "🟢 BUY XAGUSD / 🚀 56.895 / SL: ... / TP 1..5" y debajo un parrafo de
# analisis. La entrada no tiene etiqueta (es el numero solo en la linea del 🚀),
# y el analisis trae "zona" y "precio": se leia entrada 22, por el "(21/23)"
# del estocastico, y el "M5" del final quedaba como otro TP.

GENESIS_PLATA = (
    "🟢 BUY XAGUSD\n"
    "🚀 56.895\n"
    "SL: 56.722\n"
    "TP 1: 56.970\n"
    "TP 2: 57.050\n"
    "TP 3: 57.130\n"
    "TP 4: 57.210\n"
    "TP 5: 57.300\n"
    "El Estocástico en M5 se encuentra en zona de sobreventa (21/23) con el precio "
    "consolidando por encima de 56.88, lo que sugiere un rebote inminente"
)

GENESIS_EURO = (
    "🔴 SELL EURUSD\n"
    "🚀 1.12094\n"
    "SL: 1.12268\n"
    "TP 1: 1.12070\n"
    "TP 2: 1.12045\n"
    "TP 3: 1.12020\n"
    "TP 4: 1.12003\n"
    "TP 5: 1.11995\n"
    "El estocástico en M5 está en 76.69/%K girando a la baja desde zona sobrecomprada "
    "y el precio lleva 12 velas empujando desde 1.12004 hasta 1.12094"
)


@pytest.mark.parametrize("mensaje, simbolo, lado, entrada, sl, tps", [
    (GENESIS_PLATA, "XAGUSD", Side.BUY, 56.895, 56.722,
     [56.97, 57.05, 57.13, 57.21, 57.3]),
    (GENESIS_EURO, "EURUSD", Side.SELL, 1.12094, 1.12268,
     [1.1207, 1.12045, 1.1202, 1.12003, 1.11995]),
])
def test_genesis_la_entrada_es_el_numero_del_cohete(mensaje, simbolo, lado, entrada, sl, tps):
    e = parse_signal(mensaje)

    assert e.event_type is EventType.OPEN
    assert (e.symbol, e.side) == (simbolo, lado)
    assert (e.entry_low, e.entry_high, e.stop_loss) == (entrada, entrada, sl)
    assert e.take_profits == tps


@pytest.mark.parametrize("mensaje, entrada", [
    # Un numero solo en la linea que sigue al lado: es la entrada.
    ("BUY XAUUSD\n2345\nSL 2335\nTP 2360", 2345),
    # Si no esta justo debajo del lado, no: queda la regla de siempre.
    ("XAUUSD BUY 2345\nSL 2335\nTP 2360", 2345),
    ("GOLD BUY LIMIT 2340\nSL 2330\nTP 2360", 2340),
])
def test_la_entrada_en_su_linea_no_cambia_los_otros_formatos(mensaje, entrada):
    assert parse_signal(mensaje).entry == entrada


@pytest.mark.parametrize("mensaje, tps", [
    # Las listas de precios en varias lineas siguen enteras.
    ("XAUUSD BUY 2345\nSL 2335\nTP:\n2355\n2365", [2355, 2365]),
    ("XAUUSD BUY 2345\nSL 2335\nTP 2355\n- 2365", [2355, 2365]),
    # Lo que viene debajo del ultimo TP y no es un precio, no.
    ("GOLD BUY 2345\nSL 2335\nTP 2360\n@vipsignals2024", [2360]),
    ("GOLD BUY 2345\nSL 2335\nTP 2360\nEl analisis en M5 sugiere un rebote desde la zona",
     [2360]),
    # Un renglon corto debajo de la etiqueta sigue siendo parte del bloque.
    ("XAUUSD BUY 2345\nSL 2335\nTP:\nFirst one at 2355\nSecond one at 2365", [2355, 2365]),
])
def test_el_texto_debajo_de_los_tp_no_agrega_tps(mensaje, tps):
    assert parse_signal(mensaje).take_profits == tps


@pytest.mark.parametrize("mensaje", [
    "Ha sido una buena semana, gané bastante bien\nAhora puedo empezar el finde con "
    "tranquilidad. Voy a llevar a la familia al bosque, hace tiempo que queríamos "
    "salir todos juntos.",
    "El precio puede salir del rango en cualquier momento",
    "Vamos a salir de la zona de 4400 pronto",
])
def test_salir_suelto_no_es_cerrar(mensaje):
    e = parse_signal(mensaje)

    assert e is None or e.event_type is not EventType.CLOSE


@pytest.mark.parametrize("mensaje", [
    "Salir ya del oro",
    "Vamos a salir de la operacion",
    "SALIR DEL TRADE AHORA",
    "Hay que salir de todas las posiciones",
])
def test_salir_de_la_operacion_si_es_cerrar(mensaje):
    assert parse_signal(mensaje).event_type is EventType.CLOSE


@pytest.mark.parametrize("mensaje, sl", [
    # David escribe el pedido y el precio en renglones distintos: el bloque del
    # SL no se corta antes de tener su numero (revision del 17/10).
    ("ESTABLEZCA AMBOS SL\nEN LA MARCA 4170", 4170),
    ("MUEVAN SU SL\nA LA MARCA DE 4170", 4170),
    ("MUEVAN EL SL\nPOR DEBAJO DE 4170", 4170),
])
def test_el_precio_del_sl_en_el_renglon_de_abajo_se_lee(mensaje, sl):
    e = parse_signal(mensaje)

    assert e.event_type is EventType.MOVE_SL
    assert e.stop_loss == sl


@pytest.mark.parametrize("mensaje", [
    # Las palabras de David para cerrar: siguen siendo un cierre.
    "SALIR DEL NEGOCIO AHORA",
    "SALIR EN BE",
    "SALIR DE AMBAS POSICIONES",
    "Hay que salir",
    "RECOMIENDO SALIR CON GANANCIAS AHORA",
])
def test_salir_con_las_palabras_de_david_sigue_cerrando(mensaje):
    assert parse_signal(mensaje).event_type is EventType.CLOSE


@pytest.mark.parametrize("mensaje, entrada", [
    # Con una etiqueta de entrada en la cabecera, el numero suelto no la pisa.
    ("SELL XAUUSD\n17\nEntry 4510\nSL 4520\nTP 4500", 4510),
    ("XAUUSD BUY\n0.05\nEntry: 2345\nSL: 2335\nTP: 2360", 2345),
])
def test_el_numero_suelto_no_pisa_una_entrada_con_etiqueta(mensaje, entrada):
    assert parse_signal(mensaje).entry == entrada


def test_un_lado_agregado_al_final_en_una_edicion_no_cambia_la_entrada():
    e = parse_signal("DEAL | GOLD (XAU/USD) BUY XAUUSD 4050\nParameters:\n🟢TP1: 4055\n"
                     "🟢TP2: 4058\n🟢TP3: 4060\n🔴SL: 4043\n\nBUY ✅\n+210")

    assert e.entry == 4050
