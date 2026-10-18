"""Parser de mensajes de Telegram -> SignalEvent.

Un grupo de senales real no manda texto prolijo. Manda emojis, markdown,
mayusculas mezcladas, rangos de entrada, TPs en una sola linea separados por
barras, y mensajes de gestion como "close half" o "SL to BE".

La estrategia del parser es:

1. Normalizar (sacar emojis/markdown, uniformar mayusculas y separadores).
2. Extraer los datos duros (simbolo, lado, precios) SIN decidir todavia que es.
3. Recien ahi clasificar el evento, usando keywords Y los datos extraidos.

El paso 3 va ultimo a proposito: un mensaje como "GOLD SELL, close above 2350
is invalid" contiene la palabra CLOSE pero es una senal de apertura. Con el
lado + SL + TPs ya extraidos se puede desempatar bien.
"""

from __future__ import annotations

import re
import unicodedata

from tct.signals.models import EventType, OrderType, SignalEvent, Side

# --------------------------------------------------------------------------
# Simbolos
# --------------------------------------------------------------------------

# Como llama la gente a cada instrumento -> como lo llamamos nosotros.
# El nombre del broker se resuelve despues, en brokers/symbol_map.py: aca solo
# unificamos el vocabulario del grupo.
SYMBOL_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSD", "ORO": "XAUUSD", "XAU": "XAUUSD", "XAUUSD": "XAUUSD",
    "SILVER": "XAGUSD", "PLATA": "XAGUSD", "XAG": "XAGUSD", "XAGUSD": "XAGUSD",
    "NAS": "NAS100", "NAS100": "NAS100", "NASDAQ": "NAS100", "NDX": "NAS100",
    "USTEC": "NAS100", "US100": "NAS100", "TECH100": "NAS100",
    "DOW": "US30", "DJ30": "US30", "US30": "US30", "DJI": "US30",
    "WALLSTREET": "US30", "WS30": "US30",
    "SPX": "US500", "SPX500": "US500", "SP500": "US500", "US500": "US500",
    "DAX": "GER40", "GER30": "GER40", "GER40": "GER40", "DE40": "GER40",
    "FTSE": "UK100", "UK100": "UK100",
    "OIL": "USOIL", "CRUDE": "USOIL", "WTI": "USOIL", "USOIL": "USOIL",
    "BRENT": "UKOIL", "UKOIL": "UKOIL",
    "BTC": "BTCUSD", "BITCOIN": "BTCUSD", "BTCUSD": "BTCUSD",
    "ETH": "ETHUSD", "ETHEREUM": "ETHUSD", "ETHUSD": "ETHUSD",
}

_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"}

# Los alias se prueban de mas largo a mas corto para que "NAS100" gane sobre
# "NAS" y "XAUUSD" sobre "XAU".
_ALIASES_BY_LENGTH = sorted(SYMBOL_ALIASES, key=len, reverse=True)

# --------------------------------------------------------------------------
# Etiquetas de precio
# --------------------------------------------------------------------------

# Cada match parte el mensaje en "chunks": la etiqueta se queda con todo el
# texto hasta la etiqueta siguiente. Asi "TP: 2355 / 2365 / 2375" cae en un
# solo chunk con 3 numeros, y "TP1 2355 TP2 2365" cae en dos chunks de 1.
#
# El `\d?(?![\d,]|\.\d)` del indice de TP es deliberado y fragil de tocar:
# separa "TP1 2355" (el 1 es el numero de target) de "TP 1.2700" y "TP 2330"
# (donde ese digito es el precio). Solo se traga UN digito, y solo si despues
# no sigue otro digito ni un DECIMAL. Un punto suelto si: "TP1. 4154" (Gold
# Signals 98% Sure, 16/10) no se leia como TP y la senal se rechazaba.
_LABEL_RE = re.compile(
    r"(?P<TP>\b(?:TAKE\s*PROFITS?|TARGETS?|OBJETIVOS?|TPS?|T/P)\s*\d?(?![\d,]|\.\d))"
    r"|(?P<SL>\b(?:STOP\s*LOSS|STOPLOSS|SL|S/L|STOP)\b)"
    # El "@" solo cuenta como etiqueta si lo sigue un numero ("BUY @ 2345").
    # Sin ese lookahead, un @usuario del pie del mensaje ("@gold2345") pisaba
    # el precio de entrada con los digitos del nombre, y como suele caer entre
    # el SL y el TP la validacion geometrica no lo notaba.
    r"|(?P<ENTRY>\b(?:ENTRY\s*ZONE|ENTRY\s*PRICE|ENTRY|ENTRADA|ENTER|PRECIO|PRICE|ZONA|ZONE)\b|@(?=\s*\d))"
)

# Numeros de precio. Ignora los que llevan % pegado (son fracciones de cierre,
# no precios) y los que son parte de un ratio tipo "1:3".
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?")

_SIDE_RE = re.compile(r"\b(BUY|SELL|LONG|SHORT|COMPRA|VENTA)\b")
# El tipo de orden tiene que estar PEGADO al lado, de uno u otro lado:
# "BUY LIMIT 2345" o "LIMIT BUY 2345". Antes la segunda forma aceptaba un
# LIMIT o un STOP en cualquier parte del texto con tal de que despues hubiera
# un BUY o un SELL, y eso convertia una orden a mercado en PENDIENTE con solo
# nombrar la palabra:
#
#     "Ojo con el stop de ayer. DEAL | GOLD BUY XAUUSD 4432..."  -> BUY STOP
#
# Este canal habla del stop loss todo el tiempo y a veces le pone una frase
# adelante al mensaje de apertura, asi que no era hipotetico. Y una pendiente
# es justo lo que el bot peor maneja: se dispara sola mas tarde y abre una
# posicion que nadie gestiona.
#
# Se pierde reconocer "SELL 2350 limit" (el tipo despues del precio). Es el
# lado barato: perder una pendiente cuesta una senal, inventarla cuesta una
# posicion que nadie pidio (§12).
_ORDER_TYPE_RE = re.compile(
    r"\b(?:BUY|SELL|LONG|SHORT)\s+(LIMIT|STOP|NOW|MARKET)\b"
    r"|\b(LIMIT|STOP)\s*(?:ORDER)?\s*[:\-]?\s*(?=(?:BUY|SELL|LONG|SHORT)\b)"
)

_PARTIAL_RE = re.compile(
    r"\b(?:CLOSE|CLOSING|CIERRE|CIERREN|CERRAR|TAKE|TOMAR|SECURE)\b[^\n]{0,25}?"
    r"\b(?:HALF|MITAD|PARTIALS?|PARCIALES?|PARCIAL|\d{1,3}\s*%)"
    r"|\b(?:PARTIALS?|PARCIALES?|PARCIAL)\b"
    r"|\bCLOSE\s+\d{1,3}\s*%"
)
# CIERRE tambien es un sustantivo del analisis: "un cierre de vela por encima
# de 4450", "el cierre diario del oro fue en 4185", "cierre semanal:". Con un
# articulo adelante, o seguido de vela, dia, semana..., no pide cerrar nada: se
# leia como CERRAR y el bot cerraba TODAS las posiciones de oro (auditoria del
# 16/10).
# "Por encima / por debajo" es analisis cuando va con un nivel: "un cierre por
# encima de 4450". "CIERRE POR ENCIMA DE TODO" es una orden.
_UN_NIVEL = (r"(?:POR\s+(?:ENCIMA|DEBAJO)|ARRIBA|ABAJO|ABOVE|BELOW)(?:\s+DE)?\s+"
             r"(?:(?:LOS?|LAS?|EL|DEL)\s+)?(?:\d|NIVEL|SOPORTE|RESISTENCIA|ZONA|RANGO)")
