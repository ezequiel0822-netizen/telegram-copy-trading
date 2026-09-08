"""El informe de que hizo el bot y por que.

Existe por una pregunta concreta del usuario: "hoy hubo nueve senales en el
grupo y solo opero cuatro, que paso?". El dato para contestarla siempre estuvo
—cada rechazo se guarda con su motivo, que fue una decision temprana del
proyecto— pero vivia en un `.jsonl` que nadie podia leer sin abrirlo a mano.
Tener el dato y no poder mirarlo es casi lo mismo que no tenerlo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tct.informe import filtrar_por_horas, resumir

AHORA = datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc)


def evento(kind, hace_horas=1, simbolo="XAUUSD", **extra):
    base = {
        "ts": (AHORA - timedelta(hours=hace_horas)).isoformat(),
        "kind": kind,
        "signal": {"symbol": simbolo, "side": "BUY", "entry": 4432.0},
    }
    base.update(extra)
    return base


def rechazo(motivo, **kw):
    return evento("rechazada", reasons=[motivo], **kw)


# --------------------------------------------------------------------------
# La pregunta original: nueve senales, cuatro operadas
# --------------------------------------------------------------------------


def test_cuenta_las_senales_vistas_y_las_operadas():
    eventos = (
        [evento("aceptada") for _ in range(4)]
        + [rechazo("Ya hay una posicion abierta en XAUUSD") for _ in range(5)]
    )

    r = resumir(eventos)

    assert r["vistas"] == 9
    assert r["por_tipo"]["aceptada"] == 4
    assert r["por_tipo"]["rechazada"] == 5


def test_agrupa_los_motivos_que_dicen_lo_mismo():
    """Cinco rechazos por el mismo motivo tienen que verse como uno con un 5x,
    no como cinco lineas distintas. Lo que uno quiere ver es que fueron todos
    por lo mismo."""
    eventos = [rechazo("Ya hay una posicion abierta en XAUUSD") for _ in range(5)]

    motivos = resumir(eventos)["motivos"]

    assert len(motivos) == 1
    texto, veces = motivos[0]
    assert veces == 5
    assert "Ya habia una posicion abierta" in texto


def test_motivos_distintos_no_se_mezclan():
    eventos = [
        rechazo("Ya hay una posicion abierta en XAUUSD"),
        rechazo("La entrada 4432 esta a 1.2% del precio real de XAUUSD (4380)"),
        rechazo("Cupo diario agotado: 10/10 (MAX_SIGNALS_PER_DAY)"),
    ]

    motivos = dict(resumir(eventos)["motivos"])

    assert len(motivos) == 3


def test_un_rechazo_del_broker_se_cuenta_aparte():
    """No es lo mismo que el riesgo la frene que el broker no pueda abrirla:
    lo primero es el bot cuidandote, lo segundo es un problema."""
    eventos = [evento("apertura_fallida", order={"reason": "margen insuficiente"})]

    r = resumir(eventos)

    assert r["por_tipo"]["apertura_fallida"] == 1
    assert any("margen insuficiente" in m for m, _ in r["motivos"])


def test_cada_senal_queda_en_el_detalle_con_su_hora():
    """Para poder cruzarlo con el grupo de Telegram mensaje por mensaje."""
    eventos = [evento("aceptada", hace_horas=3), rechazo("x", hace_horas=2)]

    detalle = resumir(eventos)["detalle"]

    assert len(detalle) == 2
    assert all(f["symbol"] == "XAUUSD" for f in detalle)
    assert detalle[0]["ts"] < detalle[1]["ts"]


# --------------------------------------------------------------------------
# Que se cuenta y que no
# --------------------------------------------------------------------------


def test_la_gestion_no_se_cuenta_como_senal():
    """Un 'MOVER SL' no es una senal de apertura. Contarlo inflaria el numero
    y no coincidiria con lo que se ve en el grupo."""
    eventos = [evento("aceptada"), evento("mover_sl"), evento("cierre")]

    r = resumir(eventos)

    assert r["vistas"] == 1
    assert r["gestion"]["mover_sl"] == 1
    assert r["gestion"]["cierre"] == 1


def test_las_sugerencias_de_la_ia_se_cuentan_aparte():
    """La IA no opera: son senales que el parser no entendio y quedaron solo
    como aviso. Mezclarlas con las operadas seria mentir."""
    eventos = [evento("aceptada"), evento("ia_sugerencia")]

    r = resumir(eventos)

    assert r["por_tipo"]["aceptada"] == 1
    assert r["por_tipo"]["ia_sugerencia"] == 1


# --------------------------------------------------------------------------
# La ventana de tiempo
# --------------------------------------------------------------------------


def test_solo_entran_los_del_rango():
    eventos = [evento("aceptada", hace_horas=2), evento("aceptada", hace_horas=48)]

    assert len(filtrar_por_horas(eventos, 24, AHORA)) == 1


def test_un_evento_sin_fecha_no_ensucia_el_rango():
    """Contarlo igual mezclaria historia vieja en un informe que dice 'las
    ultimas 24 horas', y ese numero es el que despues se usa para decidir."""
    eventos = [evento("aceptada", hace_horas=2), {"kind": "aceptada"}]

    assert len(filtrar_por_horas(eventos, 24, AHORA)) == 1


def test_con_cero_horas_entra_todo():
    eventos = [evento("aceptada", hace_horas=500)]

    assert len(filtrar_por_horas(eventos, 0, AHORA)) == 1


# --------------------------------------------------------------------------
# El dato para calibrar
# --------------------------------------------------------------------------


