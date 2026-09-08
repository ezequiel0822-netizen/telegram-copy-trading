"""Que hizo el bot, leido de lo que quedo registrado.

POR QUE EXISTE
--------------
El bot registra TODO lo que pasa, aceptado o rechazado, y cada rechazo lleva
su motivo. Esa fue una decision temprana del proyecto, y existe justamente
para poder contestar despues la pregunta que uno se hace mirando el grupo:

    "hoy hubo nueve senales y solo opero cuatro, que paso?"

Pero hasta ahora esa informacion estaba en un archivo `.jsonl` que nadie podia
leer sin abrirlo a mano. Tener el dato y no poder mirarlo es casi lo mismo que
no tenerlo.

QUE NO HACE
-----------
No calcula ganancias ni perdidas. Para eso hace falta el precio de salida de
cada operacion, que hoy no se guarda: es el punto pendiente de la seccion 8
del CONTEXTO MAESTRO. Este modulo contesta "que hizo el bot y por que", no
"cuanto gano".
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

# Eventos que representan una senal de APERTURA que el bot vio y decidio algo.
# El resto son gestion (mover el stop, cerrar) o ruido informativo.
APERTURAS = {
    "aceptada": "operadas",
    "rechazada": "rechazadas por el riesgo",
    "apertura_fallida": "el broker no las pudo abrir",
    "ambiguo": "no se entendieron",
    "ia_sugerencia": "solo las entendio la IA (no se operan)",
    "pausado": "llegaron con el bot en pausa",
    "dry_run": "modo observacion (DRY_RUN)",
}


def _cuando(evento: dict[str, Any]) -> datetime | None:
    crudo = evento.get("ts")
    if not crudo:
        return None
    try:
        momento = datetime.fromisoformat(str(crudo))
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def filtrar_por_horas(
    eventos: list[dict[str, Any]], horas: int, ahora: datetime | None = None
) -> list[dict[str, Any]]:
    """Los eventos de las ultimas N horas. Sin fecha, se descartan.

    Descartar los que no tienen fecha es deliberado: contarlos igual mezclaria
    historia vieja en un informe que dice "las ultimas 24 horas", y el numero
    que sale de ahi es el que despues se usa para decidir.
    """
    if horas <= 0:
        return list(eventos)
    ahora = ahora or datetime.now(timezone.utc)
    desde = ahora - timedelta(hours=horas)
    return [e for e in eventos if (_cuando(e) or datetime.min.replace(tzinfo=timezone.utc)) >= desde]


def resumir(
    eventos: list[dict[str, Any]], paper_trades: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Cuenta que paso con las senales de apertura y por que."""
    por_tipo: Counter[str] = Counter()
    motivos: Counter[str] = Counter()
    detalle: list[dict[str, Any]] = []

    for evento in eventos:
        kind = evento.get("kind", "")
        if kind not in APERTURAS:
            continue
        por_tipo[kind] += 1

        senal = evento.get("signal") or {}
        fila = {
            "ts": evento.get("ts"),
            "kind": kind,
            "symbol": senal.get("symbol"),
            "side": senal.get("side"),
            "entry": senal.get("entry"),
            "precio_mercado": evento.get("precio_mercado"),
            # El TEXTO del mensaje. Sin esto, una senal que el parser no
            # entendio se muestra como "? entrada=-" y no hay forma de saber
            # que decia: justo el caso en el que uno mas necesita verlo.
            "texto": " ".join(str(senal.get("raw_message") or "").split()),
            # Para poder distinguir mensajes DISTINTOS de ediciones del mismo.
            "message_id": senal.get("telegram_message_id"),
            "motivos": [],
        }

        if kind == "rechazada":
            for motivo in evento.get("reasons", []):
                motivos[_familia_de_motivo(motivo)] += 1
            fila["motivos"] = list(evento.get("reasons", []))
        elif kind == "apertura_fallida":
            razon = (evento.get("order") or {}).get("reason", "")
            if razon:
                motivos[f"el broker rechazo: {razon}"] += 1
                fila["motivos"] = [razon]

        detalle.append(fila)

    gestion = Counter(
        e.get("kind", "") for e in eventos
        if e.get("kind") in {"mover_sl", "cierre", "cierre_parcial",
                             "cerrada_en_el_broker", "gestion_rechazada"}
    )

    # Por que no se pudo aplicar la gestion. Se contaba pero no se explicaba,
    # y "6 gestion que no se pudo aplicar" a secas suena a que algo anda mal
    # cuando casi siempre es lo contrario: el canal edita sus mensajes, la
    # edicion se reprocesa, y para entonces la posicion ya cerro. Sin el
    # motivo no hay forma de distinguir eso de un problema de verdad.
    motivos_gestion: Counter[str] = Counter()
    for e in eventos:
        if e.get("kind") != "gestion_rechazada":
            continue
        for motivo in e.get("reasons", []) or ["sin motivo registrado"]:
            motivos_gestion[_familia_de_motivo_gestion(motivo)] += 1

    # Cuantos MENSAJES distintos hubo, no cuantos eventos. Este canal edita lo
    # que manda y las ediciones se reprocesan a proposito, asi que un solo
    # mensaje puede aparecer tres veces. Contar eventos infla el numero hasta
    # no coincidir con lo que uno ve en el grupo, que es contra lo que se
    # compara.
    ids = [f["message_id"] for f in detalle if f["message_id"] is not None]
    mensajes = len(set(ids)) + sum(1 for f in detalle if f["message_id"] is None)

    return {
        "vistas": sum(por_tipo.values()),
        "mensajes": mensajes,
        "por_tipo": dict(por_tipo),
        "motivos": motivos.most_common(),
        "detalle": detalle,
        "gestion": dict(gestion),
        "motivos_gestion": motivos_gestion.most_common(),
        "distancias": _distancias(paper_trades or []),
    }