_ANALISIS_DE_CIERRE = (
    r"(?!\s+(?:" + _UN_NIVEL + r"|LA\s+(?:SEMANA|VELA|SESION)|H\d|\d+H|D1|W1))"
)
# SALIR cierra, como siempre ("salir del negocio", "salir en BE", "hay que
# salir", "SALIR" solo), salvo cuando lo que sale es el PRECIO de una figura
# o es la vida del que escribe. En los mensajes reales de David (295, del 07/09
# al 16/10) "salir" nunca fue una orden y tres veces cerro todo el oro: "intentare
# salir a internet lo minimo posible", "somos capaces de salir de una situacion
# asi" y, el 13/10, "estamos abriendo la segunda posicion... el precio esta
# comenzando a salir del desbalance": la real cerro las dos compras recien
# abiertas. Antes, "queriamos salir todos juntos" (un testimonio de Genesis) y
# "el precio puede salir del rango" tambien cerraban.
#
# Se probaron dos veces reglas mas cerradas ("salir" cierra solo con "de la
# posicion"...) y las dos revisiones del 17/10 encontraron ordenes perdidas
# ("SALIR", "SALIR DE AMBAS", 'PARA EL NEGOCIO "COMPRA 4184" SALIR') y cierres
# nuevos ("ayer salimos de la operacion"). Por eso quedo asi: lo de siempre,
# con estas excepciones, que son las que se vieron.
_SALIR_QUE_NO_CIERRA = (
    r"(?!\s+(?:TODOS\s+JUNTOS|JUNTOS|DE\s+VACACIONES|DE\s+PASEO|DE\s+VIAJE|"
    r"A\s+(?:PASEAR|CENAR|COMER|CAMINAR|DISFRUTAR|CORRER|CELEBRAR|INTERNET|LA\s+CALLE)|"
    r"DE\s+(?:(?:UNA|ESTA|ESA|LA|ESTAS|ESAS|LAS)\s+)?SITUACION(?:ES)?\b|"
    r"DEL?\s+(?:(?:LA|EL|UN|UNA|ESTE|ESTA|ESE|ESA)\s+)?(?:RANGO|ZONA|CANAL|TRIANGULO|"
    r"CONSOLIDACION|ACUMULACION|LATERAL|LATERALIDAD|CUNA|BANDERA|DESBALANCE|"
    r"DESEQUILIBRIO|IMBALANCE)\b))"
)
_CLOSE_RE = re.compile(
    r"\b(?:CLOSE|CLOSED|CERRAR)\b" + _ANALISIS_DE_CIERRE +
    r"|\b(?:CIERREN|EXIT|CANCEL|CANCELAR)\b|\bSALIR\b" + _SALIR_QUE_NO_CIERRA +
    r"|(?<!UN )(?<!EL )(?<!DEL )(?<!AL )(?<!SU )(?<!ESTE )(?<!BUEN )(?<!OTRO )"
    r"(?<!NUESTRO )\bCIERRE\b"
    r"(?!\s+(?:DE\s+(?:LA\s+|UNA\s+|\d+\s*)?(?:VELA|SEMANA|MERCADO|SESION|DIA|MES|ANO|H\b)"
    r"|DIARIO|SEMANAL|MENSUAL|ANUAL|DEL\s+(?:DIA|MES|ANO|MERCADO|VIERNES)"
    r"|DEL\s+ORO\s+(?:POR|EN|ARRIBA|ABAJO)\b|DE\s+(?:HOY|AYER)|" + _UN_NIVEL + r"|CONFIRMADO"
    r"|EN\s+(?:H\d|\d+H|TP|BE|GANANCIA|PERDIDA|\d)|H\d|\d+H|D1|W1))"
    # El pedido con sustantivo, que el articulo de arriba dejaba afuera.
    r"|\b(?:PROCEDAN|PROCEDA|HAGAN|HAGA|REALICEN|REALICE|EJECUTEN|EJECUTE)\s+"
    r"(?:EL\s+|AL\s+)?CIERRE\b"
)
# MOVA, MUEVA, MUEVAN, MUEVE...: el canal escribe en espanol de traductor
# ("MOVA SU SL A SER EL SL RESULTANTE ES 4187", 30/09). El verbo tiene que
# apuntar a un SL o STOP a menos de 30 caracteres, asi que "el precio se
# mueve" no alcanza.
_MOVE_SL_RE = re.compile(
    r"\b(?:MOVE|MOVER|MOVA|MOVAN|MUEVA|MUEVAN|MUEVE|MOVEMOS|MOVAMOS|SET|PON|PONER|"
    r"COLOQUE|COLOQUEN|BRING|SUBIR|BAJAR|TRAIL)\b[^\n]{0,30}?\b(?:SL|STOP)\b"
    r"|\b(?:SL|STOP\s*LOSS)\b[^\n]{0,20}?\b(?:TO\s+)?(?:BE|B/E|BREAK\s*EVEN|BREAKEVEN|ENTRY|ENTRADA)\b"
    r"|\b(?:BREAK\s*EVEN|BREAKEVEN)\b"
)
# Pedido EXPLICITO de mover un take profit: un verbo de accion apuntando a un TP.
#
# Hace falta el verbo; no alcanza con que aparezca "TP 4450". Medido contra el
# parser: "TP1 4450" a secas y "nuestro TP1 era 4436" -un RELATO- tambien traen
# un TP con precio. Si cualquier TP con precio moviera posiciones, una cronica
# del canal te llevaria el objetivo a un precio viejo.
#
# Los verbos que NO estan, a proposito: SUBE, BAJA, LLEVA, MUEVE, LLEGA, TOCA.
# Describen al PRECIO ("el precio sube hasta el TP 4450"), no piden nada. Y
# tampoco SET ni UPDATE: "Update: TP1 4436 hit" es un resultado.
#
# Entre el verbo y el TP no puede haber un SL o STOP: "Mover SL a 4432, TP se
# mantiene en 4440" pide mover el STOP, y leerlo como "mover el TP a 4440"
# pisaria un objetivo que el canal dijo que se queda.
_MOVE_TP_RE = re.compile(
    r"\b(?:MOVE|MOVING|MOVER|MOVEMOS|MOVAMOS|MUEVAN|CHANGE|CAMBIAR|CAMBIA|CAMBIEN|"
    r"CAMBIAMOS|MODIFY|MODIFICAR|MODIFICA|MODIFICAMOS|ADJUST|AJUSTAR|AJUSTA|"
    r"AJUSTAMOS|ACTUALIZAR|ACTUALIZA|ACTUALIZAMOS|PONER|PONEMOS)\b"
    r"(?:(?!\b(?:SL|STOP)\b)[^\n]){0,30}?"
    r"\b(?:TP\s*\d?|TAKE\s*PROFIT)\b"
)
# Marcas de que el mensaje CUENTA algo que ya paso, en vez de pedir algo.
#
# Es el filtro mas importante del parser. Los canales postean recaps todo el
# dia repitiendo la senal completa ("CERRADA EN GANANCIA / GOLD SELL 2350 /
# SL 2360 / TP 2340"), y sin esto cada recap abria una operacion nueva: mismo
# simbolo, mismo lado, precios coherentes entre si, geometria valida. Pasaba
# todos los controles porque, mirado como datos, era una senal perfecta.
#
# No alcanza con las palabras de gestion (CERRAR, CLOSE): "cerrada" describe,
# no ordena. Y no se puede usar el tilde verde solo, porque muchos canales lo
# ponen de adorno en senales legitimas.
_RESULTADO_RE = re.compile(
    r"\b(?:CERRAD[AO]S?|RESULTADOS?|ALCANZAD[AO]S?|CONSEGUID[AO]S?|LOGRAD[AO]S?|"
    r"GANANCIAS?|PROFITS?|PERDIDAS?|HIT|REACHED|SECURED|CLOSED)\b"
    r"|[+-]\s*\d+\s*PIPS"
    # "TARGET 1 COMPLETE 330+ PIPS DONE", "Gold Sell Running 260+ Pips": el
    # resultado de una senal, no una nueva (16/10).
    r"|\d+\s*\+\s*PIPS"
)

