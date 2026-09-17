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

LA REGLA DE ORO: SE CUENTAN MENSAJES, NO EVENTOS
------------------------------------------------
Este canal EDITA lo que manda y cada edicion se vuelve a procesar, asi que un
mensaje deja dos, tres o cuatro eventos. Todo lo que el informe cuenta -el
desglose, los motivos, la lista una por una, las distancias- se cuenta por
MENSAJE, porque es lo que uno ve en el grupo y contra lo que compara. Contar
eventos ya mando una vez a buscar un bug que no existia ("hubo nueve senales y
leyo cuatro"), y una revision posterior encontro que el titulo contaba mensajes
pero el desglose de abajo seguia sumando eventos: con datos reales decia "20
mensajes" arriba y sumaba 30 abajo.

Las ganancias salen del historial de MetaTrader (`--con-resultados`), nunca de
aca: este modulo solo lee lo que el bot registro.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone, tzinfo
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


def hora_local(crudo: Any, zona: tzinfo | None = None) -> str:
    """"16/09 11:39" en el reloj de ESTA PC, que es el que muestra Telegram.

    Los eventos se guardan en UTC. Antes el informe cortaba el texto crudo y
    mostraba la hora UTC sin decirlo, y sin fecha: en un informe de 300 horas
    un "11:39" podia ser de cualquiera de doce dias, y en una maquina en UTC-6
    no coincidia con la hora del mensaje en el grupo, que es justo contra lo que
    uno cruza la lista.
    """
    if not crudo:
        return "--/-- --:--"
    try:
        momento = datetime.fromisoformat(str(crudo))
    except ValueError:
        return str(crudo)[:16]
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(zona).strftime("%d/%m %H:%M")


def precio(valor: Any) -> str:
    """Un precio legible: `4404.845`, no `4404.844999999999`.

    Hasta cinco decimales, que es lo que usa el forex, sin ceros de relleno.
    Sin dato devuelve "-": un None en un f-string con formato hacia reventar el
    informe entero con un traceback.
    """
    if valor is None:
        return "-"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{numero:.5f}".rstrip("0").rstrip(".")
    return texto if texto not in {"", "-0"} else "0"


def _clave_de_mensaje(evento: dict[str, Any], orden: int) -> tuple:
    """A que MENSAJE de Telegram pertenece un evento.

    Sin id (eventos de antes de que se guardara) cada evento es su propio
    mensaje: descartarlos esconderia senales, y agruparlos a ciegas juntaria
    senales distintas.
    """
    senal = evento.get("signal") or {}
    mid = senal.get("telegram_message_id")
    if mid is None:
        return ("sin-id", orden)
    return ("mensaje", senal.get("telegram_chat_id"), mid)


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
    """Cuenta que paso con las senales de apertura y por que. POR MENSAJE."""
    por_tipo: Counter[str] = Counter()
    motivos: Counter[str] = Counter()
    detalle: list[dict[str, Any]] = []

    # Primero se juntan las ediciones de cada mensaje, en el orden en que
    # llego el primero de cada uno.
    grupos: dict[tuple, list[dict[str, Any]]] = {}
    vistas = 0
    for orden, evento in enumerate(eventos):
        if evento.get("kind", "") not in APERTURAS:
            continue
        vistas += 1
        grupos.setdefault(_clave_de_mensaje(evento, orden), []).append(evento)

    for ediciones in grupos.values():
        # Que paso con ESTE mensaje. Si alguna edicion se opero, se opero: es
        # lo que importa, aunque otra edicion haya sido rechazada antes (por
        # ejemplo, porque el tope estaba lleno y despues se libero). Si ninguna
        # se opero, vale la ULTIMA edicion, que es la version vigente del
        # mensaje y el ultimo intento del bot.
        evento = next((e for e in ediciones if e.get("kind") == "aceptada"), ediciones[-1])
        kind = evento.get("kind", "")
        por_tipo[kind] += 1

        senal = evento.get("signal") or {}
        fila = {
            # La hora en que llego el mensaje, no la de su ultima edicion: es
            # la que se ve en el grupo.
            "ts": ediciones[0].get("ts"),
            "ediciones": len(ediciones),
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

        # Los motivos de TODAS las ediciones con ese mismo resultado, no solo de
        # la ultima: si la primera se rechazo por el tope y la ultima por el
        # freno diario, las dos cosas pasaron y las dos explican por que no se
        # opero. Cada motivo cuenta UNA vez por mensaje.
        crudos: list[str] = []
        if kind == "rechazada":
            for e in ediciones:
                if e.get("kind") == "rechazada":
                    crudos.extend(e.get("reasons", []) or [])
            fila["motivos"] = list(dict.fromkeys(crudos))
            for familia in dict.fromkeys(_familia_de_motivo(m) for m in fila["motivos"]):
                motivos[familia] += 1
        elif kind == "apertura_fallida":
            for e in ediciones:
                if e.get("kind") == "apertura_fallida":
                    razon = (e.get("order") or {}).get("reason", "")
                    if razon:
                        crudos.append(razon)
            fila["motivos"] = list(dict.fromkeys(crudos))
            for razon in fila["motivos"]:
                motivos[f"el broker rechazo: {razon}"] += 1

        detalle.append(fila)

    # Que mensajes llegaron a abrir de verdad: las distancias son de "senales
    # operadas", y el paper trade se escribe ANTES de llamar al broker.
    operadas = {
        _clave_de_mensaje(e, orden)
        for orden, e in enumerate(eventos)
        if e.get("kind") == "aceptada"
        and (e.get("signal") or {}).get("telegram_message_id") is not None
    }

    gestion = Counter(
        e.get("kind", "") for e in eventos
        if e.get("kind") in {"mover_sl", "mover_tp", "cierre", "cierre_parcial",
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

    # Que paso con cada "mover TP": cuantas posiciones del TP1 se movieron, y
    # por que no se movieron las demas. Se pidio que quede a la vista para
    # poder revisar los datos despues.
    tp_movidos = 0
    tp_no_movidos: Counter[str] = Counter()
    for e in eventos:
        if e.get("kind") != "mover_tp":
            continue
        tp_movidos += len(e.get("movidas") or [])
        for no in e.get("no_movidas") or []:
            tp_no_movidos[_familia_de_no_movido(no.get("motivo", ""))] += 1

    return {
        # `vistas` son los eventos procesados, ediciones incluidas; `mensajes`
        # son los mensajes distintos. Todo lo demas se cuenta por mensaje, asi
        # que el desglose suma exactamente `mensajes`.
        "vistas": vistas,
        "mensajes": len(grupos),
        "por_tipo": dict(por_tipo),
        "motivos": motivos.most_common(),
        "detalle": detalle,
        "gestion": dict(gestion),
        "motivos_gestion": motivos_gestion.most_common(),
        "tp_movidos": tp_movidos,
        "tp_no_movidos": tp_no_movidos.most_common(),
        "distancias": _distancias(paper_trades or [], operadas),
    }


def _familia_de_no_movido(motivo: str) -> str:
    """Agrupa por que una posicion no se movio con un "mover TP".

    Los motivos traen precios, y sin agruparlos cada uno sale en su propia
    linea. Los de "persigue el TP2" y "persigue el TP3" se dejan tal cual: son
    pocos y son justamente la distincion que interesa ver.
    """
    if "lado equivocado" in motivo:
        return "el TP nuevo quedaba del lado equivocado del precio"
    if "no da la escala" in motivo:
        return "el TP nuevo no correspondia a ese instrumento"
    if "no se sabe que TP perseguia" in motivo:
        return "posicion abierta antes de registrar que TP perseguia"
    return motivo


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
    if "MOVE_TP sin precio" in motivo:
        return "Un 'mover el TP' sin decir a que precio"
    if "precio de entrada para calcular el breakeven" in motivo:
        return "Se pidio breakeven sin tener registrada la entrada"
    return motivo


def _familia_de_motivo(motivo: str) -> str:
    """Agrupa motivos que dicen lo mismo con numeros distintos.

    Sin esto, cinco rechazos por el mismo motivo aparecen como cinco lineas
    distintas —cada una con su simbolo y su precio— y se pierde justamente lo
    que uno quiere ver: que fueron todos por lo mismo.
    """
    # Por la variable y no por la frase: risk.py dice "una posicion abierta"
    # con una y "2 posiciones abiertas" con dos, y con MAX_POSITIONS_PER_SYMBOL=2
    # -la cuenta real- el rechazo recien salta con dos, asi que la frase en
    # singular no aparecia nunca y el motivo salia crudo.
    if "MAX_POSITIONS_PER_SYMBOL" in motivo or "Ya hay una posicion abierta" in motivo:
        return ("Ya habia posiciones abiertas en ese simbolo "
                "(MAX_POSITIONS_PER_SYMBOL)")
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


def _distancias(
    paper_trades: list[dict[str, Any]], operadas: set[tuple] | None = None
) -> list[dict[str, Any]]:
    """Entrada contra precio real, del momento EXACTO en que llego la senal.

    Es el dato con el que se calibra MAX_SPREAD_FROM_ENTRY_PCT sin el problema
    de las senales viejas: aca el precio se guardo cuando el mensaje llego, no
    cuando uno corre el informe.

    UNA POR SENAL, no una por posicion. Con POSITIONS_PER_SIGNAL=3 cada senal
    deja tres paper trades con la misma entrada y el mismo precio de mercado
    -una sola lectura-, y el informe los listaba tres veces bajo el titulo
    "senales operadas". Con datos reales decia 23 donde habia 15.

    SOLO LAS QUE ABRIERON, y con el precio del intento que abrio. El paper
    trade se escribe ANTES de llamar al broker, asi que una senal que el broker
    no pudo abrir -un BTCUSD en un broker sin cripto- tambien deja uno, y
    figuraba como "operada". Y si el primer intento fallo y una edicion
    posterior si abrio, se medía con el precio del intento fallido. `operadas`
    son las claves de los mensajes con evento "aceptada"; los paper trades sin
    id de mensaje no se pueden cruzar y se muestran igual.
    """
    por_clave: dict[tuple, dict[str, Any]] = {}
    for trade in paper_trades:
        entrada = trade.get("entry")
        mercado = trade.get("precio_mercado")
        if not entrada or not mercado or mercado <= 0:
            continue
        senal = trade.get("signal") or {}
        if senal.get("telegram_message_id") is not None:
            clave = ("mensaje", senal.get("telegram_chat_id"), senal.get("telegram_message_id"))
            if operadas is not None and clave not in operadas:
                continue
        else:
            # Sin id, las posiciones de una misma senal comparten entrada Y la
            # misma lectura del mercado. Dos senales distintas con los dos
            # numeros iguales hasta el ultimo decimal no pasan en la practica.
            clave = ("precios", trade.get("symbol"), entrada, mercado)
        # Gana el ULTIMO: el intento que abrio es el ultimo que escribio paper
        # trades, porque despues de abrir las ediciones ya no se reprocesan.
        por_clave[clave] = {
            "ts": trade.get("ts"),
            "symbol": trade.get("symbol"),
            "entry": entrada,
            "mercado": mercado,
            "distancia_pct": abs(entrada - mercado) / mercado * 100,
        }
    return list(por_clave.values())


# --------------------------------------------------------------------------
# Como termino cada operacion
#
# Se calcula APARTE del camino que opera, leyendo el historial de MT5 cuando
# alguien pide el informe. El bot corriendo no consulta nada de esto: el dato
# sirve para evaluar el canal, no para decidir una orden, y no vale la pena
# meterle latencia al unico camino donde la latencia importa.
# --------------------------------------------------------------------------


def tickets_operados(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Las posiciones que se llegaron a abrir: una fila por TICKET.

    El ticket vive en el evento "aceptada", que es el unico lugar durable
    donde queda: el paper trade se escribe ANTES de llamar al broker, asi que
    todavia no lo conoce, y el estado lo borra cuando la posicion cierra.

    UNA FILA POR POSICION, NO POR SENAL. Con POSITIONS_PER_SIGNAL=3 una sola
    senal abre tres posiciones, y antes esto leia solo `order` -la primera-:
    la del TP2 y la del TP3 desaparecian del informe en silencio, que es
    justamente el dato para el que se abrieron.

    Cada fila dice que TP perseguia (`tp_indice`) y, si un "mover TP" la
    toco, a donde se movio (`tp_movido_a`). El motivo por el que las demas no
    se movieron queda en el evento "mover_tp".
    """
    tp_movido: dict[Any, float] = {}
    for evento in eventos:
        if evento.get("kind") != "mover_tp":
            continue
        for movida in evento.get("movidas") or []:
            if movida.get("ticket"):
                tp_movido[movida["ticket"]] = movida.get("tp_nuevo")

    operadas = []
    for evento in eventos:
        if evento.get("kind") != "aceptada":
            continue
        senal = evento.get("signal") or {}
        objetivos = list(senal.get("take_profits") or [])
        for ticket, indice in _posiciones_del_evento(evento, objetivos):
            operadas.append({
                "ts": evento.get("ts"),
                "ticket": ticket,
                "symbol": senal.get("symbol"),
                "side": senal.get("side"),
                "entry": senal.get("entry"),
                "stop_loss": senal.get("stop_loss"),
                "take_profits": objetivos,
                "tp_indice": indice,
                "tp_movido_a": tp_movido.get(ticket),
            })
    return operadas


def _posiciones_del_evento(
    evento: dict[str, Any], objetivos: list[float]
) -> list[tuple[Any, int | None]]:
    """(ticket, que TP persigue) de cada posicion que abrio una senal.

    Tres formas de evento, de la mas nueva a la mas vieja:

    - `aperturas`: dice el ticket Y el TP de cada una. Es la unica exacta
      cuando fallo una posicion del medio y las otras entraron.
    - `orders`: todos los tickets, en el orden en que se abrieron. Se asume
      que el primero persigue el TP1, y asi; es cierto salvo que haya fallado
      una del medio. Son las senales de los primeros dias con tres TP, y no
      se pueden perder.
    - `order`: el formato de antes de las tres posiciones, uno solo.
    """
    if evento.get("aperturas"):
        return [
            (a.get("ticket"), a.get("tp_indice"))
            for a in evento["aperturas"] if a.get("ticket")
        ]
    if evento.get("orders"):
        # `orders` solo tiene las que ENTRARON. Si fallo la del medio, asignar
        # por orden le pone TP2 a la del TP3, y desde que el informe confia en
        # el indice en vez de adivinar por precio, eso se afirmaba como cierto.
        # Las que fallaron quedaron en `fallidas` como "TP2: motivo": se sacan
        # de la cuenta. Si alguna no se puede leer, no se asigna ningun indice
        # y la etiqueta vuelve a decidirse por el precio de cierre.
        import re

        fallados: set[int] = set()
        legibles = True
        for fallida in evento.get("fallidas") or []:
            coincide = re.match(r"^TP(\d+):", str(fallida))
            if coincide:
                fallados.add(int(coincide.group(1)))
            else:
                legibles = False
        restantes = [i for i in range(1, len(objetivos) + 1) if i not in fallados]

        salida = []
        for n, orden in enumerate(evento["orders"]):
            ticket = (orden or {}).get("ticket")
            if not ticket:
                continue
            indice = restantes[n] if legibles and n < len(restantes) else None
            salida.append((ticket, indice))
        return salida
    ticket = (evento.get("order") or {}).get("ticket")
    if not ticket:
        return []
    return [(ticket, 1 if objetivos else None)]


def clasificar_desenlace(operada: dict[str, Any], desenlace: dict[str, Any]) -> str:
    """Que le paso a la operacion, en palabras.

    La distincion que importa en este canal es "stop de verdad" contra "stop
    en breakeven": el canal mueve el stop a la entrada a los pocos minutos de
    cada senal, asi que la mayoria de las operaciones terminan por SL a precio
    de entrada. Contarlas como perdidas seria describir mal al canal entero.
    """
    motivo = desenlace.get("motivo")
    precio = desenlace.get("precio")
    # La entrada REAL si MT5 la dio. El bot pone el breakeven en el precio de
    # llenado, no en el del mensaje: medido contra el del mensaje, un llenado
    # a 3 puntos contaba un breakeven como stop, y una senal sin numero de
    # entrada contaba como stop siempre. La del mensaje queda de respaldo.
    entrada = desenlace.get("precio_entrada") or operada.get("entry")

    if motivo == "tp":
        # Si un "mover TP" la toco y cerro en el TP nuevo, se dice asi. Si no,
        # `_que_tp` la compararia contra los TPs originales de la senal y la
        # etiquetaria mal -o como un TP generico- justo en el dato que se pidio
        # poder revisar.
        movido = operada.get("tp_movido_a")
        if movido and precio and _cerca(precio, movido, precio):
            return f"TP{operada.get('tp_indice') or 1} movido"
        # Si se sabe que TP perseguia, no hay nada que adivinar: MT5 dice que
        # cerro por take profit, y a esa posicion se le mando UN solo TP, el
        # suyo. Adivinarlo por el precio de cierre fallaba con el deslizamiento:
        # los TP de este canal estan a 2 puntos, y un llenado 1.2 puntos mejor
        # hacia figurar como TP2 una posicion que solo perseguia el TP1 -justo
        # en el conteo con el que se decide si los TP lejanos rinden-.
        if operada.get("tp_indice"):
            return f"TP{operada['tp_indice']}"
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
    """El resumen que contesta si el canal sirve.

    Separa el resultado BRUTO (lo que movio el precio) de los COSTOS (comision,
    swap y fee) y da el NETO, que es lo que se movio la cuenta. Antes se llamaba
    "neto" a la suma de `profit` a secas, que nunca iba a cerrar contra el
    balance del broker. `profit_total` se mantiene y ahora es el neto.

    Una fila sin `neto` (desenlaces leidos antes de que existiera el campo, o
    de un broker que no lo da) cuenta su `profit` y cero de costos: es lo unico
    que se sabe de ella, y se dice en `costos_desconocidos`.
    """
    conocidos = [d for d in desenlaces if d.get("resultado")]
    conteo = Counter(d["resultado"] for d in conocidos)

    def _num(fila: dict[str, Any], campo: str) -> float:
        return float(fila.get(campo) or 0.0)

    bruto = sum(_num(d, "profit") for d in conocidos)
    costos = sum(_num(d, "comision") + _num(d, "swap") + _num(d, "fee") for d in conocidos)
    sin_costos = sum(1 for d in conocidos if "neto" not in d)
    neto = sum(_num(d, "neto") if "neto" in d else _num(d, "profit") for d in conocidos)
    return {
        "conocidos": len(conocidos),
        "sin_datos": len(desenlaces) - len(conocidos),
        "por_resultado": conteo.most_common(),
        "bruto_total": bruto,
        "costos_total": costos,
        "neto_total": neto,
        "profit_total": neto,
        "costos_desconocidos": sin_costos,
    }