def _familia_de_motivo_gestion(motivo: str) -> str:
    """Agrupa los motivos por los que no se pudo aplicar un mensaje de gestion.

    El mas comun no es un problema: el canal edita sus mensajes y la
    edicion se reprocesa; para entonces la posicion ya cerro y no hay nada
    que mover. Decirlo con esas palabras evita que alguien salga a buscar
    una falla que no existe.
    """
    if "No hay posiciones abiertas" in motivo:
        return (
            "No habia ninguna posicion abierta. Suele ser normal: es una "
            "edicion del mensaje que llego cuando la operacion ya habia cerrado."
        )
    if "Fraccion de cierre invalida" in motivo:
        return "No se entendio que fraccion cerrar"
    if "MOVE_SL sin precio" in motivo:
        return "Un 'mover el stop' sin decir a que precio ni a breakeven"
    if "precio de entrada para calcular el breakeven" in motivo:
        return "Se pidio breakeven sin tener registrada la entrada"
    return motivo


def _familia_de_motivo(motivo: str) -> str:
    """Agrupa motivos que dicen lo mismo con numeros distintos.

    Sin esto, cinco rechazos por el mismo motivo aparecen como cinco lineas
    distintas —cada una con su simbolo y su precio— y se pierde justamente lo
    que uno quiere ver: que fueron todos por lo mismo.
    """
    if "Ya hay una posicion abierta" in motivo:
        return "Ya habia una posicion abierta en ese simbolo"
    if "precio real" in motivo:
        return "La entrada estaba lejos del precio real del mercado"
    if "Cupo diario agotado" in motivo:
        return "Se agoto el cupo diario (MAX_SIGNALS_PER_DAY)"
    if "operaciones abiertas" in motivo:
        return "Se llego al tope de operaciones abiertas (MAX_OPEN_TRADES)"
    if "fuera de ALLOWED_SYMBOLS" in motivo:
        return "El simbolo no esta en ALLOWED_SYMBOLS"
    if "perdida diaria" in motivo:
        return "Freno por perdida diaria"
    if "Falta stop loss" in motivo or "Falta take profit" in motivo:
        return "La senal venia sin stop loss o sin take profit"
    return motivo


