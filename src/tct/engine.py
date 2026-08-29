"""Motor: une parser, riesgo, paper trading y broker.

Es el unico lugar donde se decide el orden de las cosas. Las reglas duras que
vienen del CONTEXTO MAESTRO y se respetan aca:

- Siempre se registra el paper trade, este el broker prendido o apagado.
- Si el mensaje es ambiguo, se registra el evento y NO se manda nada.
- Todo lo que pasa (aceptado o rechazado) queda en `data/events.jsonl`.

El paper trade se escribe ANTES de llamar al broker a proposito: si el broker
falla o el proceso muere, la senal igual quedo registrada. Al reves se
perderia la unica evidencia de que la senal existio.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from tct.brokers.base import Broker, OrderResult
from tct.config import Settings
from tct.risk import evaluate_management, evaluate_open, usable_take_profits
from tct.signals.models import EventType, SignalEvent, Side
from tct.signals.parser import parse_signal
from tct.store import OpenPosition, Store, utc_now_iso

logger = logging.getLogger(__name__)


class Engine:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        broker: Broker,
        notifier: Any | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.broker = broker
        self.notifier = notifier

    # -- Entrada principal -------------------------------------------------

    async def handle_message(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Procesa un mensaje del grupo de punta a punta.

        Devuelve un dict con lo que paso, util para tests y para el replay.
        """
        chat_id = metadata.get("chat_id")
        message_id = metadata.get("message_id")

        # Deduplicacion: Telegram reentrega updates y un reinicio puede
        # reprocesar. Sin esto se duplican operaciones.
        # Las ediciones SI se reprocesan: corregir un SL es justamente el caso.
        is_edit = bool(metadata.get("is_edit"))
        if not is_edit and message_id is not None and self.store.already_processed(chat_id, message_id):
            return {"status": "duplicado", "message_id": message_id}

        event = parse_signal(
            text,
            message_id=message_id,
            chat_id=chat_id,
            is_edit=is_edit,
            reply_to_message_id=metadata.get("reply_to_message_id"),
            source=metadata.get("source", "text"),
        )

        if message_id is not None:
            self.store.mark_processed(chat_id, message_id)

        if event is None:
            self.store.save_state()
            return {"status": "ignorado", "reason": "No parece un mensaje de trading"}

        # DRY_RUN observa sin tocar nada: ni paper trade, ni broker, ni estado.
        # Sirve para mirar como parsea un grupo nuevo durante unos dias antes
        # de dejarlo operar.
        if self.settings.dry_run:
            self.store.append_event("dry_run", {"signal": event.to_dict()})
            self.store.save_state()
            logger.info("[DRY RUN] %s %s", event.event_type.value, event.symbol or "")
            return {"status": "dry_run", "signal": event.to_dict()}

        handlers = {
            EventType.OPEN: self._handle_open,
            EventType.CLOSE: self._handle_close,
            EventType.PARTIAL_CLOSE: self._handle_partial_close,
            EventType.MOVE_SL: self._handle_move_sl,
            EventType.UPDATE: self._handle_update,
        }
        handler = handlers.get(event.event_type)

        if handler is None:  # UNKNOWN
            self.store.append_event("ambiguo", {"signal": event.to_dict()})
            self.store.save_state()
            await self._notify(f"Mensaje ambiguo, no se ejecuto nada:\n{text[:300]}")
            return {"status": "ambiguo", "signal": event.to_dict()}

        try:
            result = await handler(event)
        except Exception:
            logger.exception("Error procesando %s", event.event_type.value)
            self.store.append_event("error", {"signal": event.to_dict()})
            result = {"status": "error", "signal": event.to_dict()}

        self.store.save_state()
        return result

    # -- Apertura ----------------------------------------------------------

    async def _handle_open(self, event: SignalEvent) -> dict[str, Any]:
        decision = evaluate_open(self.settings, self.store, event)

        if not decision.ok:
            self.store.append_event(
                "rechazada", {"signal": event.to_dict(), "reasons": decision.reasons}
            )
            logger.info("Senal rechazada: %s", decision.reason_text)
            await self._notify(
                f"Senal RECHAZADA {event.symbol or '?'}\nMotivo: {decision.reason_text}"
            )
            return {"status": "rechazada", "reasons": decision.reasons, "signal": event.to_dict()}

        take_profits = usable_take_profits(event)
        lot = self.settings.default_lot
        trade_id = uuid.uuid4().hex[:12]

        # 1) Paper trade primero, siempre.
        paper = self.store.append_paper_trade({
            "trade_id": trade_id,
            "status": "PAPER_OPENED",
            "mode": self.settings.trading_mode,
            "lot": lot,
            "symbol": event.symbol,
            "side": event.side.value if event.side else None,
            "order_type": event.order_type.value,
            "entry": event.entry,
            "entry_low": event.entry_low,
            "entry_high": event.entry_high,
            "stop_loss": event.stop_loss,
            "take_profits": take_profits,
            "signal": event.to_dict(),
        })
        self.store.bump_daily_counter()

        # 2) Broker, solo si el modo lo permite.
        order = await self._send_open(event, lot, take_profits)

        # 3) Estado. El ticket es el del broker si hubo, o el sintetico del
        #    paper broker, que igual sirve para atar cierres posteriores.
        position = OpenPosition(
            trade_id=trade_id,
            symbol=(event.symbol or "").upper(),
            side=event.side.value if event.side else "",
            lot=lot,
            entry=event.entry,
            stop_loss=event.stop_loss,
            take_profits=take_profits,
            opened_at=utc_now_iso(),
            signal_message_id=event.telegram_message_id,
            broker_ticket=order.ticket if order else None,
            mode=self.settings.trading_mode,
        )
        self.store.add_position(position)

        self.store.append_event("aceptada", {
            "trade_id": trade_id,
            "signal": event.to_dict(),
            "order": order.to_dict() if order else None,
            "warnings": event.warnings,
        })

        await self._notify(self._format_open(event, lot, take_profits, order))
        logger.info(
            "Senal aceptada %s %s lote=%s ticket=%s",
            event.side.value if event.side else "?", event.symbol, lot,
            order.ticket if order else "-",
        )
        return {
            "status": "aceptada",
            "trade_id": trade_id,
            "paper_trade": paper,
            "order": order.to_dict() if order else None,
            "signal": event.to_dict(),
        }

    async def _send_open(
        self, event: SignalEvent, lot: float, take_profits: list[float]
    ) -> OrderResult | None:
        if not await self.broker.is_ready():
            return OrderResult(
                False, "open", f"Broker '{self.broker.name}' no esta listo", symbol=event.symbol
            )
        # MT5 admite un solo TP por posicion: se manda el mas cercano y los
        # demas quedan para gestionarse con los cierres parciales del grupo.
        return await self.broker.open_order(
            symbol=event.symbol or "",
            side=event.side or Side.BUY,
            order_type=event.order_type,
            lot=lot,
            entry=event.entry,
            stop_loss=event.stop_loss,
            take_profit=take_profits[0] if take_profits else None,
        )

    # -- Gestion -----------------------------------------------------------

    async def _handle_close(self, event: SignalEvent) -> dict[str, Any]:
        decision, targets = evaluate_management(self.settings, self.store, event)
        if not decision.ok:
            self.store.append_event(
                "gestion_rechazada", {"signal": event.to_dict(), "reasons": decision.reasons}
            )
            return {"status": "rechazada", "reasons": decision.reasons}

        results = []
        for position in targets:
            order = await self.broker.close_position(
                ticket=position.broker_ticket, symbol=position.symbol, fraction=1.0
            )
            self.store.append_paper_trade({
                "trade_id": position.trade_id,
                "status": "PAPER_CLOSED",
                "symbol": position.symbol,
                "side": position.side,
                "lot": position.lot,
                "order": order.to_dict(),
                "signal": event.to_dict(),
            })
            self.store.remove_position(position.trade_id)
            results.append(order.to_dict())

        self.store.append_event("cierre", {"signal": event.to_dict(), "orders": results})
        await self._notify(f"Cerradas {len(targets)} posicion(es): "
                           f"{', '.join(p.symbol for p in targets)}")
        return {"status": "cerrada", "count": len(targets), "orders": results}

    async def _handle_partial_close(self, event: SignalEvent) -> dict[str, Any]:
        decision, targets = evaluate_management(self.settings, self.store, event)
        if not decision.ok:
            self.store.append_event(
                "gestion_rechazada", {"signal": event.to_dict(), "reasons": decision.reasons}
            )
            return {"status": "rechazada", "reasons": decision.reasons}

        fraction = event.close_fraction or 0.5
        results = []
        for position in targets:
            order = await self.broker.close_position(
                ticket=position.broker_ticket, symbol=position.symbol, fraction=fraction
            )
            # La fraccion es sobre lo que QUEDA, no sobre el lote original:
            # dos "close 50%" seguidos dejan 25%, no 0%.
            position.remaining_fraction = round(position.remaining_fraction * (1 - fraction), 4)
            self.store.append_paper_trade({
                "trade_id": position.trade_id,
                "status": "PAPER_PARTIAL_CLOSE",
                "symbol": position.symbol,
                "fraction_closed": fraction,
                "remaining_fraction": position.remaining_fraction,
                "order": order.to_dict(),
                "signal": event.to_dict(),
            })
            if position.remaining_fraction <= 0.01:
                self.store.remove_position(position.trade_id)
            results.append(order.to_dict())

        self.store.append_event("cierre_parcial", {"signal": event.to_dict(), "orders": results})
        await self._notify(f"Cierre parcial {fraction:.0%} en {len(targets)} posicion(es)")
        return {"status": "cierre_parcial", "fraction": fraction, "orders": results}

    async def _handle_move_sl(self, event: SignalEvent) -> dict[str, Any]:
        decision, targets = evaluate_management(self.settings, self.store, event)
        if not decision.ok:
            self.store.append_event(
                "gestion_rechazada", {"signal": event.to_dict(), "reasons": decision.reasons}
            )
            return {"status": "rechazada", "reasons": decision.reasons}

        results = []
        for position in targets:
            # "a breakeven" significa el precio de entrada de ESA posicion,
            # por eso se resuelve por posicion y no una sola vez.
            new_sl = position.entry if event.move_sl_to_breakeven else event.stop_loss
            if new_sl is None:
                continue

            order = await self.broker.modify_stop_loss(
                ticket=position.broker_ticket, symbol=position.symbol, stop_loss=new_sl
            )
            position.stop_loss = new_sl
            self.store.append_paper_trade({
                "trade_id": position.trade_id,
                "status": "PAPER_SL_MOVED",
                "symbol": position.symbol,
                "new_stop_loss": new_sl,
                "breakeven": event.move_sl_to_breakeven,
                "order": order.to_dict(),
                "signal": event.to_dict(),
            })
            results.append(order.to_dict())

        self.store.append_event("mover_sl", {"signal": event.to_dict(), "orders": results})
        destino = "breakeven" if event.move_sl_to_breakeven else str(event.stop_loss)
        await self._notify(f"SL movido a {destino} en {len(results)} posicion(es)")
        return {"status": "sl_movido", "orders": results}

    async def _handle_update(self, event: SignalEvent) -> dict[str, Any]:
        """Modificacion suelta (SL/TP sin lado).

        No se ejecuta automaticamente: sin direccion ni simbolo no hay forma
        segura de saber a que posicion aplica. Se registra y se avisa para que
        la persona decida.
        """
        self.store.append_event("actualizacion", {"signal": event.to_dict()})
        await self._notify(
            "Llego una modificacion que no se pudo aplicar sola (sin simbolo o sin direccion):\n"
            f"{event.raw_message[:300]}"
        )
        return {"status": "actualizacion_registrada", "signal": event.to_dict()}

    # -- Auxiliares --------------------------------------------------------

    async def _notify(self, text: str) -> None:
        if self.notifier is not None and self.notifier.enabled():
            await self.notifier.send(text)

    def _format_open(
        self, event: SignalEvent, lot: float, take_profits: list[float], order: OrderResult | None
    ) -> str:
        lines = [
            f"SENAL ACEPTADA  {event.side.value if event.side else '?'} {event.symbol}",
            f"Tipo    : {event.order_type.value}",
            f"Entrada : {event.entry}" + (
                f"  (rango {event.entry_low}-{event.entry_high})" if event.has_entry_range else ""
            ),
            f"SL      : {event.stop_loss}",
            f"TPs     : {', '.join(str(tp) for tp in take_profits) or '-'}",
            f"Lote    : {lot}",
            f"Modo    : {self.settings.trading_mode}",
        ]
        if order is not None:
            estado = "OK" if order.ok else "FALLO"
            lines.append(f"Broker  : {estado} - {order.reason}")
            if order.ticket:
                lines.append(f"Ticket  : {order.ticket}")
        if event.warnings:
            lines.append("Avisos  : " + "; ".join(event.warnings))
        return "\n".join(lines)
