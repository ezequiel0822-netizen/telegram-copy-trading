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
# El `\d?(?![\d.,])` del indice de TP es deliberado y fragil de tocar: separa
# "TP1 2355" (el 1 es el numero de target) de "TP 1.2700" y "TP 2330" (donde
# ese digito es el precio). Solo se traga UN digito, y solo si despues no
# sigue otro digito ni un separador decimal.
_LABEL_RE = re.compile(
    r"(?P<TP>\b(?:TAKE\s*PROFITS?|TARGETS?|OBJETIVOS?|TPS?|T/P)\s*\d?(?![\d.,]))"
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
_ORDER_TYPE_RE = re.compile(
    r"\b(?:BUY|SELL|LONG|SHORT)\s+(LIMIT|STOP|NOW|MARKET)\b"
    r"|\b(LIMIT|STOP)\s+(?:ORDER)?\b(?=.*\b(?:BUY|SELL)\b)"
)

_PARTIAL_RE = re.compile(
    r"\b(?:CLOSE|CLOSING|CIERRE|CIERREN|CERRAR|TAKE|TOMAR|SECURE)\b[^\n]{0,25}?"
    r"\b(?:HALF|MITAD|PARTIALS?|PARCIALES?|PARCIAL|\d{1,3}\s*%)"
    r"|\b(?:PARTIALS?|PARCIALES?|PARCIAL)\b"
    r"|\bCLOSE\s+\d{1,3}\s*%"
)
_CLOSE_RE = re.compile(
    r"\b(?:CLOSE|CLOSED|CIERRE|CIERREN|CERRAR|EXIT|SALIR|CANCEL|CANCELAR)\b"
)
_MOVE_SL_RE = re.compile(
    r"\b(?:MOVE|MOVER|SET|PON|PONER|BRING|SUBIR|BAJAR|TRAIL)\b[^\n]{0,30}?\b(?:SL|STOP)\b"
    r"|\b(?:SL|STOP\s*LOSS)\b[^\n]{0,20}?\b(?:TO\s+)?(?:BE|B/E|BREAK\s*EVEN|BREAKEVEN|ENTRY|ENTRADA)\b"
    r"|\b(?:BREAK\s*EVEN|BREAKEVEN)\b"
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
)

_BREAKEVEN_RE = re.compile(r"\b(?:BE|B/E|BREAK\s*EVEN|BREAKEVEN)\b")
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

    # --- Paso 2: extraer datos duros --------------------------------------
    order_type, masked = _extract_order_type(text)
    symbol = _extract_symbol(masked)
    side = _extract_side(masked)

    # Los precios se buscan sobre el texto SIN los nombres de instrumento: si
    # no, el "30" de US30 se lee como un precio. Ver `_mask_symbols`.
    sin_simbolos = _mask_symbols(masked)
    entry_low, entry_high, stop_loss, take_profits = _extract_prices(sin_simbolos)

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

    # Normalizaciones finales por tipo de evento.
    if event_type is EventType.PARTIAL_CLOSE and close_fraction is None:
        close_fraction = 0.5
        warnings.append("Cierre parcial sin porcentaje explicito; se asume 50%")

    move_to_be = False
    if event_type is EventType.MOVE_SL:
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
        raw_message=message,
        telegram_message_id=message_id,
        telegram_chat_id=chat_id,
        is_edit=is_edit,
        reply_to_message_id=reply_to_message_id,
        source=source,
        warnings=warnings,
    )


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


def _extract_side(text: str) -> Side | None:
    match = _SIDE_RE.search(text)
    if not match:
        return None
    token = match.group(1)
    return Side.SELL if token in {"SELL", "SHORT", "VENTA"} else Side.BUY


# --------------------------------------------------------------------------
# Precios
# --------------------------------------------------------------------------


def _extract_prices(text: str) -> tuple[float | None, float | None, float | None, list[float]]:
    """Reparte los numeros del mensaje entre entrada, SL y TPs.

    Cada etiqueta se queda con el texto hasta la etiqueta siguiente.
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
    # Una senal "completa" es lado + al menos un precio de riesgo. Se calcula
    # primero porque casi todas las reglas de abajo la consultan.
    looks_like_new_signal = side is not None and (stop_loss is not None or take_profits)

    has_partial = bool(_PARTIAL_RE.search(text))
    has_close = bool(_CLOSE_RE.search(text))
    has_move_sl = bool(_MOVE_SL_RE.search(text))

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