# Verbos que solo aparecen CONTANDO algo, nunca pidiendolo. Son primera
# persona del plural en pasado, o participios: "pudimos cerrar", "cerramos",
# "operacion cerrada". Ninguna orden real de un canal usa estas formas.
#
# Van en un regex aparte de _RESULTADO_RE y se chequean ANTES que la gestion,
# porque el problema que resuelven es exactamente que la palabra de gestion
# esta presente: "Pudimos CERRAR otra operacion" tiene CERRAR, y sin esto se
# ejecutaba como una orden de cerrar todo.
#
# _RESULTADO_RE, en cambio, tiene marcas mas debiles (HIT, PIPS) que SI
# aparecen en ordenes legitimas ("TP1 hit, move SL to BE"), por eso se chequea
# despues de la gestion.
_NARRATIVA_RE = re.compile(
    r"\b(?:PUDIMOS|LOGRAMOS|CONSEGUIMOS|CERRAMOS|GANAMOS|TERMINAMOS|HICIMOS|"
    r"SUMAMOS|LLEVAMOS\s+\w+\s+OPERACION|"
    r"WE\s+(?:CLOSED|MADE|GOT|HIT)|MANAGED\s+TO)\b"
)

def es_descarte_deliberado(text: str) -> bool:
    """True si este mensaje se descarta A PROPOSITO, no por no entenderlo.

    POR QUE HACE FALTA DISTINGUIRLO
    -------------------------------
    `parse_signal` devuelve None en dos situaciones que no tienen nada que ver
    entre si:

        a) "esto no es un mensaje de trading"      -> no lo entendi
        b) "esto es una cronica o un recap"        -> lo entendi y lo descarto

    El caso (b) es una DECISION, y de las caras: `_NARRATIVA_RE` y
    `_RESULTADO_RE` existen porque un "pudimos cerrar otra operacion" se
    ejecutaba como una orden de cerrar todo, y un recap abria operaciones.

    Con los dos casos devolviendo el mismo None, el motor no podia separarlos
    y le mandaba TAMBIEN las cronicas a la IA local, que es un modelo de 3B y
    las lee como aperturas. Caso real del canal del usuario:

        "Asi que, chicos, aqui estan nuestros resultados de la primera
         operacion. Lo considero un buen comienzo"

    El parser de reglas lo descartaba bien; la IA lo interpretaba como OPEN.
    No llego a operar nada porque OLLAMA_AUTO_EXECUTE esta en false, pero
    generaba una notificacion por Telegram por cada mensaje y edicion, y ~15
    segundos de CPU cada una. O sea: la capa de IA rodeaba una guarda que se
    habia puesto a proposito.

    Recibe el mensaje CRUDO y lo normaliza aca adentro. Los regex trabajan
    sobre texto en mayusculas y sin acentos, asi que pasarles el original no
    matchea nada: "resultados" no es "RESULTADOS". Que la normalizacion sea
    interna evita que quien llame tenga que acordarse.
    """
    normalizado = _normalize(text)
    return bool(
        _NARRATIVA_RE.search(normalizado) or _RESULTADO_RE.search(normalizado)
    )


def pide_mover_tp(text: str) -> bool:
    """True si el mensaje pide, con un verbo, mover un take profit.

    Lo usa el motor para un caso puntual: un mensaje que pide mover el stop Y
    el TP sale clasificado como MOVE_SL, y hay que saber si ademas corresponde
    tocar el TP. Recibe el texto CRUDO, igual que `es_descarte_deliberado`.
    """
    return _pide_mover_tp_normalizado(_normalize(text))


def _pide_mover_tp_normalizado(normalizado: str) -> bool:
    """El chequeo sobre texto ya normalizado (mayusculas, sin acentos).

    Ademas del verbo descarta relatos y resultados. `_RESULTADO_RE` se mira sin
    la frase TAKE PROFIT, porque PROFIT es una de sus marcas: sin sacarla, un
    "mover el take profit a 4450" legitimo quedaria bloqueado.
    """
    if not _MOVE_TP_RE.search(normalizado):
        return False
    if _NARRATIVA_RE.search(normalizado):
        return False
    sin_take_profit = re.sub(r"\bTAKE\s*PROFITS?\b", " ", normalizado)
    return not _RESULTADO_RE.search(sin_take_profit)


_BREAKEVEN_RE = re.compile(r"\b(?:BE|B/E|BREAK\s*EVEN|BREAKEVEN)\b")

