"""Repaso del canal: los mensajes de los ultimos N dias contra los precios reales.

POR QUE EXISTE
--------------
El 08/10 quiso subir el lote de 0.05 a 0.07-0.10 con 17 operaciones de
historia. Con tan pocas, el porcentaje de ganadas real del canal podia estar
en cualquier lado entre 50% y 90%, y el punto de equilibrio de este canal es
~61% (cada stop cuesta mas que un TP). Hacian falta mas operaciones, y las
habia: el historial del canal en Telegram y el de precios en MetaTrader.

COMO
----
No se reimplementan las reglas del bot: se usa el MISMO motor (`Engine`), con
un broker que en vez de mandar ordenes vive en el pasado. Cada mensaje entra
a la hora en que lo mando el canal; entre mensaje y mensaje el broker recorre
los ticks reales y cierra lo que toco su stop o su TP. Asi el filtro de
distancia, el TP1, el breakeven al precio de llenado, el "PARA LA POSICION",
los reintentos del stop: todo es lo que el bot hace de verdad.

Lo que NO puede saber: el texto ORIGINAL de cada mensaje. Telegram devuelve
la ultima version, y este canal edita. Si una senal quedo editada con el
resultado ("TP1 HIT"), se le sacan esas lineas y se vuelve a leer; se cuenta
aparte para que se sepa.

SOLO LEE. El broker de repaso no tiene ninguna conexion con MetaTrader mas
que la fuente de precios, que solo pide ticks del historial.
"""

from __future__ import annotations

import bisect
import itertools
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from tct.brokers.base import Broker, OrderResult
from tct.signals.models import OrderType, Side

logger = logging.getLogger(__name__)

HORA_MS = 3_600_000
# El mismo codigo que MT5 para "stop demasiado cerca del precio": el motor lo
# reconoce y lo reintenta cada 30 s, igual que en vivo.
STOPS_INVALIDOS = 10016
REINTENTO_MS = 30_000


def a_ms(fecha: datetime | str) -> int:
    if isinstance(fecha, str):
        fecha = datetime.fromisoformat(fecha)
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return int(fecha.timestamp() * 1000)


class FuenteDePrecios(Protocol):
    """Ticks (ms, bid, ask) ordenados, de `desde_ms` a `hasta_ms` inclusive."""

    def ticks(self, desde_ms: int, hasta_ms: int) -> list[tuple[int, float, float]]: ...


