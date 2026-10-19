"""Las senales que el bot rechazo por llegar tarde: que habria pasado (19/10).

XAUUSD TRADING ZONE manda la senal completa 1 a 3 minutos despues de un "SELL
NOW", cuando el precio ya se fue hacia el TP, y el filtro la rechaza. El 19/10
una de esas cumplio todos sus TP y el pregunto si convenia entrarles igual. El
repaso mide dos formas, sin tocar el bot: entrar igual a mercado, o dejar una
orden esperando en el precio del canal (entra solo si el precio vuelve).
"""

from __future__ import annotations

from tct.repaso import resumir_tardias, simular_tardias
from tct.signals.parser import parse_signal

MIN = 60_000
TARDIA = ("La entrada 4419 esta a 0.1% del precio real de XAUUSD (4413), y el limite es "
          "0.05% (MAX_SPREAD_FROM_ENTRY_PCT). Casi siempre es un simbolo mal leido.")
SENAL = parse_signal("XAU/USD SELL 4416/4422\nTP 4412\nTP 4408\nSL 4430")


class Precios:
    """Ticks (ms, bid, ask) armados a mano, con un spread de 0.2."""

    def __init__(self, recorrido):
        self._ticks = [(t * MIN, p, p + 0.2) for t, p in recorrido]

    def ticks(self, desde, hasta):
        return [x for x in self._ticks if desde <= x[0] <= hasta]


def simular(recorrido, motivos=(TARDIA,), fin_min=600):
    filas = [{"fecha_ms": 10 * MIN, "senal": SENAL, "rechazo": list(motivos)}]
    return simular_tardias(filas, {"XAUUSD": Precios(recorrido)}, {"XAUUSD": 100.0},
                           fin_min * MIN, esperas_min=(15, 60))


def test_entrando_igual_al_precio_de_ese_momento():
    # La senal llega con el precio en 4413 (ya debajo de la zona) y baja al TP1.
    [caso] = simular([(9, 4414), (10, 4413), (12, 4411.5)])

    m = caso["mercado"]
    assert m["entrada"] == 4413 and m["motivo"] == "tp"
    # Un SELL cierra con el ask: 4411.7. Por lote: (4413 - 4411.7) * 100.
    assert round(m["resultado"], 2) == 130.0


def test_la_orden_en_el_precio_del_canal_entra_si_vuelve():
    # Vuelve a 4416 (el borde de abajo de la zona) a los 5 minutos y despues
    # baja al TP1: entra a 4416, gana 4 puntos menos el spread.
    [caso] = simular([(10, 4413), (15, 4416.1), (20, 4411.7)])

    p = caso["pendiente"][15]
    assert p["entro"] and p["entrada"] == 4416 and p["motivo"] == "tp"
    assert round(p["resultado"], 2) == round((4416 - 4411.9) * 100, 2)


def test_si_se_va_al_tp_sin_volver_no_entra():
    [caso] = simular([(10, 4413), (12, 4411.5), (30, 4416.5)])

    assert caso["pendiente"][15]["entro"] is False
    assert caso["pendiente"][60]["entro"] is False


def test_si_vuelve_despues_de_vencer_solo_entra_la_que_espera_mas():
    [caso] = simular([(10, 4413), (40, 4416.2), (45, 4411.5)])

    assert caso["pendiente"][15]["entro"] is False
    assert caso["pendiente"][60]["entro"] is True


def test_entrando_igual_tambien_pierde():
    [caso] = simular([(10, 4413), (20, 4430.5)])

    assert caso["mercado"]["motivo"] == "sl"
    assert caso["mercado"]["resultado"] < 0


def test_solo_las_rechazadas_por_tardias():
    otra = "Falta stop loss (REQUIRE_STOP_LOSS=true)"
    a_favor = TARDIA.replace("(MAX_SPREAD_FROM_ENTRY_PCT)", "(MAX_SPREAD_FROM_ENTRY_PCT x10 (a favor))")

    assert simular([(10, 4413)], motivos=(otra,)) == []
    assert simular([(10, 4413)], motivos=(TARDIA, otra)) == []
    assert simular([(10, 4413)], motivos=(a_favor,)) == []


def test_el_resumen_por_lote():
    casos = simular([(10, 4413), (15, 4416.1), (20, 4411.7)])

    r = resumir_tardias(casos, 0.03)

    assert r["senales"] == 1
    assert r["mercado"]["ganadas"] == 1 and round(r["mercado"]["total"], 2) == round(
        (4413 - 4411.9) * 100 * 0.03, 2)
    assert r["pendiente"][15]["operadas"] == 1


def test_el_repaso_lo_muestra_al_final(capsys):
    from tct import cli

    casos = simular([(10, 4413), (15, 4416.1), (20, 4411.7)])

    cli._imprimir_tardias(casos, [0.03], detalle=True)

    salida = capsys.readouterr().out
    assert "LAS 1 QUE LLEGARON TARDE" in salida
    assert "1) Entrando igual:        1 ganadas, 0 perdidas" in salida
    assert "2) Orden en el precio del canal (15 min): entraron 1 de 1" in salida
    assert "UNA POR UNA" in salida and "orden 60 min: tp" in salida


def test_sin_tardias_no_muestra_nada(capsys):
    from tct import cli

    cli._imprimir_tardias([], [0.03], detalle=True)

    assert capsys.readouterr().out == ""
