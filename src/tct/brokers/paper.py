"""Broker simulado: acepta todo y no manda nada a ningun lado.

Es el broker por defecto y el unico que funciona igual en macOS, Windows y
Linux sin dependencias externas. Sirve para dos cosas:

1. Modo PAPER_ONLY, que es donde arranca el sistema.
2. Los tests: todo el motor se puede ejercitar de punta a punta sin red.

Los tickets son un contador propio, no de ningun broker. Empiezan alto para
que sea evidente de un vistazo que son sinteticos.
"""

from __future__ import annotations

import itertools
from typing import Any

from tct.brokers.base import Broker, OrderResult
from tct.signals.models import OrderType, Side


class PaperBroker(Broker):
    name = "paper"

    def __init__(self) -> None:
        self._tickets = itertools.count(900_000_001)
        self._positions: dict[int, dict[str, Any]] = {}

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def is_ready(self) -> bool:
        return True

    async def open_order(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        lot: float,
        entry: float | None,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> OrderResult:
        ticket = next(self._tickets)
        self._positions[ticket] = {
            "symbol": symbol,
            "side": side.value,
            "lot": lot,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "order_type": order_type.value,
        }
        return OrderResult(
            ok=True,
            action="open",
            reason="simulado (PAPER_ONLY, no se envio a ningun broker)",
            ticket=ticket,
            price=entry,
            lot=lot,
            symbol=symbol,
            raw={"simulated": True, "order_type": order_type.value},
        )

    async def close_position(
        self, *, ticket: int | None, symbol: str, fraction: float = 1.0
    ) -> OrderResult:
        position = self._positions.get(ticket) if ticket else None
        if ticket is not None and position is None:
            return OrderResult(
                ok=False, action="close", reason=f"Ticket simulado {ticket} inexistente", symbol=symbol
            )

        closed_lot = round((position or {}).get("lot", 0.0) * fraction, 4) if position else None
        if position is not None:
            if fraction >= 1.0:
                self._positions.pop(ticket, None)
            else:
                position["lot"] = round(position["lot"] * (1 - fraction), 4)

        return OrderResult(
            ok=True,
            action="close" if fraction >= 1.0 else "partial_close",
            reason=f"simulado (fraccion {fraction:.0%})",
            ticket=ticket,
            lot=closed_lot,
            symbol=symbol,
            raw={"simulated": True, "fraction": fraction},
        )

    async def modify_stop_loss(
        self, *, ticket: int | None, symbol: str, stop_loss: float
    ) -> OrderResult:
        position = self._positions.get(ticket) if ticket else None
        if ticket is not None and position is None:
            return OrderResult(
                ok=False, action="modify_sl", reason=f"Ticket simulado {ticket} inexistente", symbol=symbol
            )
        if position is not None:
            position["stop_loss"] = stop_loss

        return OrderResult(
            ok=True,
            action="modify_sl",
            reason=f"simulado (SL -> {stop_loss})",
            ticket=ticket,
            price=stop_loss,
            symbol=symbol,
            raw={"simulated": True},
        )