class PreciosDeMT5:
    """Ticks del historial de MetaTrader, de a una hora y con cache.

    Si el broker no tiene ticks de esa hora, se arman con las velas de 1
    minuto: apertura, el extremo mas cercano, el otro, cierre. Con velas no se
    sabe que extremo vino primero, asi que se cuenta cuantas horas salieron
    asi (`horas_con_velas`) para decirlo en el resultado.
    """

    def __init__(self, mt5: Any, simbolo: str, desfase_ms: int = 0) -> None:
        self._mt5 = mt5
        self.simbolo = simbolo
        # Los tiempos de MT5 son la hora del SERVIDOR contada como si fuera
        # UTC. Los de Telegram son UTC de verdad. `desfase_ms` es la
        # diferencia (servidor - UTC): se suma para pedir y se resta al leer.
        self.desfase_ms = desfase_ms
        self._cache: dict[int, list[tuple[int, float, float]]] = {}
        self.horas_con_ticks = 0
        self.horas_con_velas = 0
        self.horas_sin_precios = 0
        info = mt5.symbol_info(simbolo)
        self._punto = float(getattr(info, "point", 0.0) or 0.0)

    def ticks(self, desde_ms: int, hasta_ms: int) -> list[tuple[int, float, float]]:
        salida: list[tuple[int, float, float]] = []
        for hora in range(desde_ms // HORA_MS, hasta_ms // HORA_MS + 1):
            for tick in self._hora(hora):
                if desde_ms <= tick[0] <= hasta_ms:
                    salida.append(tick)
        return salida

    def _hora(self, hora: int) -> list[tuple[int, float, float]]:
        if hora not in self._cache:
            if len(self._cache) > 24:  # memoria acotada: lo viejo no se vuelve a pedir
                self._cache.pop(min(self._cache))
            self._cache[hora] = self._leer_hora(hora)
        return self._cache[hora]

    def _leer_hora(self, hora: int) -> list[tuple[int, float, float]]:
        mt5 = self._mt5
        desde = datetime.fromtimestamp((hora * HORA_MS + self.desfase_ms) / 1000, tz=timezone.utc)
        hasta = datetime.fromtimestamp(((hora + 1) * HORA_MS + self.desfase_ms) / 1000,
                                       tz=timezone.utc)
        crudos = None
        # La terminal baja el historial de ticks a pedido: la primera vez
        # puede contestar vacio. Un segundo intento, corto.
        for intento in range(2):
            try:
                crudos = mt5.copy_ticks_range(self.simbolo, desde, hasta,
                                              getattr(mt5, "COPY_TICKS_ALL", -1))
            except Exception:
                crudos = None
            if (crudos is not None and len(crudos)) or intento:
                break
            time.sleep(0.2)
        ticks = []
        if crudos is not None and len(crudos):
            for t in crudos:
                bid, ask = float(t["bid"]), float(t["ask"])
                if bid > 0 and ask > 0:
                    ticks.append((int(t["time_msc"]) - self.desfase_ms, bid, ask))
        if ticks:
            self.horas_con_ticks += 1
            return ticks

        try:
            velas = mt5.copy_rates_range(self.simbolo, getattr(mt5, "TIMEFRAME_M1", 1),
                                         desde, hasta)
        except Exception:
            velas = None
        if velas is None or not len(velas):
            self.horas_sin_precios += 1
            return []
        self.horas_con_velas += 1
        for v in velas:
            inicio = int(v["time"]) * 1000 - self.desfase_ms
            spread = float(v["spread"]) * self._punto
            apertura, cierre = float(v["open"]), float(v["close"])
            alto, bajo = float(v["high"]), float(v["low"])
            # El extremo mas cercano a la apertura, primero.
            orden = ([bajo, alto] if apertura - bajo <= alto - apertura else [alto, bajo])
            for i, precio in enumerate([apertura, *orden, cierre]):
                ticks.append((inicio + i * 15_000, precio, precio + spread))
        return ticks


def desfase_del_servidor(mt5: Any, simbolo: str, eventos: list[dict[str, Any]],
                         ahora_s: float) -> tuple[int, str]:
    """Cuanto adelanta el reloj del servidor de MT5 respecto de UTC, en ms.

    Equivocarse aca corre TODO el repaso unas horas: cada senal se mediria
    contra el precio de otro momento. Por eso se mide con algo conocido: una
    operacion del propio bot, cuya hora UTC esta en el registro y cuya hora de
    servidor esta en el historial de MT5. Si no hay ninguna, el ultimo tick
    (solo sirve con el mercado abierto).
    """
    from tct.informe import tickets_operados

    for operada in reversed(tickets_operados(eventos)):
        if not operada.get("ticket") or not operada.get("ts"):
            continue
        try:
            deals = mt5.history_deals_get(position=operada["ticket"])
        except Exception:
            deals = None
        entrada = next((d for d in deals or []
                        if getattr(d, "entry", None) == getattr(mt5, "DEAL_ENTRY_IN", 0)), None)
        if entrada is None:
            continue
        horas = round((int(entrada.time) - a_ms(operada["ts"]) / 1000) / 3600)
        return horas * HORA_MS, f"UTC{horas:+d} (medido con una operacion del bot)"

    tick = mt5.symbol_info_tick(simbolo)
    diferencia = (int(getattr(tick, "time", 0) or 0) - ahora_s) / 3600 if tick else 99
    if abs(diferencia) <= 14:
        horas = round(diferencia)
        return horas * HORA_MS, f"UTC{horas:+d} (medido con el ultimo precio)"
    return 0, "desconocida: se toma UTC+0 y las horas pueden estar corridas"


@dataclass
class _Posicion:
    ticket: int
    simbolo: str
    lado: Side
    lote: float
    entrada: float
    sl: float | None
    tp: float | None
    abierta_ms: int
    cursor_ms: int
    resultado: float = 0.0  # lo ya cerrado (parciales), en la moneda de la cuenta
    cerrada: dict[str, Any] | None = None


@dataclass
class BrokerDeRepaso(Broker):
    """Un MetaTrader en el pasado: abre al precio de ese momento y recorre ticks."""

    precios: dict[str, FuenteDePrecios]
    usd_por_punto_y_lote: dict[str, float]
    ahora_ms: int = 0
    name: str = "repaso"
    posiciones: dict[int, _Posicion] = field(default_factory=dict)
    _tickets: Any = field(default_factory=lambda: itertools.count(1))

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def is_ready(self) -> bool:
        return True

    # -- El paso del tiempo -------------------------------------------------

    def avanzar(self, hasta_ms: int) -> None:
        """Cierra, tick por tick, lo que toco su stop o su TP hasta `hasta_ms`."""
        for pos in self.posiciones.values():
            if pos.cerrada is not None or pos.cursor_ms >= hasta_ms:
                continue
            for t, bid, ask in self.precios[pos.simbolo].ticks(pos.cursor_ms + 1, hasta_ms):
                # Un BUY se cierra con el bid; un SELL, con el ask.
                if pos.lado is Side.BUY:
                    if pos.sl is not None and bid <= pos.sl:
                        self._cerrar(pos, bid, "sl", t)
                    elif pos.tp is not None and bid >= pos.tp:
                        self._cerrar(pos, bid, "tp", t)
                else:
                    if pos.sl is not None and ask >= pos.sl:
                        self._cerrar(pos, ask, "sl", t)
                    elif pos.tp is not None and ask <= pos.tp:
                        self._cerrar(pos, ask, "tp", t)
                if pos.cerrada is not None:
                    break
            pos.cursor_ms = hasta_ms
        self.ahora_ms = max(self.ahora_ms, hasta_ms)

    def _cotizacion(self, simbolo: str) -> tuple[float, float] | None:
        """El ultimo tick hasta `ahora_ms` (se mira hasta 10 minutos atras)."""
        fuente = self.precios.get(simbolo)
        if fuente is None:
            return None
        ticks = fuente.ticks(self.ahora_ms - 600_000, self.ahora_ms)
        if not ticks:
            return None
        i = bisect.bisect_right([t[0] for t in ticks], self.ahora_ms) - 1
        return (ticks[i][1], ticks[i][2]) if i >= 0 else None

    def _ganancia(self, pos: _Posicion, precio: float, lote: float) -> float:
        sentido = 1.0 if pos.lado is Side.BUY else -1.0
        return sentido * (precio - pos.entrada) * lote * self.usd_por_punto_y_lote[pos.simbolo]

    def _cerrar(self, pos: _Posicion, precio: float, motivo: str, t: int) -> None:
        pos.resultado += self._ganancia(pos, precio, pos.lote)
        pos.cerrada = {"precio": precio, "motivo": motivo, "cerrada_ms": t}

    # -- Lo que el motor le pide ------------------------------------------

    async def market_price(self, symbol: str) -> float | None:
        cot = self._cotizacion(symbol)
        return (cot[0] + cot[1]) / 2 if cot else None

    async def open_order(self, *, symbol: str, side: Side, order_type: OrderType, lot: float,
                         entry: float | None, stop_loss: float | None,
                         take_profit: float | None) -> OrderResult:
        if order_type is not OrderType.MARKET:
            return OrderResult(False, "open", "El repaso no simula pendientes", symbol=symbol)
        cot = self._cotizacion(symbol)
        if cot is None:
            return OrderResult(False, "open", "Sin precios de ese momento", symbol=symbol)
        bid, ask = cot
        entrada = ask if side is Side.BUY else bid
        ticket = next(self._tickets)
        self.posiciones[ticket] = _Posicion(ticket, symbol, side, lot, entrada, stop_loss,
                                            take_profit, self.ahora_ms, self.ahora_ms)
        return OrderResult(True, "open", "orden ejecutada", ticket=ticket, price=entrada,
                           lot=lot, symbol=symbol)

    def _viva(self, ticket: int | None, accion: str, symbol: str):
        pos = self.posiciones.get(ticket or -1)
        if pos is None or pos.cerrada is not None:
            return None, OrderResult(False, accion, "La posicion ya no existe",
                                     ticket=ticket, symbol=symbol, raw={"ausente": True})
        return pos, None

    async def close_position(self, *, ticket: int | None, symbol: str,
                             fraction: float = 1.0) -> OrderResult:
        pos, falla = self._viva(ticket, "close", symbol)
        if falla:
            return falla
        bid, ask = self._cotizacion(pos.simbolo) or (pos.entrada, pos.entrada)
        precio = bid if pos.lado is Side.BUY else ask
        if fraction >= 1.0:
            self._cerrar(pos, precio, "canal", self.ahora_ms)
            return OrderResult(True, "close", "cerrada", ticket=ticket, price=precio,
                               symbol=symbol)
        parte = round(pos.lote * fraction, 2)
        pos.resultado += self._ganancia(pos, precio, parte)
        pos.lote = round(pos.lote - parte, 2)
        return OrderResult(True, "partial_close", "parcial", ticket=ticket, price=precio,
                           lot=parte, symbol=symbol, raw={"restante": pos.lote})

    async def modify_stop_loss(self, *, ticket: int | None, symbol: str,
                               stop_loss: float) -> OrderResult:
        pos, falla = self._viva(ticket, "modify_sl", symbol)
        if falla:
            return falla
        bid, ask = self._cotizacion(pos.simbolo) or (0.0, 0.0)
        invalido = stop_loss >= bid if pos.lado is Side.BUY else stop_loss <= ask
        if invalido:
            return OrderResult(False, "modify_sl", "Invalid stops", ticket=ticket,
                               symbol=symbol, raw={"retcode": STOPS_INVALIDOS})
        pos.sl = stop_loss
        return OrderResult(True, "modify_sl", "SL modificado", ticket=ticket,
                           price=stop_loss, symbol=symbol)

    async def modify_take_profit(self, *, ticket: int | None, symbol: str,
                                 take_profit: float) -> OrderResult:
        pos, falla = self._viva(ticket, "modify_tp", symbol)
        if falla:
            return falla
        bid, ask = self._cotizacion(pos.simbolo) or (0.0, 0.0)
        invalido = take_profit <= bid if pos.lado is Side.BUY else take_profit >= ask
        if invalido:
            return OrderResult(False, "modify_tp", "Invalid stops", ticket=ticket,
                               symbol=symbol, raw={"retcode": STOPS_INVALIDOS})
        pos.tp = take_profit
        return OrderResult(True, "modify_tp", "TP modificado", ticket=ticket,
                           price=take_profit, symbol=symbol)

    async def posicion_existe(self, ticket: int | None) -> bool | None:
        pos = self.posiciones.get(ticket or -1)
        return pos is not None and pos.cerrada is None


# --------------------------------------------------------------------------
# El recorrido
# --------------------------------------------------------------------------


def limpiar_resultado(texto: str) -> str | None:
    """La senal sin las lineas que el canal le agrego despues ("TP1 HIT").

    None si no habia nada que sacar. Solo se usa con mensajes EDITADOS que
    hoy no se leen como nada: es la forma de recuperar la senal original.
    """
    from tct.signals.parser import _NARRATIVA_RE, _RESULTADO_RE, _normalize

    lineas = texto.splitlines()
    quedan = [ln for ln in lineas
              if not (_RESULTADO_RE.search(_normalize(ln)) or _NARRATIVA_RE.search(_normalize(ln)))]
    return "\n".join(quedan) if len(quedan) != len(lineas) else None


async def repasar(engine: Any, broker: BrokerDeRepaso,
                  mensajes: list[tuple[str, dict[str, Any]]], fin_ms: int) -> list[dict[str, Any]]:
    """Pasa los mensajes por el motor en su hora; devuelve una fila por posicion."""
    from tct.signals.models import EventType
    from tct.signals.parser import parse_signal

    filas: list[dict[str, Any]] = []
    for texto, meta in mensajes:
        t = a_ms(meta["date"])
        await _llegar_a(engine, broker, t)

        reconstruida = False
        if meta.get("editado") and parse_signal(texto) is None:
            limpio = limpiar_resultado(texto)
            if limpio and (ev := parse_signal(limpio)) and ev.event_type is EventType.OPEN:
                texto, reconstruida = limpio, True

        antes = set(broker.posiciones)
        resultado = await engine.handle_message(texto, {**meta, "reproduccion": True})
        senal = parse_signal(texto)
        nuevas = sorted(set(broker.posiciones) - antes)
        for ticket in nuevas:
            filas.append({"ticket": ticket, "fecha_ms": t, "posicion": broker.posiciones[ticket],
                          "senal": senal, "reconstruida": reconstruida})
        # Una apertura que no abrio: por que (el filtro de distancia, sin SL...).
        if not nuevas and senal is not None and senal.event_type is EventType.OPEN:
            motivos = resultado.get("reasons") or [resultado.get("status", "?")]
            filas.append({"ticket": None, "fecha_ms": t, "senal": senal,
                          "rechazo": motivos, "reconstruida": reconstruida})

    await _llegar_a(engine, broker, fin_ms)
    return filas


async def _llegar_a(engine: Any, broker: BrokerDeRepaso, t: int) -> None:
    """Avanza el tiempo hasta `t`, reintentando cada 30 s los stops rechazados."""
    while getattr(engine, "_sl_pendientes", None) and broker.ahora_ms + REINTENTO_MS < t:
        broker.avanzar(broker.ahora_ms + REINTENTO_MS)
        await engine._reintentar_stops()
    broker.avanzar(t)
    broker.ahora_ms = t


def resumir(filas: list[dict[str, Any]], lote: float, lotes: list[float],
            contrato: float = 100.0) -> dict[str, Any]:
    """Ganadas, el punto de equilibrio, la peor racha y la peor caida, por lote."""
    cerradas = [f for f in filas if f.get("posicion") is not None
                and f["posicion"].cerrada is not None]
    cerradas.sort(key=lambda f: f["posicion"].cerrada["cerrada_ms"])
    abiertas = [f for f in filas if f.get("posicion") is not None
                and f["posicion"].cerrada is None]
    rechazadas = [f for f in filas if f.get("rechazo") is not None]

    resultados = [f["posicion"].resultado for f in cerradas]
    # Breakeven: menos de medio punto, que es lo que mueve el spread.
    umbral = 0.5 * lote * contrato
    ganadas = [r for r in resultados if r > umbral]
    perdidas = [r for r in resultados if r < -umbral]

    racha = peor_racha = 0
    for r in resultados:
        if r < -umbral:
            racha += 1
            peor_racha = max(peor_racha, racha)
        elif r > umbral:
            racha = 0

    acumulado = pico = caida = 0.0
    for r in resultados:
        acumulado += r
        pico = max(pico, acumulado)
        caida = max(caida, pico - acumulado)

    promedio_ganada = sum(ganadas) / len(ganadas) if ganadas else 0.0
    promedio_perdida = -sum(perdidas) / len(perdidas) if perdidas else 0.0
    decididas = len(ganadas) + len(perdidas)
    return {
        "cerradas": len(cerradas),
        "abiertas": len(abiertas),
        "rechazadas": len(rechazadas),
        "ganadas": len(ganadas),
        "perdidas": len(perdidas),
        "breakeven": len(resultados) - len(ganadas) - len(perdidas),
        "pct_ganadas": len(ganadas) / decididas * 100 if decididas else 0.0,
        "pct_equilibrio": (promedio_perdida / (promedio_ganada + promedio_perdida) * 100
                           if ganadas and perdidas else None),
        "promedio_ganada": promedio_ganada,
        "promedio_perdida": promedio_perdida,
        "total": sum(resultados),
        "peor_racha": peor_racha,
        "reconstruidas": sum(1 for f in filas if f.get("reconstruida")),
        "por_lote": [{"lote": x, "total": sum(resultados) * x / lote, "peor_caida": caida * x / lote}
                     for x in lotes],
    }
