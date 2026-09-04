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

import asyncio
import logging
import uuid
from typing import Any

from tct.brokers.base import Broker, OrderResult
from tct.config import Settings
from tct.risk import (
    evaluate_management,
    evaluate_open,
    stop_fuera_de_escala,
    usable_take_profits,
)
from tct.signals.models import EventType, SignalEvent, Side
from tct.signals.parser import parse_signal
from tct.store import OpenPosition, Store, utc_now_iso

logger = logging.getLogger(__name__)


def _parser_no_entendio(event: SignalEvent | None) -> bool:
    """True si vale la pena molestar a la IA local.

    Son los tres casos donde el parser de reglas se queda corto:

    - None    : no reconocio nada.
    - UNKNOWN : vio que era de trading pero no pudo sacar los datos.
    - UPDATE  : entendio A MEDIAS. Saco precios sueltos pero no la direccion,
                asi que el motor no puede aplicarlo a ninguna posicion y solo
                lo registra. Es exactamente el mensaje desprolijo para el que
                existe esta capa ("oro compren 2345 stop 2335"), y dejarlo
                fuera hacia que medio entender bloqueara a la IA.

    Con cualquier otro evento el parser entendio de verdad y la IA sobra: es
    mas lenta, consume CPU y no aporta nada sobre una senal ya bien leida.
    """
    if event is None:
        return True
    return event.event_type in {EventType.UNKNOWN, EventType.UPDATE}


def _restante_tras_cerrar(position, order: OrderResult, fraction: float) -> float:
    """Que fraccion del lote original queda abierta despues de un parcial.

    Se calcula con el volumen que el broker EFECTIVAMENTE cerro, no con la
    fraccion que se pidio, y ahi esta la diferencia: con DEFAULT_LOT=0.01 un
    "close 50%" pide 0.005, el broker lo sube a su lote minimo (0.01) y cierra
    el 100%. Pediste la mitad y se cerro todo.

    Confiando en la fraccion pedida, el estado creia conservar media posicion
    que en MT5 ya no existia: ningun cierre posterior la encontraba, quedaba
    bloqueando el simbolo por la regla de "ya hay una posicion abierta" y
    ocupando cupo de MAX_OPEN_TRADES para siempre.

    Si el broker no informa el volumen cerrado, se cae a la fraccion pedida:
    es la mejor estimacion disponible y es lo que se hacia siempre.
    """
    pedido = round(position.remaining_fraction * (1 - fraction), 4)

    if order.lot is None or not position.lot:
        return pedido

    # `remaining_fraction` es sobre el lote ORIGINAL, asi que el descuento
    # tiene que medirse contra el mismo lote y no contra lo que queda abierto.
    abierto = position.lot * position.remaining_fraction
    queda = max(0.0, abierto - float(order.lot))
    return round(queda / position.lot, 4)


