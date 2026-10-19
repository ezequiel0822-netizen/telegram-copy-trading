"""Las senales que el bot rechazo por llegar tarde: que habria pasado (19/10).

XAUUSD TRADING ZONE manda la senal completa 1 a 3 minutos despues de un "SELL
NOW", cuando el precio ya se fue hacia el TP, y el filtro la rechaza. El 19/10
una de esas cumplio todos sus TP y la pregunta fue si convenia entrarles igual. El
repaso mide tres formas, sin tocar el bot: entrar igual a mercado, o dejar una
orden esperando en el borde de la zona del canal (entra solo si el precio
vuelve), que se cancela si antes llega al TP1 o que espera hasta vencer.

La primera version entraba "igual" con el TP1 aunque el precio ya lo hubiera
pasado (77 de 111 en TRADING ZONE): perdidas del tamano del spread que en
MetaTrader no existen. Por eso varios tests ponen el precio justo en el spread.
"""

from __future__ import annotations

import inspect

from tct.repaso import resumir_tardias, simular_tardias
from tct.signals.parser import parse_signal

MIN = 60_000
TARDIA = ("La entrada 4419 esta a 0.1% del precio real de XAUUSD (4413), y el limite es "
          "0.05% (MAX_SPREAD_FROM_ENTRY_PCT). Casi siempre es un simbolo mal leido.")
SENAL = parse_signal("XAU/USD SELL 4416/4422\nTP 4412\nTP 4408\nSL 4430")
COMPRA = parse_signal("XAU/USD BUY 4416/4422\nTP 4426\nTP 4430\nSL 4408")


class Precios:
    """Ticks armados a mano: (minuto, bid) con un spread de 0.2, o (minuto, bid, ask)."""

    def __init__(self, recorrido):
        self._ticks = [(x[0] * MIN, x[1], x[2] if len(x) > 2 else x[1] + 0.2)
                       for x in recorrido]

    def ticks(self, desde, hasta):
        return [x for x in self._ticks if desde <= x[0] <= hasta]


def simular(recorrido, motivos=(TARDIA,), fin_min=600, senal=SENAL):
    filas = [{"fecha_ms": 10 * MIN, "senal": senal, "rechazo": list(motivos)}]
    return simular_tardias(filas, {"XAUUSD": Precios(recorrido)}, {"XAUUSD": 100.0},
                           fin_min * MIN, esperas_min=(15, 60))


# --- 1) entrar igual ---------------------------------------------------------

def test_entrando_igual_al_precio_de_ese_momento():
    # La senal llega con el precio en 4413 (ya debajo de la zona) y baja al TP1.
    [caso] = simular([(9, 4414), (10, 4413), (12, 4411.5)])

    m = caso["mercado"]
    assert m["entrada"] == 4413 and m["motivo"] == "tp" and m["tp_numero"] == 1
    # Un SELL cierra con el ask: 4411.7. Por lote: (4413 - 4411.7) * 100.
    assert round(m["resultado"], 2) == 130.0


def test_entrando_igual_tambien_pierde():
    [caso] = simular([(10, 4413), (20, 4430.5)])

    assert caso["mercado"]["motivo"] == "sl"
    assert caso["mercado"]["resultado"] < 0


def test_si_ya_paso_el_tp1_entra_con_el_siguiente():
    # Un SELL con el TP por encima del precio no existe: entra con el TP2 (4408).
    [caso] = simular([(10, 4411), (14, 4407.5)])

    assert caso["tp1_ya_paso"] is True
    m = caso["mercado"]
    assert m["entro"] and m["tp_numero"] == 2 and m["tp"] == 4408 and m["motivo"] == "tp"
    assert round(m["resultado"], 2) == round((4411 - 4407.7) * 100, 2)


def test_si_ya_paso_todos_los_tp_no_entra():
    [caso] = simular([(10, 4407), (20, 4400)])

    assert caso["mercado"]["entro"] is False
    assert resumir_tardias([caso], 0.03)["mercado"]["operadas"] == 0