# Una gestion que nombra a QUE posicion va: 'PARA LA POSICION "BUY 4187",
# MOVA SU SL ... 4187' (30/09, dos veces). El "BUY 4187" no es una senal
# nueva, es el nombre de una que ya esta abierta. Antes el BUY y el 4187 se
# leian como una apertura sin simbolo y se rechazaba: el breakeven no se
# aplicaba nunca. Se saca del texto antes de buscar lado y precios, y queda
# guardado para que la gestion toque SOLO esa posicion. NEGOCIO es del 13/10:
# 'PARA EL NEGOCIO "COMPRA 4184" ESTABLECER SL 4184'.
_REFERENCIA_POSICION_RE = re.compile(
    r"\b(?:POSICION|POSITION|OPERACION|ORDEN|TRADE|NEGOCIO)\s*(?:DE\s+|EN\s+)?[\"'`]*\s*"
    r"(BUY|SELL|COMPRA|VENTA)\s+(\d+(?:[.,]\d+)?)\s*[\"'`]*"
)
# ESTABLECER, desde el 13/10: 'PARA EL NEGOCIO "COMPRA 4184" ESTABLECER SL
# 4184' y 'ESTABLEZCA AMBOS SL EN LA MARCA 4170'. Sin el verbo esos breakeven
# se leian como aperturas sin simbolo y el stop no se movia.
#
# Va APARTE de _MOVE_SL_RE y en una forma estrecha: el verbo, el SL, y en
# seguida el precio o el BE. Y solo cuenta con la posicion nombrada o al
# principio del mensaje. Suelto en cualquier lado convertia en orden la teoria
# y el analisis ("es importante establecer su stop loss en 4150"): con una
# sola posicion abierta, el stop se AGRANDABA (auditoria del 16/10).
_ESTABLECER_SL_RE = re.compile(
    r"\b(?:ESTABLECER|ESTABLEZCA|ESTABLEZCAN)\s+"
    r"(?:(?:EL|SU|SUS|LOS|AMBOS|AMBAS|TODOS|TODAS)\s+)?"
    r"(?:SL|STOP(?:\s*LOSS)?)\s*(?:EN|A|=|:)?\s*(?:LA\s+MARCA\s+(?:DE\s+)?)?"
    r"(?=\d|(?:BE|B/E|BREAK\s*EVEN|BREAKEVEN)\b)"
)
_AL_EMPEZAR_RE = re.compile(r"(?m)^\W*$")

# "NO CIERREN LA POSICION", "NO ESTABLEZCAN EL SL EN BE TODAVIA": un pedido
# negado no es un pedido. Se mira solo la clausula -hasta la coma o el punto
# anteriores-, para que "NO CIERREN, MUEVAN EL SL A BE" siga moviendo el stop.
# Salvo las que piden lo contrario: "no olviden mover el SL a BE", "no duden en
# cerrar", "no dejen de mover el stop" son ordenes, y perderlas es un breakeven
# que no se aplica.
_NEGACION_RE = re.compile(
    r"\b(?:NO|NUNCA|JAMAS|NOT|DON'?\s?T)\b"
    r"(?!(?:\s+(?:SE|TE|LES|LE|NOS|ME|DEBEN|DEBES|DEBEMOS|PUEDEN|HAY\s+QUE))*"
    r"\s+(?:OLVID|DUD(?:EN|ES|E|AR)\b|DEJ\w*\s+DE\b|FORGET|HESITATE))"
)
# El canal junta oraciones sin puntuar ("YA NO HAY RIESGO MUEVAN EL SL A BE"):
# PERO, ASI QUE y ENTONCES tambien cortan la clausula.
_FIN_DE_CLAUSULA_RE = re.compile(r"[.,;:!?\n]|\b(?:PERO|ASI\s+QUE|ENTONCES|BUT)\b")
# Con un imperativo, el NO lo niega solo si esta PEGADO ("NO CIERREN", "NO LO
# MUEVAN") o atado con QUE/NI ("NO QUIERO QUE CIERREN"). "YA NO HAY RIESGO
# MUEVAN EL SL" es una orden: el NO es de otra frase.
_IMPERATIVO_RE = re.compile(
    r"(?:MUEVAN|MUEVA|MOVA|MOVAN|CIERREN|CIERRE|COLOQUEN|COLOQUE|PON|ESTABLEZCAN|"
    r"ESTABLEZCA|MOVE|CLOSE|EXIT|SET|BRING|TRAIL|CANCEL|TOMEN|TOME|TAKE)\b"
)
_RELLENO = (r"(?:(?:TODAVIA|AUN|YA|LO|LA|LOS|LAS|LE|LES|SE|ME|TE|NOS|YET|TO|DE|EL|SU|SUS|"
            r"AMBOS|AMBAS|TODOS|TODAS|NUESTRO|NUESTROS|NUESTRA|THE|YOUR|A)\s+)*")
_PEGADA_AL_VERBO_RE = re.compile(r"\s*" + _RELLENO)
# Sin imperativo ("NO ESTABLEZCAN EL SL EN BE": lo que coincide es "SL EN BE"),
# entre el NO y el pedido puede ir, ademas, el verbo de gestion que se niega.
# "NO HAY RIESGO, SL A BE" o "NO ME GUSTA, CERRAR TODO" no niegan nada.
_PEGADA_AL_PEDIDO_RE = re.compile(
    r"\s*" + _RELLENO
    + r"(?:(?:MUEV|MOV|ESTABLE|COLOQU|COLOC|PON|CIERR|CERR|TOM|SUB|BAJ|AJUST|SET|CLOSE|"
      r"TAKE|PUT|BRING)\w*\s+" + _RELLENO + r")?")
# "SI TODAVIA NO MOVIERON EL SL A BE, HAGANLO" y "QUIEN NO HAYA MOVIDO EL SL":
# ese NO es de la condicion, no del pedido.
_NO_DE_UNA_CONDICION_RE = re.compile(
    r"\b(?:SI|QUIEN|QUIENES|IF)\s+(?:(?:TODAVIA|AUN|YA|STILL)\s+)?$")
_ATADA_AL_VERBO_RE = re.compile(r"\b(?:QUE|NI|OR|NOR)\s*$")

# Lo que sigue a una posicion nombrada cuando se la CUENTA, no se le pide
# nada: 'la posicion "BUY 4185" se cerro en BE', '"BUY 4433": MANTENER EL SL'.
_NARRA_LA_REFERENCIA_RE = re.compile(
    r"\W*(?:SE\s+)?(?:CERRO|CERRARON|ALCANZO|TOCO|LLEGO|SALIO|FUE|ESTA\s+CERRAD\w*|"
    r"MANTENER|MANTENGAN|MANTIENE|SIGUE|QUEDA)\b"
)
_MANTENER_RE = re.compile(
    r"\W*(?:MANTENER|MANTENGAN|MANTIENE)\s+(?:EL|SU|SUS|LOS)\s+(?:SL|STOP)\b")
_SL_CON_PRECIO_RE = re.compile(
    r"\b(?:SL|STOP(?:\s*LOSS)?)\s*(?:EN|A|=|:)?\s*(?:LA\s+MARCA\s+(?:DE\s+)?)?"
    r"(\d+(?:[.,]\d+)?)"
)


def _sin_negar(regex: re.Pattern, text: str) -> re.Match | None:
    """La primera coincidencia de `regex` que es un pedido: no negada en su
    clausula, y no una pregunta ("¿MOVEMOS EL SL A BE?")."""
    for encontrada in regex.finditer(text):
        siguiente = _FIN_DE_CLAUSULA_RE.search(text, encontrada.end())
        if siguiente is not None and siguiente.group(0) == "?":
            continue
        inicio = 0
        for fin in _FIN_DE_CLAUSULA_RE.finditer(text, 0, encontrada.start()):
            inicio = fin.end()
        negaciones = [n for n in _NEGACION_RE.finditer(text, inicio, encontrada.start())
                      if not _NO_DE_UNA_CONDICION_RE.search(text, inicio, n.start())]
        if not negaciones:
            return encontrada
        entre = text[negaciones[-1].end():encontrada.start()]
        pegada = (_PEGADA_AL_VERBO_RE if _IMPERATIVO_RE.match(text, encontrada.start())
                  else _PEGADA_AL_PEDIDO_RE)
        if not pegada.fullmatch(entre) and not _ATADA_AL_VERBO_RE.search(entre):
            return encontrada
    return None