class Engine:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        broker: Broker,
        notifier: Any | None = None,
        ollama: Any | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.broker = broker
        self.notifier = notifier
        # Interprete de respaldo. None = apagado o no disponible; el sistema
        # funciona identico sin el.
        self.ollama = ollama
        # Telethon despacha cada mensaje en su propia task. Sin este candado,
        # dos senales casi simultaneas evaluan el riesgo a la vez (leyendo el
        # mismo estado) y registran despues: las dos ven "0 posiciones
        # abiertas" y las dos abren, salteandose MAX_OPEN_TRADES y la regla de
        # una posicion por simbolo. Serializar el ciclo entero es la unica
        # forma simple de que la foto que ve el riesgo siga siendo cierta
        # cuando se escribe el resultado.
        self._turno = asyncio.Lock()

    # -- Entrada principal -------------------------------------------------

    async def handle_message(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Procesa un mensaje del grupo de punta a punta.

        Devuelve un dict con lo que paso, util para tests y para el replay.
        """
        async with self._turno:
            return await self._procesar(text, metadata)

    async def _procesar(self, text: str, metadata: dict[str, Any]) -> dict[str, Any]:
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

        # Las ediciones se exceptuan del dedup para captar correcciones (un SL
        # mal tipeado que el grupo arregla). Pero si ese mensaje YA abrio una
        # operacion, la edicion no puede abrir otra: los canales editan el
        # mensaje viejo para marcar el resultado, y eso mandaba una orden
        # nueva horas despues, a precio de mercado y con el SL original.
        if (
            is_edit
            and event is not None
            and event.event_type is EventType.OPEN
            and self.store.ya_opero(chat_id, message_id)
        ):
            self.store.append_event("edicion_ignorada", {"signal": event.to_dict()})
            self.store.save_state()
            logger.info(
                "Edicion de un mensaje que ya opero (%s). No se reabre.", message_id
            )
            return {"status": "edicion_ignorada", "signal": event.to_dict()}

        # La IA solo entra donde el parser de reglas fallo. Si el parser
        # entendio, no se la consulta: es mas rapida, gratis y determinista.
        if self.ollama is not None and _parser_no_entendio(event):
            interpretado = await self._consultar_ia(text, metadata)
            if interpretado is not None:
                event = interpretado

        if event is None:
            self.store.save_state()
            return {"status": "ignorado", "reason": "No parece un mensaje de trading"}

        # Pausa manual desde Telegram. Se sigue leyendo, parseando y
        # registrando: lo unico que se corta es abrir o cerrar. Asi, cuando
        # reanudes, podes mirar en events.jsonl que te perdiste.
        if self.store.is_paused:
            self.store.append_event("pausado", {"signal": event.to_dict()})
            self.store.save_state()
            logger.info(
                "PAUSADO: se registro %s %s pero no se opero.",
                event.event_type.value, event.symbol or "",
            )
            return {"status": "pausado", "signal": event.to_dict()}

        # DRY_RUN observa sin tocar nada: ni paper trade, ni broker, ni estado.
        # Sirve para mirar como parsea un grupo nuevo durante unos dias antes
        # de dejarlo operar.
        if self.settings.dry_run:
            self.store.append_event("dry_run", {"signal": event.to_dict()})
            self.store.save_state()
            logger.info("[DRY RUN] %s %s", event.event_type.value, event.symbol or "")
            return {"status": "dry_run", "signal": event.to_dict()}

        # Una senal que entendio la IA y no el parser NO se ejecuta, salvo que
        # se active a mano OLLAMA_AUTO_EXECUTE. Ver la explicacion completa en
        # intelligence/ollama.py: risk.py valida que un precio sea coherente,
        # no que sea el correcto, asi que un numero inventado pero plausible
        # pasaria todos los controles.
        if event.source == "ollama" and not self.settings.ollama_auto_execute:
            self.store.append_event("ia_sugerencia", {"signal": event.to_dict()})
            self.store.save_state()
            await self._notify(self._format_sugerencia_ia(event))
            logger.info(
                "La IA interpreto un mensaje que el parser no entendio (%s %s). "
                "Solo se aviso, no se opero.",
                event.event_type.value, event.symbol or "?",
            )
            return {"status": "sugerencia_ia", "signal": event.to_dict()}

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
        # El freno por perdida diaria necesita saber cuanto vale la cuenta
        # AHORA. Se pide antes de evaluar el riesgo porque es justo uno de los
        # motivos por los que se puede rechazar la senal.
        await self._actualizar_equity()

        # Y el contraste con el precio real necesita saber cuanto vale el
        # instrumento AHORA, por el mismo motivo.
        precio_mercado = await self._precio_para_abrir(event)

        decision = evaluate_open(
            self.settings, self.store, event, market_price=precio_mercado
        )

        if not decision.ok:
            self.store.append_event(
                "rechazada", {
                    "signal": event.to_dict(),
                    "reasons": decision.reasons,
                    "precio_mercado": precio_mercado,
                },
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
            # Precio real del instrumento en el momento de la senal, o None si
            # el broker no lo dio. Es lo que despues va a permitir calcular el
            # P&L de los paper trades contra algo que existio de verdad, en vez
            # de contra la entrada que dijo el mensaje.
            "precio_mercado": precio_mercado,
            "stop_loss": event.stop_loss,
            "take_profits": take_profits,
            "signal": event.to_dict(),
        })

        # 2) Broker, solo si el modo lo permite.
        order = await self._send_open(event, lot, take_profits)

        # Si el broker rechazo, NO se registra la posicion. Registrarla dejaria
        # una fantasma: existe en el estado y no en el broker, bloquea el
        # simbolo por la regla de "ya hay una posicion abierta" y ocupa cupo de
        # MAX_OPEN_TRADES, para siempre. El paper trade de arriba ya quedo
        # escrito, asi que la senal no se pierde.
        if order is not None and not order.ok:
            self.store.append_event("apertura_fallida", {
                "trade_id": trade_id,
                "signal": event.to_dict(),
                "order": order.to_dict(),
            })
            await self._notify(
                f"NO se pudo abrir {event.symbol}: {order.reason}\n"
                "La senal quedo registrada, pero no hay ninguna posicion."
            )
            logger.error("El broker rechazo la apertura de %s: %s",
                         event.symbol, order.reason)
            return {
                "status": "apertura_fallida",
                "reason": order.reason,
                "paper_trade": paper,
                "signal": event.to_dict(),
            }

        # El cupo diario se consume ACA, no antes de llamar al broker.
        # MAX_SIGNALS_PER_DAY limita cuantas OPERACIONES toma el bot en un dia,
        # y una senal que el broker rechazo no es una operacion.
        #
        # Contarla igual tenia una consecuencia concreta: si el canal opera un
        # instrumento que el broker conectado no expone (BTCUSD en una demo sin
        # cripto, por ejemplo), cada senal de ese simbolo fallaba al abrir y
        # aun asi ocupaba un lugar del cupo, dejando sin lugar a las que si
        # podian operar. El paper trade ya quedo escrito unas lineas arriba,
        # asi que la senal no se pierde: lo unico que no se gasta es el cupo.
        self.store.bump_daily_counter()

        # 3) Estado. El ticket es el del broker si hubo, o el sintetico del
        #    paper broker, que igual sirve para atar cierres posteriores.
        #
        # El lote que se guarda es el que ACEPTO el broker, no el que se pidio.
        # `_normalize_volume` lo ajusta al paso y al minimo del instrumento, asi
        # que los dos numeros pueden diferir. Guardar el pedido dejaba al estado,
        # a los avisos y sobre todo a la matematica de los cierres parciales
        # trabajando sobre un lote que en MT5 no existe.
        lot_abierto = order.lot if (order is not None and order.lot) else lot
        position = OpenPosition(
            trade_id=trade_id,
            symbol=(event.symbol or "").upper(),
            side=event.side.value if event.side else "",
            lot=lot_abierto,
            entry=event.entry,
            stop_loss=event.stop_loss,
            take_profits=take_profits,
            opened_at=utc_now_iso(),
            signal_message_id=event.telegram_message_id,
            broker_ticket=order.ticket if order else None,
            mode=self.settings.trading_mode,
        )
        self.store.add_position(position)
        if event.telegram_message_id is not None:
            self.store.marcar_que_opero(event.telegram_chat_id, event.telegram_message_id)

        self.store.append_event("aceptada", {
            "trade_id": trade_id,
            "signal": event.to_dict(),
            "order": order.to_dict() if order else None,
            "warnings": event.warnings,
        })

        await self._notify(
            self._format_open(event, lot_abierto, take_profits, order, precio_mercado)
        )
        logger.info(
            "Senal aceptada %s %s lote=%s ticket=%s",
            event.side.value if event.side else "?", event.symbol, lot_abierto,
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
        cerradas = 0
        fallidas: list[str] = []
        ausentes: list[str] = []
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
            # Solo se borra del estado si el broker confirmo. Borrarla igual
            # dejaria la operacion viva en el broker y sin registro: ningun
            # cierre posterior la encontraria, y correria sola hasta el SL.
            if order.ok:
                self.store.remove_position(position.trade_id)
                cerradas += 1
            elif self._reconciliar_ausente(position, order):
                ausentes.append(position.symbol)
            else:
                fallidas.append(f"{position.symbol}: {order.reason}")
            results.append(order.to_dict())

        self.store.append_event("cierre", {
            "signal": event.to_dict(), "orders": results,
            "fallidas": fallidas, "ausentes": ausentes,
        })

        ya_estaban = (
            f"\n\nEstas ya estaban cerradas en el broker: {', '.join(ausentes)}.\n"
            "Se sacaron del estado, asi que esos simbolos quedan libres de nuevo."
            if ausentes else ""
        )

        if fallidas:
            await self._notify(
                f"Cerradas {cerradas} de {len(targets)}. NO se pudieron cerrar:\n"
                + "\n".join(f"  {f}" for f in fallidas)
                + "\nSiguen abiertas y el bot las sigue teniendo en cuenta."
                + ya_estaban
            )
            return {"status": "cierre_parcial_fallido", "count": cerradas,
                    "fallidas": fallidas, "ausentes": ausentes, "orders": results}

        if ausentes:
            await self._notify(f"Cerradas {cerradas} de {len(targets)}." + ya_estaban)
            return {"status": "cerrada", "count": cerradas,
                    "ausentes": ausentes, "orders": results}

        await self._notify(f"Cerradas {cerradas} posicion(es): "
                           f"{', '.join(p.symbol for p in targets)}")
        return {"status": "cerrada", "count": cerradas, "orders": results}

    async def _handle_partial_close(self, event: SignalEvent) -> dict[str, Any]:
        decision, targets = evaluate_management(self.settings, self.store, event)
        if not decision.ok:
            self.store.append_event(
                "gestion_rechazada", {"signal": event.to_dict(), "reasons": decision.reasons}
            )
            return {"status": "rechazada", "reasons": decision.reasons}

        fraction = event.close_fraction or 0.5
        results = []
        aplicadas = 0
        fallidas: list[str] = []
        ausentes: list[str] = []
        for position in targets:
            order = await self.broker.close_position(
                ticket=position.broker_ticket, symbol=position.symbol, fraction=fraction
            )
            results.append(order.to_dict())

            # Si el broker rechazo, el estado NO se toca. Descontar igual es la
            # "operacion huerfana" de siempre, en el handler que se habia
            # quedado sin revisar: un solo "close 99%" rechazado bajaba el
            # restante por debajo del umbral y borraba del estado una posicion
            # que sigue viva en MT5. Nadie la volveria a encontrar.
            if not order.ok:
                if self._reconciliar_ausente(position, order):
                    ausentes.append(position.symbol)
                    continue
                logger.error("No se pudo cerrar parcialmente %s: %s",
                             position.symbol, order.reason)
                fallidas.append(f"{position.symbol}: {order.reason}")
                continue

            position.remaining_fraction = _restante_tras_cerrar(position, order, fraction)
            aplicadas += 1
            self.store.append_paper_trade({
                "trade_id": position.trade_id,
                "status": "PAPER_PARTIAL_CLOSE",
                "symbol": position.symbol,
                "fraction_closed": fraction,
                "lot_cerrado": order.lot,
                "remaining_fraction": position.remaining_fraction,
                "order": order.to_dict(),
                "signal": event.to_dict(),
            })
            if position.remaining_fraction <= 0.01:
                self.store.remove_position(position.trade_id)

        self.store.append_event("cierre_parcial", {
            "signal": event.to_dict(), "orders": results,
            "fallidas": fallidas, "ausentes": ausentes,
        })

        if fallidas:
            await self._notify(
                f"Cierre parcial {fraction:.0%}: salio en {aplicadas} de {len(targets)}.\n"
                "NO se pudo en:\n" + "\n".join(f"  {f}" for f in fallidas)
                + "\nEsas siguen abiertas enteras, y el bot las sigue contando asi."
            )
            return {"status": "cierre_parcial_fallido", "fraction": fraction,
                    "count": aplicadas, "fallidas": fallidas, "orders": results}

        await self._notify(f"Cierre parcial {fraction:.0%} en {aplicadas} posicion(es)")
        return {"status": "cierre_parcial", "fraction": fraction, "orders": results}

    async def _handle_move_sl(self, event: SignalEvent) -> dict[str, Any]:
        decision, targets = evaluate_management(self.settings, self.store, event)
        if not decision.ok:
            self.store.append_event(
                "gestion_rechazada", {"signal": event.to_dict(), "reasons": decision.reasons}
            )
            return {"status": "rechazada", "reasons": decision.reasons}

        results = []
        movidas = 0
        fallidas: list[str] = []
        descartadas: list[str] = []
        for position in targets:
            # "a breakeven" significa el precio de entrada de ESA posicion,
            # por eso se resuelve por posicion y no una sola vez.
            new_sl = position.entry if event.move_sl_to_breakeven else event.stop_loss
            if new_sl is None:
                # `evaluate_management` solo rechaza si NINGUNA posicion tiene
                # entrada. Con una mezcla, las que no la tienen se salteaban en
                # SILENCIO y el aviso igual decia "SL movido a breakeven en 1
                # posicion(es)": te ibas creyendo que quedaron todas protegidas.
                descartadas.append(
                    f"{position.symbol}: sin precio de entrada registrado, "
                    "no hay a donde llevar el breakeven"
                )
                continue

            # El contraste con el precio real, tambien en la gestion. Se
            # resuelve POR POSICION y no una sola vez porque un "MOVER SL A
            # 4430" sin simbolo aplica a TODAS las abiertas: 4430 es un stop
            # perfecto para el oro y una barbaridad para EURUSD, que cotiza a
            # 1.08. Y MT5 no ataja eso: rechaza los stops del lado equivocado,
            # pero un stop del lado correcto y absurdamente lejos lo acepta sin
            # chistar, dejando la posicion sin proteccion real.
            #
            # Se descartan solo las posiciones cuyo numero no da la escala, en
            # vez de rechazar el mensaje entero: mover lo que se puede mover es
            # mejor que no mover nada, y lo que quedo sin tocar se avisa.
            motivo = stop_fuera_de_escala(
                new_sl, await self._precio_de_mercado(position.symbol)
            )
            if motivo is not None:
                logger.error("No se movio el SL de %s: %s", position.symbol, motivo)
                descartadas.append(f"{position.symbol}: {motivo}")
                continue

            order = await self.broker.modify_stop_loss(
                ticket=position.broker_ticket, symbol=position.symbol, stop_loss=new_sl
            )
            # Sin este chequeo el estado mentiria sobre donde esta el stop: el
            # bot creeria estar protegido en breakeven mientras el broker lo
            # mantiene donde estaba.
            if not order.ok:
                results.append(order.to_dict())
                if self._reconciliar_ausente(position, order):
                    descartadas.append(
                        f"{position.symbol}: ya no existia en el broker, "
                        "se saco del estado"
                    )
                    continue
                logger.error("No se pudo mover el SL de %s: %s",
                             position.symbol, order.reason)
                fallidas.append(f"{position.symbol}: {order.reason}")
                continue
            movidas += 1
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

        self.store.append_event("mover_sl", {
            "signal": event.to_dict(), "orders": results,
            "fallidas": fallidas, "descartadas": descartadas,
        })
        destino = "breakeven" if event.move_sl_to_breakeven else str(event.stop_loss)
        problemas = fallidas + descartadas

        # `results` incluye los rechazos, asi que contarlos como movidas decia
        # "SL movido en 1 posicion(es)" con el broker habiendo rechazado todo.
        # El estado ya estaba bien; lo que mentia era el aviso, que es lo unico
        # que la persona ve desde el telefono. Creerte protegido en breakeven
        # cuando el stop sigue donde estaba es peor que no recibir el aviso.
        if problemas:
            await self._notify(
                f"SL a {destino}: salio en {movidas} de {len(problemas) + movidas}.\n"
                "NO se pudo mover en:\n" + "\n".join(f"  {p}" for p in problemas)
                + "\nEsas posiciones siguen con el stop anterior."
            )
            return {"status": "sl_movido_parcial", "count": movidas,
                    "fallidas": fallidas, "descartadas": descartadas,
                    "orders": results}

        await self._notify(f"SL movido a {destino} en {movidas} posicion(es)")
        return {"status": "sl_movido", "count": movidas, "orders": results}

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

    async def _actualizar_equity(self) -> None:
        """Trae el valor de la cuenta y fija la referencia del dia.

        Si el broker no puede darlo, `balance_actual` queda en None y el freno
        diario no opina: sin dato no se rechaza nada.
        """
        if self.settings.max_daily_loss_pct <= 0:
            return
        try:
            equity = await self.broker.account_equity()
        except Exception:
            logger.warning("No se pudo leer el equity de la cuenta", exc_info=True)
            return

        self.store.balance_actual = equity
        inicial = self.store.day_start_balance(equity)

        if inicial and equity is not None:
            caida = (inicial - equity) / inicial * 100
            if caida > 0:
                logger.info(
                    "Cuenta: %.2f | apertura del dia: %.2f | caida %.2f%% (tope %.1f%%)",
                    equity, inicial, caida, self.settings.max_daily_loss_pct,
                )

    def _reconciliar_ausente(self, position, order: OrderResult) -> bool:
        """Saca del estado una posicion que el broker dice que ya no existe.

        Que no exista NO es un fallo de la operacion: es la unica informacion
        capaz de resolver una posicion fantasma, y tratarla como rechazo la
        volvia eterna.

        El caso que lo hace probable no tiene nada de exotico: la propia guia le
        dice al usuario que revise las posiciones en MetaTrader y las cierre a
        mano si no las quiere. Desde ese momento el bot tenia una posicion que
        no podia cerrar nunca, que bloqueaba el simbolo por la regla de "ya hay
        una posicion abierta" y que ocupaba cupo de MAX_OPEN_TRADES: cada senal
        de ese instrumento se rechazaba, para siempre.

        El broker solo pone la marca cuando PREGUNTO y no estaba. Un error de
        consulta (terminal caida) no la lleva: ahi la posicion puede estar
        perfectamente viva, y borrarla la dejaria corriendo sin registro.
        """
        if not order.raw.get("ausente"):
            return False
        logger.info(
            "%s ya no existia en el broker (%s): se saca del estado.",
            position.symbol, order.reason,
        )
        self.store.remove_position(position.trade_id)
        return True

    async def _precio_de_mercado(self, symbol: str | None) -> float | None:
        """Trae la cotizacion real de un instrumento.

        Nunca lanza: si el broker no responde, quien la pidio se queda sin dato
        y no opina. Es la misma politica que el freno diario, y por el mismo
        motivo: un broker lento no puede dejar al bot sin operar.

        Se pide con el simbolo CANONICO (XAUUSD) y es el broker el que lo
        traduce a como se llame en esa cuenta, igual que al mandar la orden.
        """
        if not symbol:
            return None
        try:
            return await self.broker.market_price(symbol)
        except Exception:
            logger.warning(
                "No se pudo leer el precio de mercado de %s", symbol, exc_info=True
            )
            return None

    async def _precio_para_abrir(self, event: SignalEvent) -> float | None:
        """El precio que necesita el control de apertura, si esta encendido.

        Con los dos limites en 0 la llamada seria puro costo en el camino
        critico de una senal.
        """
        if (
            self.settings.max_spread_from_entry_pct <= 0
            and self.settings.max_pending_distance_pct <= 0
        ):
            return None
        return await self._precio_de_mercado(event.symbol)

    async def _consultar_ia(self, text: str, metadata: dict[str, Any]) -> SignalEvent | None:
        """Consulta al interprete local. Nunca lanza: es una capa opcional."""
        try:
            return await self.ollama.interpretar(text, metadata)
        except Exception:
            logger.exception("La IA local fallo; se sigue solo con el parser de reglas")
            return None

    def _format_sugerencia_ia(self, event: SignalEvent) -> str:
        lines = [
            "MENSAJE QUE EL PARSER NO ENTENDIO",
            "La IA local lo interpreto asi. NO se opero nada.",
            "",
            f"Tipo    : {event.event_type.value}",
            f"Simbolo : {event.symbol or '-'}",
            f"Lado    : {event.side.value if event.side else '-'}",
            f"Entrada : {event.entry if event.entry is not None else '-'}",
            f"SL      : {event.stop_loss if event.stop_loss is not None else '-'}",
            f"TPs     : {', '.join(str(tp) for tp in event.take_profits) or '-'}",
        ]
        if event.warnings:
            lines.append("")
            lines.extend(event.warnings)
        lines.append("")
        lines.append("Mensaje original:")
        lines.append(event.raw_message[:500])
        return "\n".join(lines)

    async def _notify(self, text: str) -> None:
        if self.notifier is not None and self.notifier.enabled():
            await self.notifier.send(text)

    def _format_open(
        self,
        event: SignalEvent,
        lot: float,
        take_profits: list[float],
        order: OrderResult | None,
        precio_mercado: float | None = None,
    ) -> str:
        lines = [
            f"SENAL ACEPTADA  {event.side.value if event.side else '?'} {event.symbol}",
            f"Tipo    : {event.order_type.value}",
            f"Entrada : {event.entry}" + (
                f"  (rango {event.entry_low}-{event.entry_high})" if event.has_entry_range else ""
            ),
            # Al lado de la entrada del mensaje, para poder comparar de un
            # vistazo desde el telefono sin abrir MT5.
            f"Mercado : {precio_mercado if precio_mercado is not None else 'sin dato'}",
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
