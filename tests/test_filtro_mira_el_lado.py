"""El filtro de entrada tarde solo aprieta cuando el precio se movio EN CONTRA.

DE DONDE SALE
-------------
De los datos, no de una idea. El 21/09, con la demo de FxPro en 0.05% y
MetaQuotes sin filtro apretado, el canal mando BUY 4358 con el mercado en
4354.8: tres puntos MAS BARATO. FxPro la rechazo por "lejos del precio real" y
MetaQuotes la opero y termino en TP1, +5.70. Fue la unica vez que el filtro
actuo en once dias, y fue para sacar a la cuenta de una ganadora en la que
ademas entraba mejor que el precio anunciado.

LO QUE NO SE PUEDE PERDER
-------------------------
El mismo filtro ataja los precios MAL LEIDOS (otro simbolo, otra escala, un
digito comido), y esos caen para cualquier lado. Si "a favor" no tuviera techo,
un "BTC BUY 65000" leido como oro pasaria: con el oro en 4438, el mercado esta
93% "a favor". Por eso a favor el techo es FACTOR_A_FAVOR veces mas ancho, no
infinito.

Los tests entran por `engine.handle_message`, como los de test_riesgo_mercado:
lo que importa es que el filtro este CABLEADO, no que la funcion sola opine
bien.
"""

from __future__ import annotations

import pytest

from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.risk import FACTOR_A_FAVOR
from tct.store import Store
from tests.test_engine import build_settings, send


class BrokerConPrecio(PaperBroker):
    def __init__(self, precio: float | None) -> None:
        super().__init__()
        self.precio = precio

    async def market_price(self, symbol: str) -> float | None:
        return self.precio


def armar(tmp_path, precio, limite=0.05, **overrides):
    settings = build_settings(tmp_path, max_spread_from_entry_pct=limite,
                              allowed_symbols={"XAUUSD"}, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return Engine(settings, store, BrokerConPrecio(precio))


def compra(entrada, tp=None, sl=None):
    return (f"XAUUSD BUY\nEntry {entrada}\nSL {sl or entrada - 8}\nTP {tp or entrada + 6}")


def venta(entrada):
    return f"XAUUSD SELL\nEntry {entrada}\nSL {entrada + 8}\nTP {entrada - 6}"


def rechazada_por_el_precio(resultado) -> bool:
    return resultado["status"] == "rechazada" and any(
        "precio real" in r for r in resultado["reasons"])


# --------------------------------------------------------------------------
# El caso real del 21/09
# --------------------------------------------------------------------------


def test_la_senal_del_21_09_ahora_se_opera(tmp_path):
    """BUY 4358 con el mercado en 4354.835: tres puntos mas barato."""
    engine = armar(tmp_path, precio=4354.835)

    resultado = send(engine, compra(4358))

    assert not rechazada_por_el_precio(resultado), resultado["reasons"]


def test_la_edicion_de_esa_misma_senal_sigue_rechazada(tmp_path):
    """La segunda edicion llego con el mercado en 4363.385: cinco puntos EN
    CONTRA. Esa es la entrada tarde que el filtro existe para atajar."""
    engine = armar(tmp_path, precio=4363.385)

    assert rechazada_por_el_precio(send(engine, compra(4358)))


# --------------------------------------------------------------------------
# Los dos lados, en las dos direcciones
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mensaje,precio,se_opera", [
    (compra(4350), 4345.0, True),    # comprar mas barato: a favor
    (compra(4350), 4355.0, False),   # comprar mas caro: en contra
    (venta(4350), 4355.0, True),     # vender mas caro: a favor
    (venta(4350), 4345.0, False),    # vender mas barato: en contra
])
def test_a_favor_se_opera_y_en_contra_no(tmp_path, mensaje, precio, se_opera):
    engine = armar(tmp_path, precio=precio)

    assert (not rechazada_por_el_precio(send(engine, mensaje))) is se_opera


def test_en_contra_pero_cerca_se_sigue_operando(tmp_path):
    """El limite en contra no cambio: 0.05% de 4350 son algo mas de 2 puntos."""
    engine = armar(tmp_path, precio=4351.0)

    assert not rechazada_por_el_precio(send(engine, compra(4350)))


# --------------------------------------------------------------------------
# A favor hay techo: el precio mal leido no entra por esta puerta
# --------------------------------------------------------------------------


def test_un_precio_de_otro_instrumento_no_pasa_por_estar_a_favor(tmp_path):
    """"BTC BUY 65000" leido como oro: el mercado esta 93% "a favor"."""
    engine = armar(tmp_path, precio=4438.0)

    assert rechazada_por_el_precio(send(engine, "XAUUSD BUY\nEntry 65000\nSL 64000\nTP 66000")), (
        "un precio de otro instrumento entro por la puerta de 'a favor'")


def test_una_escala_cambiada_tampoco(tmp_path):
    """"DAX SELL 18.500" leido como 18.5, con el indice arriba: a favor."""
    engine = armar(tmp_path, precio=39500.0)

    assert rechazada_por_el_precio(send(engine, "XAUUSD SELL\nEntry 39.5\nSL 39.6\nTP 39.4"))


def test_el_techo_a_favor_es_el_factor_sobre_el_limite(tmp_path):
    """Con 0.05 quedan 0.5%: en oro, unos 21 puntos. Mas que todos los
    objetivos del canal juntos, y mucho menos que otro instrumento."""
    ancho = 0.05 * FACTOR_A_FAVOR / 100

    adentro = armar(tmp_path / "a", precio=4350.0 * (1 - ancho) + 1)
    afuera = armar(tmp_path / "b", precio=4350.0 * (1 - ancho) - 1)

    assert not rechazada_por_el_precio(send(adentro, compra(4350)))
    assert rechazada_por_el_precio(send(afuera, compra(4350)))


def test_el_motivo_dice_que_era_a_favor(tmp_path):
    """Si rechaza una a favor, el mensaje tiene que decir cual de los dos
    limites fue: si no, se busca el numero equivocado en el .env."""
    engine = armar(tmp_path, precio=4000.0)

    motivo = " ".join(send(engine, compra(4350))["reasons"])

    assert "a favor" in motivo


# --------------------------------------------------------------------------
# Lo que no cambia
# --------------------------------------------------------------------------


def test_una_pendiente_se_sigue_midiendo_con_su_propio_limite(tmp_path):
    """Una pendiente se pone lejos del mercado a proposito, para los dos lados."""
    engine = armar(tmp_path, precio=4300.0, max_pending_distance_pct=2.0)

    resultado = send(engine, "XAUUSD BUY LIMIT\nEntry 4350\nSL 4342\nTP 4356")

    assert not rechazada_por_el_precio(resultado), resultado["reasons"]


def test_sin_precio_de_mercado_no_se_opina(tmp_path):
    """Sin dato no se inventa un rechazo (§9): un broker lento no puede dejar
    al bot sin operar."""
    engine = armar(tmp_path, precio=None)

    assert not rechazada_por_el_precio(send(engine, compra(4350)))


def test_adentro_del_rango_no_hay_a_favor_ni_en_contra(tmp_path):
    engine = armar(tmp_path, precio=4350.0)

    resultado = send(engine, "XAUUSD BUY\nEntry 4348-4352\nSL 4340\nTP 4358")

    assert not rechazada_por_el_precio(resultado), resultado["reasons"]