def _distancias(paper_trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entrada contra precio real, del momento EXACTO en que llego la senal.

    Es el dato con el que se calibra MAX_SPREAD_FROM_ENTRY_PCT sin el problema
    de las senales viejas: aca el precio se guardo cuando el mensaje llego, no
    cuando uno corre el informe.
    """
    medidas = []
    for trade in paper_trades:
        entrada = trade.get("entry")
        mercado = trade.get("precio_mercado")
        if not entrada or not mercado or mercado <= 0:
            continue
        medidas.append({
            "ts": trade.get("ts"),
            "symbol": trade.get("symbol"),
            "entry": entrada,
            "mercado": mercado,
            "distancia_pct": abs(entrada - mercado) / mercado * 100,
        })
    return medidas


# --------------------------------------------------------------------------
# Como termino cada operacion
#
# Se calcula APARTE del camino que opera, leyendo el historial de MT5 cuando
# alguien pide el informe. El bot corriendo no consulta nada de esto: el dato
# sirve para evaluar el canal, no para decidir una orden, y no vale la pena
# meterle latencia al unico camino donde la latencia importa.
# --------------------------------------------------------------------------


def tickets_operados(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Las senales que llegaron a abrir una posicion, con su ticket.

    El ticket vive en el evento "aceptada", que es el unico lugar durable
    donde queda: el paper trade se escribe ANTES de llamar al broker, asi que
    todavia no lo conoce, y el estado lo borra cuando la posicion cierra.
    """
    operadas = []
    for evento in eventos:
        if evento.get("kind") != "aceptada":
            continue
        ticket = (evento.get("order") or {}).get("ticket")
        if not ticket:
            continue
        senal = evento.get("signal") or {}
        operadas.append({
            "ts": evento.get("ts"),
            "ticket": ticket,
            "symbol": senal.get("symbol"),
            "side": senal.get("side"),
            "entry": senal.get("entry"),
            "stop_loss": senal.get("stop_loss"),
            "take_profits": list(senal.get("take_profits") or []),
        })
    return operadas


def clasificar_desenlace(operada: dict[str, Any], desenlace: dict[str, Any]) -> str:
    """Que le paso a la operacion, en palabras.

    La distincion que importa en este canal es "stop de verdad" contra "stop
    en breakeven": el canal mueve el stop a la entrada a los pocos minutos de
    cada senal, asi que la mayoria de las operaciones terminan por SL a precio
    de entrada. Contarlas como perdidas seria describir mal al canal entero.
    """
    motivo = desenlace.get("motivo")
    precio = desenlace.get("precio")
    entrada = operada.get("entry")

    if motivo == "tp":
        return _que_tp(operada, precio)

    if motivo == "sl":
        if entrada and precio and _cerca(precio, entrada, entrada):
            return "breakeven"
        return "stop"

    if motivo in {"manual", "programa"}:
        return "cerrada a mano" if motivo == "manual" else "la cerro el bot"
    return "otro"


def _que_tp(operada: dict[str, Any], precio: float | None) -> str:
    """Cual de los tres objetivos toco. Hoy el bot manda solo el primero a MT5,
    asi que casi siempre va a ser TP1; se calcula igual para que el dia que se
    manden los tres el informe ya lo sepa leer."""
    objetivos = operada.get("take_profits") or []
    if not precio or not objetivos:
        return "TP"

    # El MAS CERCANO, no el primero que entre en la tolerancia. Los TP de este
    # canal estan a 2 puntos entre si, y la tolerancia del relleno del broker
    # es de ese mismo orden: quedarse con el primero que califica devuelve TP2
    # para un cierre exacto en TP3.
    i, tp = min(enumerate(objetivos, start=1), key=lambda par: abs(precio - par[1]))
    return f"TP{i}" if _cerca(precio, tp, precio) else "TP"


def _cerca(a: float, b: float, escala: float, tolerancia_pct: float = 0.05) -> bool:
    """Si dos precios son el mismo, con el margen del relleno del broker.

    Un cierre nunca cae exacto en el numero pedido: hay spread y deslizamiento.
    0.05% del precio son ~2 puntos en oro, que es lo que corresponde.
    """
    if not escala:
        return False
    return abs(a - b) / abs(escala) * 100 <= tolerancia_pct


def resumir_desenlaces(desenlaces: list[dict[str, Any]]) -> dict[str, Any]:
    """El resumen que contesta si el canal sirve."""
    conocidos = [d for d in desenlaces if d.get("resultado")]
    conteo = Counter(d["resultado"] for d in conocidos)
    total = sum(float(d.get("profit") or 0.0) for d in conocidos)
    return {
        "conocidos": len(conocidos),
        "sin_datos": len(desenlaces) - len(conocidos),
        "por_resultado": conteo.most_common(),
        "profit_total": total,
    }
