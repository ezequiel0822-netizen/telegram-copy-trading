"""Modelos de dominio: que puede decir un mensaje del grupo de senales.

Un grupo de senales no manda solo "abri esto". Manda tambien "cerra la mitad",
"move SL to BE", "cancela la orden". Por eso el parser no devuelve un
`TradeSignal` a secas, devuelve un `SignalEvent` con un `EventType` que dice
QUE hay que hacer. El motor decide despues si eso se puede ejecutar o no.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class EventType(str, Enum):
    """Que pide el mensaje."""

    OPEN = "OPEN"                    # abrir una operacion nueva
    CLOSE = "CLOSE"                  # cerrar del todo
    PARTIAL_CLOSE = "PARTIAL_CLOSE"  # cerrar una fraccion (ej. "close 50%")
    MOVE_SL = "MOVE_SL"              # mover stop loss (incluye a breakeven)
    UPDATE = "UPDATE"                # modificar TPs / SL sin cerrar
    UNKNOWN = "UNKNOWN"              # parece senal pero no se entendio


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Como entrar.

    MARKET = ya, al precio que haya ("BUY NOW", "BUY @ market").
    LIMIT  = esperar a que el precio VUELVA al nivel (mejor precio que el actual).
    STOP   = esperar a que el precio ROMPA el nivel (peor precio que el actual).
    """

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


@dataclass(frozen=True)
class SignalEvent:
    """Resultado de parsear un mensaje.

    Todos los campos de precio son opcionales a proposito: un mensaje de
    "move SL to BE" no trae symbol ni entrada, y eso es valido. Es el motor
    (`risk.py`) el que decide si un evento tiene datos suficientes para actuar.
    """

    event_type: EventType
    symbol: str | None = None
    side: Side | None = None
    order_type: OrderType = OrderType.MARKET

    # Rango de entrada: los grupos suelen mandar "Entry 2345-2347".
    # Si es un precio unico, entry_low == entry_high.
    entry_low: float | None = None
    entry_high: float | None = None

    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)

    # Solo para PARTIAL_CLOSE: fraccion a cerrar, 0.0-1.0 (0.5 = mitad).
    close_fraction: float | None = None

    # Solo para MOVE_SL: si el mensaje dice "a breakeven" en vez de un precio.
    move_sl_to_breakeven: bool = False

    # Trazabilidad: sin esto no se puede auditar por que el bot hizo algo.
    raw_message: str = ""
    telegram_message_id: int | None = None
    telegram_chat_id: int | None = None
    is_edit: bool = False
    reply_to_message_id: int | None = None
    source: str = "text"  # "text" | "caption" | "ocr"

    # Notas del parser sobre lo que le resulto dudoso.
    warnings: list[str] = field(default_factory=list)

    @property
    def entry(self) -> float | None:
        """Precio de entrada unico. Si vino un rango, el punto medio.

        El punto medio es la convencion mas neutral: usar el extremo favorable
        infla el backtest, usar el desfavorable lo deprime.
        """
        if self.entry_low is None or self.entry_high is None:
            return self.entry_low if self.entry_high is None else self.entry_high
        return (self.entry_low + self.entry_high) / 2

    @property
    def has_entry_range(self) -> bool:
        return (
            self.entry_low is not None
            and self.entry_high is not None
            and self.entry_low != self.entry_high
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["side"] = self.side.value if self.side else None
        data["order_type"] = self.order_type.value
        data["entry"] = self.entry
        return data