def test_la_distancia_sale_del_precio_guardado_al_llegar_la_senal():
    """Es la diferencia con `simular --con-precios`: aca el precio de mercado
    se guardo cuando el mensaje llego, no cuando se corre el informe. No
    existe el problema de las senales viejas."""
    trades = [{
        "ts": AHORA.isoformat(), "symbol": "XAUUSD",
        "entry": 4432.0, "precio_mercado": 4435.0,
    }]

    medidas = resumir([], trades)["distancias"]

    assert len(medidas) == 1
    assert medidas[0]["distancia_pct"] == pytest.approx(abs(4432 - 4435) / 4435 * 100)


def test_un_trade_sin_precio_de_mercado_no_se_mide():
    """Con el broker de papel, o si la cotizacion no estaba, no hay nada que
    medir. Inventar un cero desviaria la calibracion."""
    trades = [{"symbol": "XAUUSD", "entry": 4432.0, "precio_mercado": None}]

    assert resumir([], trades)["distancias"] == []


# --------------------------------------------------------------------------
# Las ediciones no pueden inflar el conteo
#
# Salida real del usuario: el informe decia "9 senales de apertura" cuando en
# el grupo habia muchas menos. Este canal edita lo que manda y las ediciones
# se reprocesan a proposito, asi que un solo mensaje generaba tres eventos.
# Un numero que no coincide con lo que uno ve en el grupo no sirve para
# comparar, que es exactamente para lo que se lo mira.
# --------------------------------------------------------------------------


def con_id(kind, mid, hace_horas=1):
    e = evento(kind, hace_horas)
    e["signal"]["telegram_message_id"] = mid
    return e


def test_tres_ediciones_del_mismo_mensaje_cuentan_como_uno():
    eventos = [con_id("ia_sugerencia", 100) for _ in range(3)]

    r = resumir(eventos)

    assert r["mensajes"] == 1, "tres ediciones del mismo mensaje contaron como tres"
    assert r["vistas"] == 3, "el conteo de eventos tiene que seguir estando"


def test_mensajes_distintos_cuentan_por_separado():
    eventos = [con_id("aceptada", 1), con_id("aceptada", 2), con_id("aceptada", 3)]

    assert resumir(eventos)["mensajes"] == 3


def test_el_caso_real_del_usuario():
    """3 senales operadas + 2 mensajes que la IA interpreto, cada uno con dos
    ediciones. El informe decia 9; son 5 mensajes."""
    eventos = (
        [con_id("aceptada", 1), con_id("aceptada", 2), con_id("aceptada", 3)]
        + [con_id("ia_sugerencia", 10) for _ in range(3)]
        + [con_id("ia_sugerencia", 20) for _ in range(3)]
    )

    r = resumir(eventos)

    assert r["vistas"] == 9
    assert r["mensajes"] == 5


def test_un_evento_sin_message_id_cuenta_igual():
    """Los eventos viejos no lo guardaban. Descartarlos escondería senales."""
    eventos = [evento("aceptada"), evento("aceptada")]

    assert resumir(eventos)["mensajes"] == 2


# --------------------------------------------------------------------------
# El texto del mensaje
# --------------------------------------------------------------------------


def test_el_detalle_guarda_lo_que_decia_el_mensaje():
    """Sin esto, una senal que el parser no entendio se ve como '? entrada=-'
    y no hay forma de saber que decia: justo cuando mas se necesita."""
    e = evento("ia_sugerencia")
    e["signal"]["raw_message"] = "No esperemos por TP1\nMovamos el SL ya"

    fila = resumir([e])["detalle"][0]

    assert fila["texto"] == "No esperemos por TP1 Movamos el SL ya", (
        "el texto tiene que quedar en una sola linea para la tabla"
    )


# --------------------------------------------------------------------------
# Por que no se pudo aplicar la gestion
#
# El informe decia "6 gestion que no se pudo aplicar" y nada mas. Eso suena a
# que algo anda mal, cuando casi siempre es lo contrario: el canal edita sus
# mensajes, la edicion se reprocesa, y para entonces la operacion ya cerro.
# Sin el motivo no hay forma de distinguirlo de un problema de verdad.
# --------------------------------------------------------------------------


def test_se_explica_por_que_fallo_la_gestion():
    eventos = [
        evento("gestion_rechazada", reasons=["No hay posiciones abiertas en XAUUSD"])
        for _ in range(6)
    ]

    motivos = resumir(eventos)["motivos_gestion"]

    assert len(motivos) == 1
    texto, veces = motivos[0]
    assert veces == 6
    assert "Suele ser normal" in texto, "no aclara que no es un problema"
    assert "edicion" in texto, "no dice de donde sale"


def test_los_motivos_de_gestion_se_agrupan():
    """Seis por el mismo motivo son una linea con un 6x, no seis lineas."""
    eventos = [
        evento("gestion_rechazada", reasons=["No hay posiciones abiertas en XAUUSD"]),
        evento("gestion_rechazada", reasons=["No hay posiciones abiertas en EURUSD"]),
        evento("gestion_rechazada", reasons=["MOVE_SL sin precio ni breakeven"]),
    ]

    motivos = dict(resumir(eventos)["motivos_gestion"])

    assert len(motivos) == 2
    assert max(motivos.values()) == 2


def test_una_gestion_sin_motivo_no_se_pierde():
    """Los eventos viejos no guardaban reasons. Saltearlos haria que el conteo
    de arriba y el desglose no cierren, y ahi uno deja de confiar en los dos."""
    eventos = [evento("gestion_rechazada")]

    motivos = dict(resumir(eventos)["motivos_gestion"])

    assert sum(motivos.values()) == 1


def test_el_informe_imprime_los_motivos_de_gestion():
    """El cableado hasta la pantalla."""
    import inspect

    from tct import cli

    assert "motivos_gestion" in inspect.getsource(cli.cmd_informe)