def test_compra_que_ya_paso_el_tp1():
    # Un BUY entra al ask (4427.2) y cobra con el bid.
    [caso] = simular([(10, 4427), (12, 4430.1)], senal=COMPRA)

    assert caso["tp1_ya_paso"] is True
    m = caso["mercado"]
    assert m["entrada"] == 4427.2 and m["tp_numero"] == 2 and m["tp"] == 4430
    assert round(m["resultado"], 2) == round((4430.1 - 4427.2) * 100, 2)


def test_compra_con_el_tp1_dentro_del_spread():
    # bid 4425.9 < TP1 4426 <= ask 4426.1: entrar al ask con ese TP pierde el
    # spread al instante. Cuenta como "ya llego al TP1" y entra con el TP2.
    [caso] = simular([(10, 4425.9, 4426.1), (12, 4430.1)], senal=COMPRA)

    assert caso["tp1_ya_paso"] is True
    assert caso["mercado"]["tp_numero"] == 2


def test_venta_con_el_tp1_dentro_del_spread():
    # bid 4411.9 < TP1 4412 <= ask 4412.1: un SELL entra al bid, 4411.9.
    [caso] = simular([(10, 4411.9, 4412.1), (12, 4407.5)])

    assert caso["tp1_ya_paso"] is True
    assert caso["mercado"]["entrada"] == 4411.9 and caso["mercado"]["tp_numero"] == 2


def test_el_tp_justo_en_el_precio_no_cuenta_como_por_delante():
    [compra] = simular([(10, 4425.8, 4426.0), (12, 4430.1)], senal=COMPRA)
    [venta] = simular([(10, 4412.0, 4412.2), (12, 4407.5)])

    assert compra["mercado"]["tp_numero"] == 2 and compra["tp1_ya_paso"] is True
    assert venta["mercado"]["tp_numero"] == 2 and venta["tp1_ya_paso"] is True


def test_el_numero_del_tp_cuenta_los_que_el_bot_usa():
    # El 4425 de un SELL en 4416/4422 esta del lado equivocado: el bot no lo
    # usa, y su TP1 es el 4412 (como numera el bot sus posiciones).
    senal = parse_signal("XAU/USD SELL 4416/4422\nTP 4425\nTP 4412\nTP 4408\nSL 4430")
    [caso] = simular([(10, 4413), (12, 4411.5)], senal=senal)

    assert caso["mercado"]["tp_numero"] == 1 and caso["mercado"]["tp"] == 4412
    assert caso["tp1_ya_paso"] is False


# --- 2) y 3) la orden en el borde de la zona --------------------------------

def test_la_orden_en_el_precio_del_canal_entra_si_vuelve():
    # Vuelve a 4416 (el borde de abajo de la zona) a los 5 minutos y despues
    # baja al TP1: entra a 4416, gana 4 puntos menos el spread.
    [caso] = simular([(10, 4413), (15, 4416.1), (20, 4411.7)])

    p = caso["pendiente"][15]
    assert p["entro"] and p["entrada"] == 4416 and p["motivo"] == "tp"
    assert round(p["resultado"], 2) == round((4416 - 4411.9) * 100, 2)
    assert caso["orden"] == {"precio": 4416, "tp": 4412, "tp_numero": 1}


def test_si_se_va_al_tp_sin_volver_no_entra():
    [caso] = simular([(10, 4413), (12, 4411.5), (30, 4416.5)])

    assert caso["pendiente"][15]["entro"] is False
    assert caso["pendiente"][60]["entro"] is False
    assert caso["pendiente"][60]["motivo"] == "se fue al TP"


def test_si_vuelve_despues_de_vencer_solo_entra_la_que_espera_mas():
    [caso] = simular([(10, 4413), (40, 4416.2), (45, 4411.5)])

    assert caso["pendiente"][15]["entro"] is False
    assert caso["pendiente"][60]["entro"] is True


def test_si_ya_habia_llegado_al_tp1_la_orden_que_se_cancela_ni_se_pone():
    # El primer tick despues de la senal ya esta de vuelta en el borde: si la
    # orden se pusiera, entraria. No se pone porque el TP1 ya se habia tocado.
    [caso] = simular([(10, 4411), (20, 4416.1), (25, 4411.7)])

    assert caso["pendiente"][15] == {"entro": False, "resultado": 0.0,
                                     "motivo": "ya habia llegado al TP1"}
    sin = caso["sin_cancelar"][15]
    assert sin["entro"] and sin["entrada"] == 4416 and sin["motivo"] == "tp"
    assert round(sin["resultado"], 2) == round((4416 - 4411.9) * 100, 2)