# Sin posicion nombrada, ESTABLECER cuenta solo si el pedido termina en el
# precio o el BE: "ESTABLECER SL 4150 ES LO QUE YO HARIA" y "ESTABLEZCAN EL SL
# EN 4400 SI QUIEREN DARLE ESPACIO" son consejos, y con una sola posicion
# abierta agrandaban el stop.
_TERMINA_EN_EL_PRECIO_RE = re.compile(
    r"\s*(?:\d+(?:[.,]\d+)?|BE|B/E|BREAK\s*EVEN|BREAKEVEN)\s*(?:\(BE\))?\s*"
    r"(?:[.!]\s*)?(?:\n|$)"
)


def _establecer_como_mover(text: str, *, con_referencia: bool) -> str:
    """Si el mensaje pide ESTABLECER el SL en una forma valida, lo reescribe con
    MOVER, que es lo que entiende el resto del parser."""
    pedido = _sin_negar(_ESTABLECER_SL_RE, text)
    if pedido is None:
        return text
    if not con_referencia and (
            not _AL_EMPEZAR_RE.match(text[text.rfind("\n", 0, pedido.start()) + 1:pedido.start()])
            or not _TERMINA_EN_EL_PRECIO_RE.match(text, pedido.end())):
        return text
    verbo = pedido.group(0).split()[0]
    return text[: pedido.start()] + "MOVER" + text[pedido.start() + len(verbo):]


_HALF_RE = re.compile(r"\b(?:HALF|MITAD)\b")
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")


def parse_signal(
    message: str,
    *,
    message_id: int | None = None,
    chat_id: int | None = None,
    is_edit: bool = False,
    reply_to_message_id: int | None = None,
    source: str = "text",
) -> SignalEvent | None:
    """Convierte un mensaje en un `SignalEvent`, o None si no es de trading.

    Devolver None es una decision explicita: el 90% de lo que se manda en un
    grupo es charla. Solo se considera senal si hay un lado (BUY/SELL) o una
    instruccion de gestion reconocible.
    """
    if not message or not message.strip():
        return None

    text = _normalize(message)
    warnings: list[str] = []

    # --- Paso 1: gestion que nombra su posicion ("POSICION "BUY 4187"") ---
    text, posicion_lado, posicion_entrada, todas_a_be = _separar_referencia_a_posicion(text)
    if posicion_lado is None and not todas_a_be:
        # 'ESTABLEZCA AMBOS SL EN LA MARCA 4170': sin posicion nombrada, solo
        # al principio del mensaje.
        text = _establecer_como_mover(text, con_referencia=False)

    # --- Paso 2: extraer datos duros --------------------------------------
    order_type, masked = _extract_order_type(text)
    symbol = _extract_symbol(masked)
    side = _extract_side(masked)

    # Los precios se buscan sobre el texto SIN los nombres de instrumento: si
    # no, el "30" de US30 se lee como un precio. Ver `_mask_symbols`.
    sin_simbolos = _mask_symbols(masked)
    entry_low, entry_high, stop_loss, take_profits = _extract_prices(sin_simbolos)

    # "🟢 BUY XAGUSD / 🚀 56.895 / SL: ..." (Academia de Trading Genesis,
    # 17/10): la entrada es el numero SOLO en la linea que sigue al lado. No
    # tiene etiqueta, y el analisis del final ("en zona de sobreventa (21/23)
    # con el precio...") trae ZONA y PRECIO, que si lo son: se leia entrada 22.
    # Solo en la cabecera (antes del primer SL o TP) y si no hay una etiqueta
    # de entrada ahi: "SELL XAUUSD / 17 / Entry 4510" sigue siendo 4510, y un
    # "BUY ✅ / +210" que el canal agrega al final al editar no pisa nada.
    sola = _ENTRADA_EN_SU_LINEA_RE.search(sin_simbolos)
    if sola is not None and side is not None:
        etiquetas = list(_LABEL_RE.finditer(sin_simbolos))
        primer_sl_tp = next((m.start() for m in etiquetas if m.lastgroup in ("SL", "TP")),
                            len(sin_simbolos))
        etiqueta_de_entrada = any(m.lastgroup == "ENTRY" and m.start() < primer_sl_tp
                                  for m in etiquetas)
        if sola.end() <= primer_sl_tp and not etiqueta_de_entrada:
            entry_low = entry_high = _to_float(sola.group(1))

    # Fallback: "GOLD BUY 2345" no tiene etiqueta "Entry". Si hay lado y no se
    # encontro entrada, tomamos el primer numero suelto que no sea SL ni TP.
    if entry_low is None and side is not None:
        entry_low, entry_high = _loose_entry(sin_simbolos, exclude={stop_loss, *take_profits})

    close_fraction = _extract_close_fraction(masked)

    # --- Paso 3: clasificar con todo a la vista ---------------------------
    event_type = _classify(
        masked,
        side=side,
        stop_loss=stop_loss,
        take_profits=take_profits,
        entry=entry_low,
        close_fraction=close_fraction,
        warnings=warnings,
    )

    if event_type is None:
        return None

    # Una publicidad no es una orden. Los canales "gratis" que venden un VIP
    # mezclan verbos de gestion en el texto ("aprender a ... cerrar posiciones
    # como corresponde", 16/10) y se leian como CERRAR. Una orden de gestion
    # es corta y no trae un @usuario ni un link para escribirle a alguien: hacen
    # falta las DOS cosas (6+ lineas y el contacto) para no perder una orden.
    if event_type in _GESTION_CON_DESTINO and _es_publicidad(text):
        return None

    # La referencia solo sirve para gestionar. Si con todo el mensaje a la
    # vista no salio gestion, no se arrastra a otra cosa.
    if event_type not in _GESTION_CON_DESTINO:
        posicion_lado = posicion_entrada = None

    # Normalizaciones finales por tipo de evento.
    if event_type is EventType.PARTIAL_CLOSE and close_fraction is None:
        close_fraction = 0.5
        warnings.append("Cierre parcial sin porcentaje explicito; se asume 50%")

    move_to_be = False
    if event_type is EventType.MOVE_SL and todas_a_be:
        # Un breakeven para cada posicion nombrada, cada una a su entrada.
        stop_loss, move_to_be = None, True
    elif event_type is EventType.MOVE_SL:
        move_to_be = bool(_BREAKEVEN_RE.search(masked)) and stop_loss is None
        if not move_to_be and stop_loss is None:
            warnings.append("MOVE_SL sin precio ni referencia a breakeven")

    if entry_low is not None and entry_high is not None and entry_low > entry_high:
        entry_low, entry_high = entry_high, entry_low

    if event_type is EventType.OPEN:
        warnings.extend(_sanity_warnings(side, entry_low, entry_high, stop_loss, take_profits))

    return SignalEvent(
        event_type=event_type,
        symbol=symbol,
        side=side,
        order_type=order_type,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop_loss,
        take_profits=take_profits,
        close_fraction=close_fraction,
        move_sl_to_breakeven=move_to_be,
        posicion_lado=posicion_lado,
        posicion_entrada=posicion_entrada,
        raw_message=message,
        telegram_message_id=message_id,
        telegram_chat_id=chat_id,
        is_edit=is_edit,
        reply_to_message_id=reply_to_message_id,
        source=source,
        warnings=warnings,
    )


