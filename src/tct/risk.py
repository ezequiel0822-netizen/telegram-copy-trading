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
from tct.signals.models import EventType, OrderType, SignalEvent, Side
from tct.store import Store


@dataclass(frozen=True)
class RiskDecision:
    ok: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"


def evaluate_open(
    settings: Settings,
    store: Store,
    event: SignalEvent,
    market_price: float | None = None,
) -> RiskDecision:
    """Decide si una senal de apertura puede ejecutarse.

    `market_price` es el precio real del instrumento AHORA, o None si no se
    pudo leer. Lo trae el motor porque pedirlo es una llamada al broker y esta
    funcion es sincrona y pura a proposito: se puede probar entera sin red.
    """
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

    # --- Contraste con el precio real ------------------------------------
    # La unica validacion que mira afuera del mensaje. Todas las anteriores
    # comparan el mensaje contra si mismo y por eso no distinguen un precio
    # coherente de uno correcto.
    reasons.extend(_market_distance_reasons(settings, event, market_price))

    # --- Exposicion ------------------------------------------------------
    open_count = len(store.open_positions())
    if open_count >= settings.max_open_trades:
        reasons.append(
            f"Ya hay {open_count} operaciones abiertas (MAX_OPEN_TRADES={settings.max_open_trades})"
        )

    if store.find_positions(symbol):
        reasons.append(f"Ya hay una posicion abierta en {symbol}")

    # --- Tope de perdida diaria ------------------------------------------
    # Se evalua contra el balance con el que abrio el dia. Es la proteccion
    # que mas importa con dinero real: un dia malo se corta solo en vez de
    # seguir tomando cada senal que llegue.
    reasons.extend(_daily_loss_reasons(settings, store))

    # --- Cupo diario -----------------------------------------------------
    used = store.signals_today()
    if used >= settings.max_signals_per_day:
        reasons.append(
            f"Cupo diario agotado: {used}/{settings.max_signals_per_day} (MAX_SIGNALS_PER_DAY)"
        )

    return RiskDecision(not reasons, reasons)


def _daily_loss_reasons(settings: Settings, store: Store) -> list[str]:
    """Frena si la perdida del dia supera MAX_DAILY_LOSS_PCT.

    Devuelve lista vacia si el tope esta apagado (0) o si todavia no se pudo
    leer el balance: sin dato no se inventa un motivo de rechazo.
    """
    if settings.max_daily_loss_pct <= 0:
        return []

    inicial = store.state.day_start_balance
    actual = getattr(store, "balance_actual", None)
    if not inicial or actual is None:
        return []

    caida_pct = (inicial - actual) / inicial * 100
    if caida_pct >= settings.max_daily_loss_pct:
        return [
            f"Tope de perdida diaria alcanzado: -{caida_pct:.1f}% "
            f"(limite {settings.max_daily_loss_pct}%). Se reanuda manana."
        ]
    return []


def _market_distance_reasons(
    settings: Settings, event: SignalEvent, market_price: float | None
) -> list[str]:
    """Rechaza una entrada que no se parece al precio real del instrumento.

    Es la red que ataja una clase entera de errores de lectura que todas las
    demas validaciones dejan pasar, porque el mensaje mal leido queda
    internamente coherente:

    - Simbolo equivocado: "mientras el gold descansa, BTC BUY 65000" leido
      como oro. La geometria cierra perfecto; el precio esta 15 veces afuera.
    - Escala cambiada: "DAX SELL 18.500" leido como 18.5. Los tres numeros
      escalan juntos, asi que SL y TP siguen del lado correcto.
    - Digitos comidos: "US30 SELL 39,500" leido como entrada 30.
    - Mensaje viejo: un recap con los precios de la semana pasada.

    Con una orden A MERCADO el dano ademas es concreto y no teorico: la orden
    entra al precio de AHORA pero el SL y el TP son los del mensaje. Una
    entrada leida 2345 con el oro en 4438 no abre la posicion a un precio
    malo: abre una posicion con el stop a dos mil puntos.

    Devuelve lista vacia si no hay precio (sin dato no se inventa un motivo de
    rechazo, misma politica que el freno diario) o si el control esta en 0.
    """
    if market_price is None or market_price <= 0:
        return []

    distancia = distancia_al_mercado(event, market_price)
    if distancia is None:
        return []

    # Una pendiente se pone lejos del mercado a proposito: esperar a que el
    # precio vuelva (LIMIT) o que rompa (STOP) es su razon de ser. Medirla con
    # la tolerancia de una orden a mercado rechazaria senales buenas.
    if event.order_type is OrderType.MARKET:
        limite, llave = settings.max_spread_from_entry_pct, "MAX_SPREAD_FROM_ENTRY_PCT"
    else:
        limite, llave = settings.max_pending_distance_pct, "MAX_PENDING_DISTANCE_PCT"

    if limite <= 0 or distancia <= limite:
        return []

    return [
        f"La entrada {_num(event.entry)} esta a {distancia:.1f}% del precio real de "
        f"{event.symbol} ({_num(market_price)}), y el limite es {limite}% ({llave}). "
        "Casi siempre es un simbolo mal leido, un mensaje viejo o un precio con la "
        f"escala cambiada. Si el precio del mensaje estaba bien, subi {llave} en el .env."
    ]