def test_la_orden_sin_cancelar_tambien_vence():
    [caso] = simular([(10, 4413), (12, 4411.5), (30, 4416.5)])

    assert caso["sin_cancelar"][15]["entro"] is False
    assert caso["sin_cancelar"][15]["motivo"] == "no volvio"
    # A los 20 minutos vuelve: la de 60 entra y queda abierta (no hay mas ticks).
    assert caso["sin_cancelar"][60]["entro"] is True
    assert caso["sin_cancelar"][60]["resultado"] is None


def test_la_compra_va_en_el_borde_de_arriba_y_entra_con_el_ask():
    # BUY 4416/4422: la orden va en 4422. A los 10 min el bid toca 4421.9 pero el
    # ask esta en 4422.1: no entra. A los 20 min el ask baja a 4422.0: entra
    # (solo la de 60 minutos, la de 15 ya vencio).
    [caso] = simular([(10, 4424), (20, 4421.9, 4422.1), (30, 4421.8, 4422.0), (35, 4426.5)],
                     senal=COMPRA)

    assert caso["orden"]["precio"] == 4422
    assert caso["sin_cancelar"][15]["entro"] is False
    p = caso["sin_cancelar"][60]
    assert p["entro"] and p["entrada"] == 4422 and p["motivo"] == "tp"
    assert round(p["resultado"], 2) == round((4426.5 - 4422) * 100, 2)


def test_la_venta_entra_con_el_bid():
    # SELL en 4416: con bid 4415.9 / ask 4416.1 no entra; con bid 4416.0, si.
    [caso] = simular([(10, 4413), (20, 4415.9), (30, 4416.0), (35, 4411.5)])

    assert caso["sin_cancelar"][15]["entro"] is False
    assert caso["sin_cancelar"][60]["entro"] is True


def test_la_compra_se_cancela_con_el_bid_en_el_tp1():
    # El ask llega al TP1 (4426.1) pero el bid no (4425.9): un BUY cobra con el
    # bid, asi que no llego al TP y la orden sigue. Despues vuelve y entra.
    [caso] = simular([(10, 4423.0), (12, 4425.9, 4426.1), (20, 4421.8, 4422.0), (25, 4426.5)],
                     senal=COMPRA)

    assert caso["pendiente"][15]["entro"] is True


def test_la_venta_se_cancela_con_el_ask_en_el_tp1():
    # bid 4411.9 / ask 4412.1: el ask no llego al TP1 (4412). No se cancela.
    [caso] = simular([(10, 4413), (12, 4411.9), (20, 4416.1), (25, 4411.5)])

    assert caso["pendiente"][15]["entro"] is True


def test_la_orden_usa_el_primer_tp_mas_alla_de_su_precio():
    # El TP1 (4418) esta dentro de la zona: una orden SELL en 4416 con TP 4418
    # la rechaza MetaTrader. Usa el TP2, 4408, y gana.
    senal = parse_signal("XAU/USD SELL 4416/4422\nTP 4418\nTP 4408\nSL 4430")
    [caso] = simular([(10, 4413), (12, 4416.1), (13, 4416.0), (20, 4407.5)], senal=senal)

    assert caso["orden"]["tp"] == 4408 and caso["orden"]["tp_numero"] == 2
    p = caso["sin_cancelar"][15]
    assert p["entro"] and p["motivo"] == "tp" and p["resultado"] > 0


def test_sin_ningun_tp_mas_alla_de_la_orden_no_se_pone():
    senal = parse_signal("XAU/USD SELL 4416/4422\nTP 4418\nSL 4430")
    [caso] = simular([(10, 4413), (12, 4416.1), (20, 4411.5)], senal=senal)

    for clave in ("pendiente", "sin_cancelar"):
        assert caso[clave][15] == {"entro": False, "resultado": 0.0,
                                   "motivo": "ningun TP queda mas alla de la orden"}