_PUBLICIDAD_RE = re.compile(r"@\w{3,}|HTTPS?://|\bT\.ME/")


def _es_publicidad(text: str) -> bool:
    lineas = [linea for linea in text.splitlines() if linea.strip()]
    return len(lineas) >= 6 and bool(_PUBLICIDAD_RE.search(text))


_GESTION_CON_DESTINO = {
    EventType.MOVE_SL, EventType.MOVE_TP, EventType.CLOSE, EventType.PARTIAL_CLOSE,
}


def _separar_referencia_a_posicion(
    text: str,
) -> tuple[str, Side | None, float | None, bool]:
    """Saca del texto las 'POSICION "BUY 4187"' y dice a que posicion apunta.

    Devuelve (texto, lado, entrada, todas_a_be). Solo cuando el resto del
    mensaje es gestion (mover el stop, cerrar, un parcial) y NO trae take
    profits. Una senal de apertura siempre trae TP, y "TRADE BUY 4187 SL 4180
    TP 4195" tiene que seguir siendo una apertura: leerla como gestion perderia
    la senal entera.

    Con varias posiciones nombradas, se saltean las que el mensaje solo
    CUENTA ('"COMPRA 4433" CERRO EN TP1. AHORA PARA EL NEGOCIO "COMPRA 4432"
    ESTABLECER SL EN BE'): antes ganaba la primera, y el breakeven iba a la que
    ya no estaba. Si quedan varias, no se elige una: se aplica a todas, como
    antes; y si cada una tenia su SL en su propia entrada, es un breakeven para
    cada una (todas_a_be).
    """
    referencias = list(_REFERENCIA_POSICION_RE.finditer(text))
    if not referencias:
        return text, None, None, False

    sin_referencia = text
    for referencia in reversed(referencias):
        sin_referencia = (sin_referencia[: referencia.start()] + " POSICION "
                          + sin_referencia[referencia.end():])
    sin_referencia = _establecer_como_mover(sin_referencia, con_referencia=True)
    es_gestion = (
        _sin_negar(_MOVE_SL_RE, sin_referencia)
        or _sin_negar(_CLOSE_RE, sin_referencia)
        or _sin_negar(_PARTIAL_RE, sin_referencia)
    )
    _, _, _, take_profits = _extract_prices(_mask_symbols(sin_referencia))
    if not es_gestion or take_profits:
        return text, None, None, False

    if len(referencias) == 1:
        # Sola, es la destinataria aunque se la cuente ('LA POSICION "BUY
        # 4185" LLEGO AL TP1, MUEVAN SU SL A 4185'), salvo que se pida
        # mantenerla.
        pedidas = [] if _MANTENER_RE.match(text, referencias[0].end()) else referencias
    else:
        pedidas = [r for r in referencias
                   if not _NARRA_LA_REFERENCIA_RE.match(text, r.end())]
    if not pedidas:
        # Todas las nombradas se cuentan, ninguna se pide: no se toca nada.
        return text, None, None, False
    if len(pedidas) > 1:
        entradas = {_to_float(r.group(2)) for r in pedidas}
        stops = {_to_float(m.group(1)) for m in _SL_CON_PRECIO_RE.finditer(sin_referencia)}
        return sin_referencia, None, None, bool(stops) and stops <= entradas

    elegida = pedidas[0]
    lado = Side.BUY if elegida.group(1) in {"BUY", "COMPRA"} else Side.SELL
    return sin_referencia, lado, _to_float(elegida.group(2)), False


# --------------------------------------------------------------------------
# Normalizacion
# --------------------------------------------------------------------------


def _normalize(message: str) -> str:
    """Deja el mensaje en MAYUSCULAS, sin emojis ni markdown, con lineas intactas.

    Las lineas se conservan porque los limites de linea ayudan a que un TP no
    se "coma" numeros de la linea siguiente.
    """
    # NFKD + descarte de no-ASCII saca emojis y acentos de una (ENTRADA/ENTRÁDA).
    text = unicodedata.normalize("NFKD", message)
    text = "".join(ch for ch in text if ord(ch) < 128 or ch == "\n")
    text = text.upper()
    # "DON,T CLOSE YOUR BUY": la coma en lugar del apostrofo cortaba la frase
    # y el CLOSE quedaba sin negar (16/10).
    text = re.sub(r"\b(DON|DOESN|DIDN|CAN|WON|ISN|AREN)[,`]\s?T\b", r"\1'T", text)
    text = re.sub(r"[*_`~|]+", " ", text)          # markdown
    text = re.sub(r"[–—]", "-", text)     # guiones largos
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_order_type(text: str) -> tuple[OrderType, str]:
    """Detecta MARKET/LIMIT/STOP y enmascara el token para no confundirlo.

    Esto importa: en "BUY STOP 2350", la palabra STOP es el tipo de orden, no
    una etiqueta de stop loss. Si no se enmascara, el parser lee 2350 como SL.
    """
    match = _ORDER_TYPE_RE.search(text)
    if not match:
        return OrderType.MARKET, text

    keyword = (match.group(1) or match.group(2) or "").strip()
    order_type = {
        "LIMIT": OrderType.LIMIT,
        "STOP": OrderType.STOP,
        "NOW": OrderType.MARKET,
        "MARKET": OrderType.MARKET,
    }.get(keyword, OrderType.MARKET)

    # Se enmascara SOLO la palabra del tipo de orden, nunca el BUY/SELL que la
    # precede: si se borrara "SELL LIMIT" entero, el lado se perderia y la
    # senal terminaria clasificada como UPDATE en vez de OPEN.
    start, end = match.span(1) if match.group(1) else match.span(2)
    masked = text[:start] + " " * (end - start) + text[end:]
    return order_type, masked


def _extract_symbol(text: str) -> str | None:
    """Encuentra el instrumento, priorizando el que acompana al BUY/SELL.

    Antes ganaba el alias mas largo del diccionario sin importar donde
    apareciera en el mensaje. Con "Mientras el gold descansa, BTC BUY 65000"
    eso abria ORO en vez de bitcoin: una operacion en el instrumento
    equivocado, con precios coherentes entre si, que pasaba todos los
    controles.

    Ahora gana el que esta mas cerca del BUY/SELL, que es donde vive el
    instrumento de verdad; lo demas son menciones al pasar.
    """
    candidatos: list[tuple[int, int, str]] = []
    for alias in _ALIASES_BY_LENGTH:
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text):
            # El tercer criterio es el largo negado: con la misma distancia,
            # gana el alias mas especifico (NAS100 antes que NAS).
            candidatos.append((match.start(), -len(alias), SYMBOL_ALIASES[alias]))

    if candidatos:
        lado = _SIDE_RE.search(text)
        if lado is not None:
            candidatos.sort(key=lambda c: (abs(c[0] - lado.start()), c[1]))
        else:
            candidatos.sort(key=lambda c: (c[0], c[1]))
        return candidatos[0][2]

    # Par de divisas: dos monedas conocidas pegadas (EURUSD, GBPJPY...).
    for match in re.finditer(r"\b([A-Z]{3})([A-Z]{3})\b", text):
        base, quote = match.group(1), match.group(2)
        if base in _CURRENCIES and quote in _CURRENCIES and base != quote:
            return base + quote

    # Con separador: EUR/USD, GBP-JPY.
    for match in re.finditer(r"\b([A-Z]{3})\s*[/-]\s*([A-Z]{3})\b", text):
        base, quote = match.group(1), match.group(2)
        if base in _CURRENCIES and quote in _CURRENCIES and base != quote:
            return base + quote

    return None