def distancia_al_mercado(event: SignalEvent, market_price: float) -> float | None:
    """Cuanto se aleja la entrada del precio real, en porcentaje.

    Publica porque `tct simular --con-precios` la usa para mostrar la misma
    cuenta que hace el filtro sin ejecutar nada. Calibrar el numero mirando
    otra formula seria calibrarlo contra algo que despues no se aplica.

    Con un rango ("Entry 2345-2347") se mide contra el borde mas cercano, y un
    mercado adentro del rango da 0: el rango es una banda de precios que el
    grupo declaro validos, no un punto.
    """
    entry = event.entry
    if entry is None or entry <= 0:
        return None

    low = event.entry_low if event.entry_low is not None else entry
    high = event.entry_high if event.entry_high is not None else entry
    if low > high:
        low, high = high, low

    if low <= market_price <= high:
        return 0.0

    borde = low if market_price < low else high
    return abs(borde - market_price) / market_price * 100


# Cuanto puede alejarse un stop del precio real antes de dar por hecho que el
# numero esta mal leido. Es un FACTOR, no un porcentaje, y es enorme a
# proposito.
#
# Un stop se pone lejos del mercado por definicion, y cuanto es "lejos" depende
# del instrumento, de la estrategia y del dia: medirlo con la tolerancia de una
# entrada rechazaria stops perfectamente sanos. Lo que NO depende de nada es la
# ESCALA. Ningun stop legitimo vale el doble ni la mitad que el instrumento que
# protege. Un 444 con el oro en 4438 (un digito comido) o un 4430 aplicado a
# EURUSD en 1.08 (el numero de otro instrumento) quedan afuera por varios
# ordenes de magnitud, y son justamente los dos errores que se buscan.
#
# No es configurable a proposito: no es una politica de riesgo que alguien
# quiera ajustar, es verificar que el numero pertenezca a este mercado.
FACTOR_ESCALA_STOP = 2.0


def stop_fuera_de_escala(
    stop_loss: float | None, market_price: float | None
) -> str | None:
    """Motivo por el que un stop no puede ser de este instrumento, o None.

    Sin precio no opina, igual que todo lo demas que mira afuera: sin dato no
    se inventa un motivo de rechazo.

    Esto NO reemplaza la validacion del broker. MT5 ya rechaza un stop del lado
    equivocado del mercado, que es la mitad de los desastres posibles. La otra
    mitad, un stop del lado correcto pero absurdamente lejos, MT5 la ACEPTA sin
    chistar: la posicion queda sin proteccion real y nadie se entera.
    """
    if stop_loss is None or market_price is None or market_price <= 0:
        return None
    if stop_loss <= 0:
        return f"stop invalido ({_num(stop_loss)})"

    if stop_loss > market_price * FACTOR_ESCALA_STOP:
        return (
            f"{_num(stop_loss)} es mas del doble del precio real "
            f"({_num(market_price)}), no puede ser un stop de este instrumento"
        )
    if stop_loss < market_price / FACTOR_ESCALA_STOP:
        return (
            f"{_num(stop_loss)} es menos de la mitad del precio real "
            f"({_num(market_price)}), no puede ser un stop de este instrumento"
        )
    return None


def _num(valor: float | None) -> str:
    """Precio legible: 4438.5 y no 4438.500000000001; 1.0855 y no 1.09."""
    if valor is None:
        return "?"
    return f"{valor:.5f}".rstrip("0").rstrip(".")


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
