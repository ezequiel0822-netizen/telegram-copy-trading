"""Capas de seguridad: que senales pueden pasar y cuales no.

El CONTEXTO MAESTRO pide que las protecciones sean "configurables, visibles y
faciles de cambiar". Por eso viven todas en este archivo, cada una devuelve un
motivo en castellano, y ninguna esta escondida dentro del ejecutor de ordenes.

Ninguna regla de aca lanza excepciones: devuelven un `RiskDecision`. Rechazar
una senal es un resultado normal del sistema, no un error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tct.config import Settings
from tct.signals.models import EventType, SignalEvent, Side
from tct.store import Store


@dataclass(frozen=True)
class RiskDecision:
    ok: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"


def evaluate_open(settings: Settings, store: Store, event: SignalEvent) -> RiskDecision:
    """Decide si una senal de apertura puede ejecutarse."""
    reasons: list[str] = []

    if event.event_type is not EventType.OPEN:
        return RiskDecision(False, [f"No es una senal de apertura ({event.event_type.value})"])

    # --- Datos minimos ---------------------------------------------------
    if not event.symbol:
        reasons.append("No se pudo identificar el simbolo")
    if event.side is None:
        reasons.append("No se pudo identificar la direccion (BUY/SELL)")
    if settings.require_stop_loss and event.stop_loss is None:
        reasons.append("Falta stop loss (REQUIRE_STOP_LOSS=true)")
    if settings.require_take_profit and not event.take_profits:
        reasons.append("Falta take profit (REQUIRE_TAKE_PROFIT=true)")

    # Sin simbolo o sin lado no tiene sentido seguir evaluando.
    if reasons:
        return RiskDecision(False, reasons)

    # --- Lista blanca ----------------------------------------------------
    symbol = (event.symbol or "").upper()
    if symbol not in settings.allowed_symbols:
        reasons.append(f"Simbolo {symbol} fuera de ALLOWED_SYMBOLS")

    # --- Tamano ----------------------------------------------------------
    if settings.default_lot > settings.max_lot:
        reasons.append(f"DEFAULT_LOT {settings.default_lot} supera MAX_LOT {settings.max_lot}")

    # --- Coherencia geometrica -------------------------------------------
    # Un SL del lado equivocado no es una senal conservadora: es una senal
    # rota. Ejecutarla abriria una posicion que se cierra al instante.
    reasons.extend(_geometry_reasons(event))

    # --- Exposicion ------------------------------------------------------
    open_count = len(store.open_positions())
    if open_count >= settings.max_open_trades:
        reasons.append(
            f"Ya hay {open_count} operaciones abiertas (MAX_OPEN_TRADES={settings.max_open_trades})"
        )

    if store.find_positions(symbol):
        reasons.append(f"Ya hay una posicion abierta en {symbol}")

    # --- Cupo diario -----------------------------------------------------
    used = store.signals_today()
    if used >= settings.max_signals_per_day:
        reasons.append(
            f"Cupo diario agotado: {used}/{settings.max_signals_per_day} (MAX_SIGNALS_PER_DAY)"
        )

    return RiskDecision(not reasons, reasons)


def _geometry_reasons(event: SignalEvent) -> list[str]:
    """Verifica que SL y TP esten del lado correcto de la entrada."""
    reasons: list[str] = []
    entry = event.entry
    if entry is None or event.side is None:
        return reasons

    if entry <= 0:
        return [f"Entrada invalida: {entry}"]

    stop_loss = event.stop_loss
    if stop_loss is not None:
        if stop_loss <= 0:
            reasons.append(f"Stop loss invalido: {stop_loss}")
        elif event.side is Side.BUY and stop_loss >= entry:
            reasons.append(f"BUY con SL {stop_loss} por encima de la entrada {entry}")
        elif event.side is Side.SELL and stop_loss <= entry:
            reasons.append(f"SELL con SL {stop_loss} por debajo de la entrada {entry}")

    # Alcanza con que UN take profit sea coherente: los grupos suelen mandar
    # TP1/TP2/TP3 y a veces el ultimo viene con un typo. Se ejecuta con los
    # validos y se descarta el resto en `usable_take_profits()`.
    if event.take_profits and not usable_take_profits(event):
        reasons.append(
            f"Ningun take profit del lado correcto para un {event.side.value} desde {entry}"
        )

    return reasons


def usable_take_profits(event: SignalEvent) -> list[float]:
    """Los TPs que estan del lado correcto de la entrada."""
    entry = event.entry
    if entry is None or event.side is None:
        return list(event.take_profits)
    if event.side is Side.BUY:
        return [tp for tp in event.take_profits if tp > entry]
    return [tp for tp in event.take_profits if tp < entry]


def evaluate_management(
    settings: Settings, store: Store, event: SignalEvent
) -> tuple[RiskDecision, list]:
    """Decide si un evento de gestion (cierre, parcial, mover SL) puede ejecutarse.

    Devuelve la decision y las posiciones a las que aplica. Un mensaje de
    gestion sin simbolo ("close all") aplica a todo lo abierto; con simbolo,
    solo a ese instrumento.
    """
    targets = store.find_positions(event.symbol)

    if not targets:
        detail = f" en {event.symbol}" if event.symbol else ""
        return RiskDecision(False, [f"No hay posiciones abiertas{detail}"]), []

    if event.event_type is EventType.PARTIAL_CLOSE:
        fraction = event.close_fraction
        if fraction is None or not (0 < fraction < 1):
            return RiskDecision(False, [f"Fraccion de cierre invalida: {fraction}"]), targets

    if event.event_type is EventType.MOVE_SL:
        if event.stop_loss is None and not event.move_sl_to_breakeven:
            return RiskDecision(False, ["MOVE_SL sin precio ni breakeven"]), targets
        # Mover el SL a breakeven en una posicion sin entrada registrada no
        # tiene a donde apuntar.
        if event.move_sl_to_breakeven and all(p.entry is None for p in targets):
            return RiskDecision(False, ["No hay precio de entrada para calcular el breakeven"]), targets

    return RiskDecision(True), targets