def _mask_symbols(text: str) -> str:
    """Borra los nombres de instrumento antes de buscar precios.

    Sin esto, "US30 SELL 39,500" toma el 30 de "US30" como precio de entrada:
    el nombre del instrumento LLEVA digitos y el extractor de numeros no
    distingue. Afecta a todos los indices (US30, NAS100, US500, GER40, UK100)
    justo en el campo mas peligroso, la entrada.

    Se reemplaza por espacios de la misma longitud para no correr las
    posiciones, que el troceado por etiquetas necesita intactas.
    """
    masked = text
    for alias in _ALIASES_BY_LENGTH:
        masked = re.sub(
            rf"\b{re.escape(alias)}\b",
            lambda m: " " * len(m.group(0)),
            masked,
        )
    # Los pares de divisas no traen digitos, pero se enmascaran igual para que
    # ningun resto suyo pueda confundirse con un numero.
    def _borrar_par(match: re.Match[str]) -> str:
        base, quote = match.group(1), match.group(2)
        if base in _CURRENCIES and quote in _CURRENCIES and base != quote:
            return " " * len(match.group(0))
        return match.group(0)

    masked = re.sub(r"\b([A-Z]{3})([A-Z]{3})\b", _borrar_par, masked)
    return masked


# "LARGO" / "CORTO" como encabezado de la senal (Sebastian | Banco Plata,
# 16/10). Solo SOLOS en su linea: en una frase son "a largo plazo" o "un
# camino corto", y leerlos como lado inventaria senales.
_LADO_EN_SU_LINEA_RE = re.compile(r"(?m)^\W*(LARGO|CORTO)\W*$")


def _extract_side(text: str) -> Side | None:
    match = _SIDE_RE.search(text)
    if not match:
        encabezado = _LADO_EN_SU_LINEA_RE.search(text)
        if encabezado is None:
            return None
        return Side.BUY if encabezado.group(1) == "LARGO" else Side.SELL
    token = match.group(1)
    return Side.SELL if token in {"SELL", "SHORT", "VENTA"} else Side.BUY


# --------------------------------------------------------------------------
# Precios
# --------------------------------------------------------------------------


# La linea del lado ("BUY", con el simbolo ya borrado y sin numeros) y, en la
# linea siguiente, un numero solo: la entrada de Genesis. Las dos condiciones
# juntas: un numero suelto en cualquier otro lugar no es una entrada.
_ENTRADA_EN_SU_LINEA_RE = re.compile(
    r"(?m)^\W*(?:BUY|SELL|COMPRA|VENTA|LONG|SHORT)\b[^\n\d]*\n\W*(\d+(?:[.,]\d+)?)\W*$"
)


def _solo_lineas_de_precio(chunk: str) -> str:
    """El bloque de una etiqueta, sin el parrafo o el contacto que vienen despues.

    "TP 5: 57.300 / El Estocastico en M5 ..." (Genesis, 17/10): el analisis
    pegado debajo del ultimo TP se leia entero, y el "5" de "M5" quedaba como
    otro take profit; igual el "2024" de un "@vipsignals2024" del pie.

    Se corta recien cuando el bloque YA tiene su precio, y solo en una linea
    que no empieza con un numero y es un parrafo (seis palabras o mas) o un
    @usuario / link. Con menos se perdian precios reales: "ESTABLEZCA AMBOS
    SL\\nEN LA MARCA 4170" (David, con el salto de linea) dejaba el SL sin
    precio y el stop no se movia; "TP:\\nFirst one at 2355\\nSecond one at
    2365" perdia el segundo (lo encontro la revision del 17/10).
    """
    lineas = chunk.split("\n")
    quedan = [lineas[0]]
    for linea in lineas[1:]:
        ya_tiene_precio = _NUMBER_RE.search("\n".join(quedan)) is not None
        if ya_tiene_precio and not re.match(r"^\W*\d", linea) and (
                len(re.findall(r"[A-Z]{2,}", linea)) >= 6 or "@" in linea
                or "HTTP" in linea):
            break
        quedan.append(linea)
    return "\n".join(quedan)


def _extract_prices(text: str) -> tuple[float | None, float | None, float | None, list[float]]:
    """Reparte los numeros del mensaje entre entrada, SL y TPs.

    Cada etiqueta se queda con el texto hasta la etiqueta siguiente, y de
    ese texto, solo su linea y las de precios que la siguen.
    """
    matches = list(_LABEL_RE.finditer(text))
    entry_low = entry_high = stop_loss = None
    take_profits: list[float] = []

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[match.end() : end]
        # Una linea en blanco cierra el bloque de precios. Sin esto, la ultima
        # etiqueta se tragaba todo el pie del mensaje y cosas como
        # "Valido 24hs. Grupo VIP 2024" entraban como take profits.
        corte = chunk.find("\n\n")
        if corte != -1:
            chunk = chunk[:corte]
        chunk = _solo_lineas_de_precio(chunk)
        kind = match.lastgroup
        numbers = _extract_numbers(chunk)
        if not numbers:
            continue

        if kind == "SL" and stop_loss is None:
            stop_loss = numbers[0]
        elif kind == "TP":
            take_profits.extend(numbers)
        elif kind == "ENTRY" and entry_low is None:
            entry_low = numbers[0]
            # Dos numbers en el chunk de entrada = rango ("2345-2347").
            entry_high = numbers[1] if len(numbers) > 1 else numbers[0]

    # Duplicados fuera, orden preservado (TP1 antes que TP2).
    take_profits = list(dict.fromkeys(take_profits))
    return entry_low, entry_high, stop_loss, take_profits


def _extract_numbers(text: str) -> list[float]:
    """Numeros de un fragmento, salteando los que llevan % o son parte de un ratio."""
    values: list[float] = []
    for match in _NUMBER_RE.finditer(text):
        after = text[match.end() : match.end() + 8]
        if re.match(r"\s*%", after):
            continue  # "50%" es una fraccion de cierre, no un precio
        # "80 PIPS", "2 LOTES", "24 HS": son cantidades, no niveles de precio.
        # Sin esto, un "+80 pips" al final de un "SL a BE" se convertia en el
        # stop loss nuevo, y el bot mandaba el SL de oro a 80.
        if re.match(r"\s*(?:PIPS?|LOTES?|HS?|HORAS?|DIAS?|MIN)\b", after):
            continue
        before = text[max(0, match.start() - 1) : match.start()]
        if before == ":" or re.match(r"\s*:", after):
            continue  # ratio tipo "1:3" o "R:R 1:2"
        values.append(_to_float(match.group(0)))
    return values