# --- cuales entran, y el resumen ------------------------------------------

def test_solo_las_rechazadas_por_tardias():
    otra = "Falta stop loss (REQUIRE_STOP_LOSS=true)"
    a_favor = TARDIA.replace("(MAX_SPREAD_FROM_ENTRY_PCT)", "(MAX_SPREAD_FROM_ENTRY_PCT x10 (a favor))")

    assert simular([(10, 4413)], motivos=(otra,)) == []
    assert simular([(10, 4413)], motivos=(TARDIA, otra)) == []
    assert simular([(10, 4413)], motivos=(a_favor,)) == []


def test_el_resumen_por_lote():
    casos = simular([(10, 4413), (15, 4416.1), (20, 4411.7)])

    r = resumir_tardias(casos, 0.03)

    assert r["senales"] == 1 and r["tp1_ya_paso"] == 0
    assert r["mercado"]["ganadas"] == 1 and round(r["mercado"]["total"], 2) == round(
        (4413 - 4411.9) * 100 * 0.03, 2)
    assert round(r["mercado"]["promedio_ganada"], 2) == 3.30
    assert r["pendiente"][15]["operadas"] == 1
    assert r["sin_cancelar"][60]["operadas"] == 1


# --- lo que se imprime -------------------------------------------------------

def test_el_repaso_lo_muestra_al_final(capsys):
    from tct import cli

    casos = simular([(10, 4413), (15, 4416.1), (20, 4411.7)])

    cli._imprimir_tardias(casos, [0.03], detalle=True, lote_del_detalle=0.03)

    salida = capsys.readouterr().out
    assert "LA 1 QUE LLEGO TARDE" in salida
    assert "En 0 de 1 ya habia llegado al TP1." in salida
    assert "se sumaria al del bot" in salida
    assert "1) Entrando igual: entraron 1 de 1, 1 ganada, 0 perdidas" in salida
    assert "gana 3.30 y pierde 0.00 en promedio" in salida
    assert "2) Orden, se cancela en el TP1:" in salida
    assert "3) Orden sin cancelar:" in salida
    assert "espera 15 min: entraron 1 de 1, 1 ganada" in salida
    # El detalle, al lote del detalle del bot: 110 por lote son 3.30 a 0.03.
    assert "UNA POR UNA (a lote 0.03" in salida
    assert "1) entrando igual a 4413 con TP1 4412: tp +3.30" in salida
    assert "2) orden en 4416: 15 min tp +12.30, 60 min tp +12.30" in salida


def test_el_detalle_cuando_ya_llego_al_tp1(capsys):
    from tct import cli

    casos = simular([(10, 4411), (14, 4407.5), (20, 4416.1), (25, 4411.7)])

    cli._imprimir_tardias(casos, [0.03], detalle=True, lote_del_detalle=0.03)

    salida = capsys.readouterr().out
    assert "En 1 de 1 ya habia llegado al TP1." in salida
    assert "1) entrando igual a 4411 con TP2 4408: tp" in salida
    assert "2) orden en 4416: no se pone, ya habia llegado al TP1" in salida
    assert "3) sin cancelar: 15 min tp" in salida


def test_el_detalle_cuando_no_entra(capsys):
    from tct import cli

    casos = simular([(10, 4407), (20, 4400)])

    cli._imprimir_tardias(casos, [0.03], detalle=True, lote_del_detalle=0.03)

    assert "1) entrando igual: no entra, a 4407 ya paso todos los TP" in capsys.readouterr().out


def test_sin_tardias_no_muestra_nada(capsys):
    from tct import cli

    cli._imprimir_tardias([], [0.03], detalle=True)

    assert capsys.readouterr().out == ""


def test_se_muestran_aunque_ninguna_del_bot_haya_terminado():
    # Si el canal manda todo tarde, el bot no termina ninguna: es justo cuando
    # mas sirve ver las tardias.
    from tct import cli

    fuente = inspect.getsource(cli._repaso_async)
    corte = fuente.index("Ninguna termino todavia")
    assert "_imprimir_tardias(" in fuente[corte:fuente.index("return 0", corte)]