def _to_float(token: str) -> float:
    """Convierte '18,500' -> 18500.0, '2345,50' -> 2345.5, '1.2650' -> 1.265.

    La coma es ambigua: separador de miles en ingles, decimal en espanol.
    Se resuelve por forma: grupos exactos de 3 digitos = miles, si no = decimal.
    """
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", token):
        return float(token.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d+", token):
        return float(token.replace(",", ""))
    return float(token.replace(",", "."))


_LOOSE_RANGE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[-/]\s*(\d+(?:[.,]\d+)?)"
)


def _loose_entry(text: str, exclude: set[float | None]) -> tuple[float | None, float | None]:
    """Entrada sin etiqueta, como en "GOLD BUY 2345" o "SELL LIMIT 2345-2347".

    Se corta en la primera etiqueta de precio para no invadir el territorio
    del SL/TP. Si los dos primeros numeros vienen pegados por un guion o una
    barra, se interpretan como rango de entrada.
    """
    first_label = _LABEL_RE.search(text)
    head = text[: first_label.start()] if first_label else text

    range_match = _LOOSE_RANGE_RE.search(head)
    if range_match:
        low, high = _to_float(range_match.group(1)), _to_float(range_match.group(2))
        if low not in exclude and high not in exclude:
            return low, high

    for value in _extract_numbers(head):
        if value not in exclude:
            return value, value
    return None, None


def _extract_close_fraction(text: str) -> float | None:
    if _HALF_RE.search(text):
        return 0.5
    match = _PERCENT_RE.search(text)
    if match:
        percent = float(match.group(1))
        if 0 < percent <= 100:
            return percent / 100
    return None


# --------------------------------------------------------------------------
# Clasificacion
# --------------------------------------------------------------------------


def _classify(
    text: str,
    *,
    side: Side | None,
    stop_loss: float | None,
    take_profits: list[float],
    entry: float | None,
    close_fraction: float | None,
    warnings: list[str],
) -> EventType | None:
    """Decide que pide el mensaje. None = no es de trading, ignorar.

    El ORDEN de las reglas es lo unico que importa aca, y cada una esta donde
    esta por un caso concreto que rompia con el orden anterior.
    """
    # --- 0) Cronicas -----------------------------------------------------
    # Va primero de todo, incluso antes de la gestion, porque el problema que
    # resuelve es que la palabra de gestion ESTA presente pero narrando.
    # Caso real: "Hoy es un dia magico. Pudimos cerrar otra operacion" se
    # ejecutaba como una orden de cerrar TODAS las posiciones abiertas.
    if _NARRATIVA_RE.search(text):
        return None

    # Una senal "completa" es lado + al menos un precio de riesgo. Se calcula
    # primero porque casi todas las reglas de abajo la consultan.
    looks_like_new_signal = side is not None and (stop_loss is not None or take_profits)

    has_partial = bool(_sin_negar(_PARTIAL_RE, text))
    has_close = bool(_sin_negar(_CLOSE_RE, text))
    has_move_sl = bool(_sin_negar(_MOVE_SL_RE, text))
    has_move_tp = _pide_mover_tp_normalizado(text)

    # --- 1) Gestion pura -------------------------------------------------
    # Va primero, pero SOLO cuando el mensaje no trae una senal completa. Esa
    # condicion es la que separa "Move SL to BE, +80 pips" (gestion, sin lado)
    # de "GOLD SELL 2350, close below 2340 invalidates / SL 2360 / TP 2330"
    # (apertura que menciona la palabra close de pasada).
    if not looks_like_new_signal:
        if has_partial:
            if has_move_sl:
                warnings.append(
                    "El mensaje tambien pide mover el SL; se atiende el cierre parcial"
                )
            return EventType.PARTIAL_CLOSE
        if has_close:
            return EventType.CLOSE
        if has_move_sl:
            return EventType.MOVE_SL
        # Un "mover TP a 4450" explicito. Va despues del stop: si un mensaje
        # pide las dos cosas, el motor atiende el TP aparte (ver el despacho).
        if has_move_tp and take_profits:
            return EventType.MOVE_TP

    # --- 2) Recaps y resultados ------------------------------------------
    # Va DESPUES de la gestion y ANTES de la apertura. Un recap repite la
    # senal entera y, mirado solo como datos, es indistinguible de una senal
    # nueva: mismo lado, mismos precios, geometria valida. Lo unico que lo
    # delata es que el texto habla en pasado.
    #
    # Tuvo que quedar despues de la gestion porque los mensajes de gestion
    # legitimos tambien hablan de resultados: "TP1 hit, move SL to BE" o
    # "close half, +80 pips" son ordenes, no cronicas.
    #
    # Devuelve None (se ignora sin ruido) y no UNKNOWN: un canal activo postea
    # varios recaps por dia. Si sospechas que se traga senales de verdad,
    # `tct simular` muestra que hizo con cada mensaje del dia.
    if _RESULTADO_RE.search(text):
        return None

    # --- 3) Apertura -----------------------------------------------------
    if looks_like_new_signal:
        return EventType.OPEN

    # --- 4) Gestion con senal completa (raro, pero posible) --------------
    if has_partial:
        return EventType.PARTIAL_CLOSE
    if has_close:
        return EventType.CLOSE
    if has_move_sl:
        return EventType.MOVE_SL

    # Sin keywords de gestion pero con lado: apertura incompleta.
    if side is not None:
        if entry is None and stop_loss is None and not take_profits:
            warnings.append("Se detecto BUY/SELL pero ningun precio")
            return EventType.UNKNOWN
        return EventType.OPEN

    # Sin lado y sin gestion, pero con SL/TP nuevos: es una modificacion.
    if stop_loss is not None or take_profits:
        return EventType.UPDATE

    return None


def _sanity_warnings(
    side: Side | None,
    entry_low: float | None,
    entry_high: float | None,
    stop_loss: float | None,
    take_profits: list[float],
) -> list[str]:
    """Chequeos de coherencia geometrica de la senal.

    No bloquean nada aca (eso es tarea de risk.py), pero dejan constancia:
    un SL del lado equivocado suele ser un typo del grupo, y conviene verlo.
    """
    warnings: list[str] = []
    entry = entry_low if entry_high is None else (entry_low + entry_high) / 2 if entry_low is not None else None
    if entry is None or side is None:
        return warnings

    if stop_loss is not None:
        if side is Side.BUY and stop_loss >= entry:
            warnings.append(f"SL {stop_loss} por encima de la entrada {entry} en un BUY")
        if side is Side.SELL and stop_loss <= entry:
            warnings.append(f"SL {stop_loss} por debajo de la entrada {entry} en un SELL")

    for take_profit in take_profits:
        if side is Side.BUY and take_profit <= entry:
            warnings.append(f"TP {take_profit} por debajo de la entrada {entry} en un BUY")
        if side is Side.SELL and take_profit >= entry:
            warnings.append(f"TP {take_profit} por encima de la entrada {entry} en un SELL")

    return warnings
