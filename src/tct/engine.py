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
import functools
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from tct.brokers.base import Broker, OrderResult
from tct.config import Settings
from tct.risk import (
    evaluate_management,
    evaluate_open,
    motivos_por_distancia,
    stop_agranda_el_riesgo,
    stop_fuera_de_escala,
    usable_take_profits,
)
from tct.signals.models import EventType, OrderType, SignalEvent, Side
from tct.signals.parser import es_descarte_deliberado, parse_signal, pide_mover_tp
from tct.store import OpenPosition, Store, utc_now_iso

logger = logging.getLogger(__name__)

# Cuantas veces se reintenta una orden a mercado que el broker rechazo porque
# el precio se movio (recotizacion). Cada reintento vuelve a pasar el precio
# nuevo por el filtro de entrada tarde: ver `Engine._send_open`.
REINTENTOS_POR_PRECIO = 2

# Cuanto se sigue buscando una orden que order_send no confirmo. Si entro,
# aparece en segundos; esto cubre un MetaTrader que tarda en volver.
BUSCAR_SIN_CONFIRMAR = timedelta(minutes=10)

# Retcode de MT5 cuando el stop esta mas cerca del precio de lo que el broker
# permite (TRADE_RETCODE_INVALID_STOPS).
STOPS_INVALIDOS = 10016


def _vale_preguntarle_a_la_ia(event: SignalEvent | None, text: str) -> bool:
    """Si conviene molestar a la IA local con este mensaje.

    Un None del parser tiene DOS significados y hay que separarlos, porque
    tratarlos igual deshace una decision que costo cara:

        no lo entendi          -> que opine la IA, para eso esta
        lo descarte a proposito -> NO. Ya se decidio, y se decidio bien.

    Las cronicas y los recaps caen en el segundo caso. `_NARRATIVA_RE` existe
    porque "pudimos cerrar otra operacion" se ejecutaba como una orden de
    cerrar todo. Pasarle igual esos mensajes a la IA es rodear la guarda por
    atras: un modelo de 3B los lee como aperturas.

    En el canal del usuario esto pasaba todos los dias. Los recaps generaban
    una notificacion de "la IA interpreto esto" por cada mensaje Y por cada
    edicion, mas ~15 segundos de CPU cada una. Nunca opero nada porque
    OLLAMA_AUTO_EXECUTE esta en false, pero un aviso que siempre es ruido
    entrena a ignorar los avisos.
    """
    if event is None:
        return not es_descarte_deliberado(text)
    return _parser_no_entendio(event)


def _mismo_precio(a: float, b: float) -> bool:
    """Si dos precios son literalmente el mismo numero.

    A proposito NO tiene tolerancia. Sirve para reconocer un "MOVER SL A 4467"
    como el breakeven de una entrada de 4467, y los dos numeros salen del mismo
    canal con el mismo formato, asi que coinciden exacto. Aflojarlo tendria un
    costo asimetrico: de mas, se pisa un stop que el canal pidio a proposito;
    de menos, se cae en el comportamiento viejo, que es el literal. Errar para
    el lado de obedecer el mensaje es el lado barato.
    """
    return abs(a - b) <= max(abs(a), abs(b), 1.0) * 1e-9


def _entrada_efectiva(position, usar_precio_real: bool) -> float | None:
    """A que precio esta de verdad esta posicion.

    `entry_real` queda en None en paper trading y en las posiciones que se
    abrieron antes de que el campo existiera, asi que siempre hay que poder
    caer en `entry`.
    """
    if usar_precio_real and position.entry_real:
        return position.entry_real
    return position.entry


def _destino_del_stop(position, event: SignalEvent, usar_precio_real: bool) -> float | None:
    """A que precio va el stop de ESTA posicion. Hay tres casos.

        "a breakeven", sin numero        -> la entrada de esta posicion
        "MOVER SL A <la entrada>"        -> tambien es breakeven, escrito como
                                            numero: es como habla este canal
        "MOVER SL A <cualquier otro>"    -> literal, es un stop nuevo

    EL SEGUNDO CASO ES EL QUE IMPORTA Y COSTO PLATA.

    Una orden a mercado entra al precio de AHORA, no al del mensaje. Medido
    sobre 12 operaciones reales del canal, la diferencia fue de 0.02% a 0.07%:
    decimas de punto en oro. Mover el stop al numero del mensaje en vez de al
    precio de llenado convierte el breakeven en una moneda al aire, y en esas
    12 salio mal dos de cada tres veces:

        SELL 4467, lleno en 4467.745, stop a 4467.0  ->  +0.57
        BUY  4387, lleno en 4387.315, stop a 4387.0  ->  -0.42
        SELL 4334, lleno en 4333.025, stop a 4334.0  ->  -1.08

    Las tres cerraron "en breakeven" y dos perdieron. No es slippage: es que el
    stop estaba puesto del lado equivocado del precio de entrada real, siempre
    por la misma distancia que el spread.
    """
    if event.move_sl_to_breakeven:
        return _entrada_efectiva(position, usar_precio_real)

    pedido = event.stop_loss
    if pedido is None:
        return None
    if (
        usar_precio_real
        and position.entry is not None
        and _mismo_precio(pedido, position.entry)
    ):
        return _entrada_efectiva(position, usar_precio_real)
    return pedido


def _interpretacion_utilizable(event: SignalEvent) -> bool:
    """Si lo que devolvio la IA sirve para algo, aunque sea para avisar.

    Una APERTURA sin simbolo o sin entrada no se puede ejecutar jamas: el
    riesgo la rechazaria con "no se pudo identificar el simbolo". Avisar de
    ella es puro ruido, y encima ruido que parece importante.

    Caso real del canal, medido: seis avisos en un dia de "MENSAJE QUE EL
    PARSER NO ENTENDIO / la IA lo interpreto asi: Tipo OPEN, Simbolo -,
    Entrada -". Todos venian de recaps del canal contando como les fue. Un
    aviso que siempre es ruido entrena a ignorar los avisos, y el dia que
    llegue uno que importa va a estar mezclado con esos.

    Los eventos de GESTION no entran en esta regla: un "mover el SL a X" sin
    simbolo es legitimo y aplica a todo lo abierto.
    """
    if event.event_type is not EventType.OPEN:
        return True
    return bool(event.symbol) and event.entry is not None


# Cuanto despues del mensaje original una edicion todavia puede ABRIR. Es el
# tiempo de una correccion ("perdon, el SL es 4424"); mas tarde, lo que el
# canal hace es anotar el resultado.
VENTANA_DE_CORRECCION = timedelta(minutes=10)


def _antiguedad(metadata: dict[str, Any]) -> timedelta | None:
    """Cuanto hace que se escribio el mensaje (el ORIGINAL, si es una edicion:
    Telegram manda en `date` esa hora). None si no se sabe."""
    fecha = metadata.get("date")
    if not fecha:
        return None
    try:
        original = datetime.fromisoformat(fecha)
    except (TypeError, ValueError):
        return None
    if original.tzinfo is None:
        original = original.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - original


def _mensaje_viejo(metadata: dict[str, Any]) -> bool:
    """Si el mensaje se escribio hace mas que la ventana de una correccion.
    Sin fecha no se opina: se hace lo de siempre."""
    edad = _antiguedad(metadata)
    return edad is not None and edad > VENTANA_DE_CORRECCION


def _minutos_de_antiguedad(metadata: dict[str, Any]) -> int | None:
    edad = _antiguedad(metadata)
    return int(edad.total_seconds() // 60) if edad is not None else None


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
        ollama: Any | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.broker = broker
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
        # Ordenes que order_send no confirmo y todavia no aparecieron.
        self._sin_confirmar: list[dict[str, Any]] = []
        # Stops que el broker rechazo por distancia minima (10016): trade_id -> SL.
        self._sl_pendientes: dict[str, float] = {}
        # Las consultas a la IA que corren de fondo (ver `_ia_de_fondo`).
        self._tareas_ia: set[asyncio.Task] = set()

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
        #
        # Lo que SI hace, dentro de la ventana de una correccion: si cambio el
        # SL, se lo aplica a las posiciones de esa senal. Antes se ignoraba en
        # silencio, y un SL tipeado 4324 en vez de 4424 quedaba con 108 puntos
        # de riesgo (542 dolares a 0.05) aunque el canal lo corrigiera al minuto.
        if (
            is_edit
            and event is not None
            and event.event_type is EventType.OPEN
            and self.store.ya_opero(chat_id, message_id)
        ):
            if not _mensaje_viejo(metadata) and event.stop_loss is not None:
                corregido = await self._corregir_sl(event, message_id)
                if corregido is not None:
                    self.store.save_state()
                    return corregido
            self.store.append_event("edicion_ignorada", {"signal": event.to_dict()})
            self.store.save_state()
            logger.info(
                "Edicion de un mensaje que ya opero (%s). No se reabre.", message_id
            )
            return {"status": "edicion_ignorada", "signal": event.to_dict()}

        # NADA de hace mas de 10 minutos ejecuta: ni una edicion (el canal
        # edita horas despues para anotar el resultado, y "MOVER SL A 4432 ✅"
        # se seguia leyendo como mover el stop, sobre la posicion de OTRA
        # senal), ni un mensaje nuevo entregado tarde (al volver internet,
        # Telegram entrega lo que se perdio con su hora original: una senal de
        # hace 40 minutos se abria, y un MOVER SL atrasado alejo 48 puntos el
        # stop de la unica posicion abierta). Telegram manda en `date` la hora
        # del mensaje original. `tct simular` reproduce mensajes viejos a
        # proposito, y ahi no aplica.
        if (
            event is not None
            and not metadata.get("reproduccion")
            and _mensaje_viejo(metadata)
        ):
            minutos = _minutos_de_antiguedad(metadata)
            self.store.append_event(
                "edicion_ignorada" if is_edit else "ignorado_por_viejo",
                {"signal": event.to_dict(), "motivo": "tardia", "minutos": minutos},
            )
            self.store.save_state()
            if is_edit:
                logger.info("Edicion de un mensaje de hace %s minutos (%s): no se ejecuta "
                            "tarde.", minutos, message_id)
                return {"status": "edicion_ignorada", "signal": event.to_dict()}
            await self._avisar(
                f"Llego TARDE un mensaje de hace {minutos} minutos (se habia cortado "
                f"la conexion?). NO se ejecuto:\n{text[:300]}\n"
                "Si la hora de esta PC esta mal, todos los mensajes van a parecer "
                "viejos: corregila.",
                problema=True,
            )
            return {"status": "ignorado_por_viejo", "signal": event.to_dict()}

        # La IA solo entra donde el parser de reglas fallo. Si el parser
        # entendio, no se la consulta: es mas rapida, gratis y determinista.
        ia_de_fondo = False
        if self.ollama is not None and _vale_preguntarle_a_la_ia(event, text):
            if not self.settings.ollama_auto_execute:
                # Lo que diga la IA solo se anota: nunca opera. Entonces no
                # tiene por que hacer esperar a nadie. Antes se la consultaba
                # con el turno tomado, y una senal que llegaba detras esperaba
                # lo que tardara la IA: ~15 s en la PC del usuario (sin placa
                # de video), 45 con el timeout, 90 con una edicion, y mas con
                # tres bots haciendo cola en el mismo Ollama. Medido el 27/09:
                # con el precio corriendo 2,7 puntos en esa espera, el filtro
                # de entrada tarde RECHAZABA la senal. Ahora se consulta de
                # fondo, fuera del turno.
                self._ia_de_fondo(text, metadata)
                ia_de_fondo = True
                if event is None:
                    self.store.save_state()
                    return {"status": "consultando_ia"}
            else:
                interpretado = await self._consultar_ia(text, metadata)
                if interpretado is not None and _interpretacion_utilizable(interpretado):
                    event = interpretado

        if event is None:
            self.store.save_state()
            return {"status": "ignorado", "reason": "No parece un mensaje de trading"}

        # Pausa manual desde Telegram. Se sigue leyendo, parseando y
        # registrando: lo unico que se corta es ABRIR. Asi, cuando reanudes,
        # podes mirar en events.jsonl que te perdiste.
        #
        # La gestion de lo que ya esta abierto sigue: antes la pausa cortaba
        # todo, y un "MOVER SL A <entrada>" llegado en pausa dejaba la posicion
        # con el stop original, sin aviso y sin forma de recuperarlo al
        # reanudar (el mensaje ya quedaba procesado).
        if self.store.is_paused and event.event_type is EventType.OPEN:
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
        # se active a mano OLLAMA_AUTO_EXECUTE: sin eso la IA corre de fondo
        # (`_ia_de_fondo`) y nunca llega hasta aca. Ver la explicacion completa
        # en intelligence/ollama.py: risk.py valida que un precio sea
        # coherente, no que sea el correcto, asi que un numero inventado pero
        # plausible pasaria todos los controles.

        handlers = {
            EventType.OPEN: self._handle_open,
            EventType.CLOSE: self._handle_close,
            EventType.PARTIAL_CLOSE: self._handle_partial_close,
            EventType.MOVE_SL: self._handle_move_sl,
            EventType.MOVE_TP: self._handle_move_tp,
            EventType.UPDATE: self._handle_update,
        }
        handler = handlers.get(event.event_type)

        # Con la IA consultando este mismo mensaje de fondo, el aviso lo da
        # ella: el del parser ("modificacion que no se pudo aplicar") salia
        # ademas, y decia lo contrario (la IA lo leia como una apertura).
        if handler is None:  # UNKNOWN
            self.store.append_event("ambiguo", {"signal": event.to_dict()})
            self.store.save_state()
            if not ia_de_fondo:
                await self._avisar(
                    f"Mensaje ambiguo, no se ejecuto nada:\n{text[:300]}", problema=True
                )
            return {"status": "ambiguo", "signal": event.to_dict()}
        if event.event_type is EventType.UPDATE and ia_de_fondo:
            handler = functools.partial(self._handle_update, avisar=False)

        try:
            result = await handler(event)
            # Un mismo mensaje puede pedir las dos cosas ("Mover TP a 4450 y SL
            # a 4432"). El parser lo clasifica como MOVE_SL -el stop es lo que
            # protege-, y aca se atiende tambien el TP. Solo con un verbo
            # apuntando al TP: `pide_mover_tp` no toma "TP se mantiene en 4440"
            # como pedido de moverlo.
            if (
                event.event_type is EventType.MOVE_SL
                and event.take_profits
                and pide_mover_tp(event.raw_message or "")
            ):
                result = {**result, "mover_tp": await self._handle_move_tp(event)}
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
        # Lo primero: sacar del estado lo que el broker ya cerro solo. Sin
        # esto, la regla de "ya hay una posicion abierta en X" rechaza la
        # senal que viene ahora por culpa de una que dejo de existir.
        await self._sincronizar_posiciones()
        # Y lo contrario: una orden que no se confirmo y SI entro tiene que
        # estar registrada antes de mirar los topes, o se abre una de mas.
        await self._confirmar_sin_respuesta()

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
            # `problema=True` no es opcional aca: este es el UNICO aviso del
            # freno por perdida diaria, que rechaza todas las senales hasta el
            # dia siguiente. Callarlo hace que un dia frenado se vea igual que
            # un dia sin senales.
            await self._avisar(
                f"Senal RECHAZADA {event.symbol or '?'}\nMotivo: {decision.reason_text}",
                problema=True,
            )
            return {"status": "rechazada", "reasons": decision.reasons, "signal": event.to_dict()}

        take_profits = usable_take_profits(event)
        lot = self.settings.default_lot

        # Cuantas posiciones abre esta senal, y con que objetivo cada una.
        #
        # MT5 admite UN take profit por posicion. Perseguir los tres objetivos
        # que manda este canal exige, por lo tanto, tres operaciones: no hay
        # forma de expresarlo con una. Y el lote minimo (0.01) no se puede
        # partir, asi que cada una lleva DEFAULT_LOT entero y la senal pasa a
        # valer el triple. Eso es una decision de riesgo, no un detalle: por eso
        # vive en POSITIONS_PER_SIGNAL, arranca en 1, y se imprime al arrancar.
        objetivos = self._objetivos_de_apertura(take_profits)

        aperturas: list[dict[str, Any]] = []
        papers: list[dict[str, Any]] = []
        fallidas: list[str] = []
        ordenes_fallidas: list[dict[str, Any]] = []

        for indice, objetivo in enumerate(objetivos, start=1):
            trade_id = uuid.uuid4().hex[:12]
            etiqueta = f"TP{indice}" if objetivo is not None else "sin TP"

            # 1) Paper trade primero, siempre. Uno por posicion: son operaciones
            #    distintas, con tickets distintos y desenlaces distintos.
            #
            #    `take_profits` va COMPLETO en cada uno, no solo el objetivo de
            #    esta posicion. Es lo que permite que el informe diga "cerro en
            #    TP2": compara el precio de cierre contra los tres. Cual se le
            #    mando al broker queda aparte, en `tp_enviado`.
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
                "tp_enviado": objetivo,
                "signal": event.to_dict(),
            })
            papers.append(paper)

            # 2) Broker, solo si el modo lo permite.
            # Una excepcion aca cortaba la senal entera por el `except` general
            # de `_procesar`: con una posicion ya abierta, el mensaje quedaba
            # sin marcar como operado y la edicion siguiente la volvia a abrir.
            # Ahora es una posicion fallida, y "sin confirmar": pudo haber
            # entrado antes de fallar, asi que se la busca en la cuenta.
            try:
                order = await self._send_open(
                    event, lot, [objetivo] if objetivo is not None else []
                )
            except Exception as exc:
                logger.exception("Fallo al mandar la orden de %s (%s)", event.symbol, etiqueta)
                order = OrderResult(False, "open", f"error al mandar la orden: {exc}",
                                    symbol=event.symbol, lot=lot,
                                    raw={"sin_respuesta": True, "sin_confirmar": True})

            # Si el broker rechazo, NO se registra la posicion. Registrarla dejaria
            # una fantasma: existe en el estado y no en el broker, bloquea el
            # simbolo por la regla de "ya hay una posicion abierta" y ocupa cupo de
            # MAX_OPEN_TRADES, para siempre. El paper trade de arriba ya quedo
            # escrito, asi que la senal no se pierde.
            if order is not None and not order.ok:
                if order.raw.get("sin_confirmar"):
                    # order_send no contesto y la orden no aparecio todavia:
                    # pudo haber entrado. Se la sigue buscando; si aparece, se
                    # registra como esta posicion (`_confirmar_sin_respuesta`).
                    self._sin_confirmar.append({
                        "event": event, "trade_id": trade_id, "lot": lot,
                        "take_profits": take_profits, "indice": indice,
                        "objetivo": objetivo,
                        "hasta": datetime.now(timezone.utc) + BUSCAR_SIN_CONFIRMAR,
                    })
                fallidas.append(f"{etiqueta}: {order.reason}")
                ordenes_fallidas.append(order.to_dict())
                logger.error("El broker rechazo la apertura de %s (%s): %s",
                             event.symbol, etiqueta, order.reason)
                continue

            # 3) Estado. El ticket es el del broker si hubo, o el sintetico del
            #    paper broker, que igual sirve para atar cierres posteriores.
            #
            # El lote que se guarda es el que ACEPTO el broker, no el que se pidio.
            # `_normalize_volume` lo ajusta al paso y al minimo del instrumento, asi
            # que los dos numeros pueden diferir. Guardar el pedido dejaba al estado,
            # a los avisos y sobre todo a la matematica de los cierres parciales
            # trabajando sobre un lote que en MT5 no existe.
            lot_abierto = order.lot if (order is not None and order.lot) else lot
            position = self._nueva_posicion(event, trade_id, order, lot_abierto,
                                            take_profits, indice, objetivo)
            self.store.add_position(position)
            # Marcada y guardada YA, con la primera que entra: si algo corta la
            # senal despues, una edicion de este mensaje no la vuelve a abrir.
            if event.telegram_message_id is not None:
                self.store.marcar_que_opero(event.telegram_chat_id, event.telegram_message_id)
            self.store.save_state()
            aperturas.append({
                "trade_id": trade_id,
                "tp": objetivo,
                "etiqueta": etiqueta,
                "indice": indice if objetivo is not None else None,
                "lot": lot_abierto,
                # El dict es lo que va al registro; el objeto es lo que usa el
                # aviso. Guardar solo uno obliga a reconstruir el otro.
                "order": order.to_dict() if order else None,
                "order_obj": order,
                "paper_trade": paper,
            })

        # Ninguna entro: la senal no dejo una sola posicion abierta.
        if not aperturas:
            self.store.append_event("apertura_fallida", {
                "signal": event.to_dict(),
                # `order` en singular es lo que lee el informe; `orders` lleva
                # todas cuando la senal intento abrir mas de una.
                "order": ordenes_fallidas[0] if ordenes_fallidas else None,
                "orders": ordenes_fallidas,
            })
            motivo = fallidas[0].split(": ", 1)[-1] if fallidas else "sin motivo"
            sin_confirmar = any(o.get("raw", {}).get("sin_confirmar")
                                for o in ordenes_fallidas)
            await self._avisar(
                f"NO se pudo abrir {event.symbol}: {motivo}\n"
                + ("MetaTrader no confirmo: puede haber entrado. El bot la sigue\n"
                   "buscando y, si aparece, la toma bajo su gestion."
                   if sin_confirmar else
                   "La senal quedo registrada, pero no hay ninguna posicion."),
                problema=True,
            )
            return {
                "status": "apertura_fallida",
                "reason": motivo,
                "paper_trade": papers[0] if papers else None,
                "paper_trades": papers,
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
        #
        # Se cuenta UNA VEZ por senal, no una por posicion: tres posiciones
        # persiguiendo los tres TP de un mismo mensaje son una sola senal.
        self.store.bump_daily_counter()

        if event.telegram_message_id is not None:
            self.store.marcar_que_opero(event.telegram_chat_id, event.telegram_message_id)

        # UN evento "aceptada" por senal, no uno por posicion: el informe cuenta
        # estos eventos para decir cuantas senales se operaron, y escribir tres
        # haria que un dia de 4 senales se informara como 12.
        #
        # Pero el desenlace se lee POR TICKET, asi que los tickets van todos en
        # `orders`. `order` en singular se mantiene para no romper lo que ya
        # estaba escrito en el registro de antes de este cambio.
        self.store.append_event("aceptada", {
            "trade_id": aperturas[0]["trade_id"],
            "signal": event.to_dict(),
            "order": aperturas[0]["order"],
            "orders": [a["order"] for a in aperturas],
            "fallidas": fallidas,
            "warnings": event.warnings,
            # Ticket y TP de cada posicion. `orders` tiene los tickets en orden,
            # pero si falla una del medio ya no se sabe cual persigue que TP; el
            # informe usa esto para decir TP1, TP2 o TP3 sin adivinar.
            "aperturas": [
                {
                    "ticket": (a["order"] or {}).get("ticket"),
                    "tp_indice": a["indice"],
                    "tp": a["tp"],
                }
                for a in aperturas
            ],
        })

        # Una apertura que entro A MEDIAS avisa por su cuenta.
        #
        # Antes esto viajaba adentro del 'SENAL ACEPTADA' de mas abajo, que es
        # rutina, y una senal que abrio 2 de 3 posiciones quedaba invisible en
        # las tres salidas del sistema. El informe tampoco lo muestra:
        # `fallidas` se guarda en el evento pero nadie lo lee. Por eso va
        # aparte y marcado como problema, o sea WARNING en el log.
        #
        # No es un problema de plata -entra MENOS exposicion, no mas- sino de
        # dato: las tres posiciones existen para MEDIR cuantas veces el precio
        # llega al TP2 y al TP3. Un 2 de 3 invisible ensucia justo eso: el TP3
        # figura como 'no llego' cuando en realidad nunca se mando.
        if fallidas or event.warnings:
            await self._avisar(
                f"{event.symbol}: entraron {len(aperturas)} de {len(objetivos)} "
                "posicion(es).\n"
                + "\n".join(f"  {f}" for f in fallidas)
                + (("\n" + "; ".join(event.warnings)) if event.warnings else ""),
                problema=True,
            )

        await self._avisar(
            self._format_open(
                event, aperturas[0]["lot"], take_profits,
                aperturas[0]["order_obj"], precio_mercado,
                aperturas=aperturas, fallidas=fallidas,
            )
        )
        logger.info(
            "Senal aceptada %s %s en %d posicion(es) lote=%s tickets=%s",
            event.side.value if event.side else "?", event.symbol, len(aperturas),
            aperturas[0]["lot"],
            ", ".join(str((a["order"] or {}).get("ticket") or "-") for a in aperturas),
        )
        return {
            "status": "aceptada",
            "trade_id": aperturas[0]["trade_id"],
            "paper_trade": aperturas[0]["paper_trade"],
            "paper_trades": papers,
            "order": aperturas[0]["order"],
            "orders": [a["order"] for a in aperturas],
            "fallidas": fallidas,
            "signal": event.to_dict(),
        }

    def _objetivos_de_apertura(self, take_profits: list[float]) -> list[float | None]:
        """Que take profit lleva cada posicion que va a abrir esta senal.

        Devuelve una lista: un elemento por posicion. Con POSITIONS_PER_SIGNAL=1
        -el valor de fabrica- es exactamente lo de siempre, el TP mas cercano y
        una sola posicion.

        No se abren mas posiciones que TPs tenga la senal: una cuarta posicion
        sin objetivo propio no persigue nada, solo duplica exposicion.

        Y no se pasa de MAX_OPEN_TRADES. `evaluate_open` ya lo miro, pero mira
        si entra UNA; si quedaba un solo lugar libre y la senal quiere abrir
        tres, el techo se cruzaria igual. Recortar aca lo mantiene siendo un
        techo de verdad.
        """
        if not take_profits:
            return [None]

        cuantas = max(1, getattr(self.settings, "positions_per_signal", 1))
        cuantas = min(cuantas, len(take_profits))

        libres = self.settings.max_open_trades - len(self.store.open_positions())
        if libres > 0:
            cuantas = min(cuantas, libres)

        return list(take_profits[:cuantas])


    async def _send_open(
        self, event: SignalEvent, lot: float, take_profits: list[float]
    ) -> OrderResult | None:
        if not await self.broker.is_ready():
            return OrderResult(
                False, "open", f"Broker '{self.broker.name}' no esta listo", symbol=event.symbol
            )
        # MT5 admite un solo TP por posicion: se manda el mas cercano y los
        # demas quedan para gestionarse con los cierres parciales del grupo.
        async def mandar() -> OrderResult:
            return await self.broker.open_order(
                symbol=event.symbol or "",
                side=event.side or Side.BUY,
                order_type=event.order_type,
                lot=lot,
                entry=event.entry,
                stop_loss=event.stop_loss,
                take_profit=take_profits[0] if take_profits else None,
            )

        orden = await mandar()
        # Recotizacion: el precio se movio y el broker no ejecuto nada. Se
        # reintenta, pero solo si el precio NUEVO sigue pasando el filtro de
        # entrada tarde. Reintentar a ciegas (como se hacia dentro del broker)
        # abrio una entrada 4432 a 4440.5, con el tope en 0.05%: justo el caso
        # para el que el filtro existe, el precio moviendose rapido.
        for intento in range(1, REINTENTOS_POR_PRECIO + 1):
            if (orden is None or orden.ok or not orden.raw.get("recotizacion")
                    or event.order_type is not OrderType.MARKET):
                break
            precio = await self._precio_de_mercado(event.symbol)
            if precio is None:
                break  # sin precio no se puede volver a mirar el filtro
            motivos = motivos_por_distancia(self.settings, event, precio)
            if motivos:
                return OrderResult(
                    False, "open", f"El precio se movio mientras se abria: {motivos[0]}",
                    symbol=event.symbol, lot=orden.lot,
                    raw={"retcode": orden.raw.get("retcode"), "recotizacion": True},
                )
            logger.info("El broker pidio otro precio: reintento %s de %s con %s.",
                        intento, REINTENTOS_POR_PRECIO, precio)
            orden = await mandar()
        return orden

    # -- Gestion -----------------------------------------------------------

    async def _handle_close(self, event: SignalEvent) -> dict[str, Any]:
        # Lo que el broker ya cerro solo (TP, SL) no puede seguir contando: una
        # posicion fantasma volvia ambiguo el "mover TP" de la que sigue viva.
        await self._sincronizar_posiciones()
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
                # Un cierre total que el broker lleno a medias: la posicion
                # sigue, con menos lote. Se registra lo que quedo de verdad.
                restante = order.raw.get("restante")
                if restante is not None and position.lot:
                    position.remaining_fraction = round(float(restante) / position.lot, 4)
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
            await self._avisar(
                f"Cerradas {cerradas} de {len(targets)}. NO se pudieron cerrar:\n"
                + "\n".join(f"  {f}" for f in fallidas)
                + "\nSiguen abiertas y el bot las sigue teniendo en cuenta."
                + ya_estaban,
                problema=True,
            )
            return {"status": "cierre_parcial_fallido", "count": cerradas,
                    "fallidas": fallidas, "ausentes": ausentes, "orders": results}

        if ausentes:
            await self._avisar(f"Cerradas {cerradas} de {len(targets)}." + ya_estaban)
            return {"status": "cerrada", "count": cerradas,
                    "ausentes": ausentes, "orders": results}

        await self._avisar(f"Cerradas {cerradas} posicion(es): "
                           f"{', '.join(p.symbol for p in targets)}")
        return {"status": "cerrada", "count": cerradas, "orders": results}

    async def _handle_partial_close(self, event: SignalEvent) -> dict[str, Any]:
        # Lo que el broker ya cerro solo (TP, SL) no puede seguir contando: una
        # posicion fantasma volvia ambiguo el "mover TP" de la que sigue viva.
        await self._sincronizar_posiciones()
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
            await self._avisar(
                f"Cierre parcial {fraction:.0%}: salio en {aplicadas} de {len(targets)}.\n"
                "NO se pudo en:\n" + "\n".join(f"  {f}" for f in fallidas)
                + "\nEsas siguen abiertas enteras, y el bot las sigue contando asi.",
                problema=True,
            )
            return {"status": "cierre_parcial_fallido", "fraction": fraction,
                    "count": aplicadas, "fallidas": fallidas, "orders": results}

        await self._avisar(f"Cierre parcial {fraction:.0%} en {aplicadas} posicion(es)")
        return {"status": "cierre_parcial", "fraction": fraction, "orders": results}

    async def _handle_move_sl(self, event: SignalEvent) -> dict[str, Any]:
        # Lo que el broker ya cerro solo (TP, SL) no puede seguir contando: una
        # posicion fantasma volvia ambiguo el "mover TP" de la que sigue viva.
        await self._sincronizar_posiciones()
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
            # por eso se resuelve por posicion y no una sola vez. Y ese precio
            # es al que el broker lleno, no el que dijo el mensaje: ver
            # `_destino_del_stop`, que es donde vive el motivo.
            new_sl = _destino_del_stop(
                position, event, self.settings.breakeven_uses_real_entry
            )
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

            # Y el que la escala NO puede ver: dos posiciones del MISMO
            # instrumento. El breakeven de una senal le llega a la otra —este
            # canal opera solo oro y manda un MOVER SL detras de cada senal— y
            # le ALEJA el stop. Ver `stop_agranda_el_riesgo`, que tiene los
            # numeros medidos.
            motivo = stop_agranda_el_riesgo(
                position.side, position.stop_loss, new_sl, hay_varias=len(targets) > 1
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
                if order.raw.get("retcode") == STOPS_INVALIDOS:
                    # El broker exige una distancia minima entre el precio y el
                    # stop: un breakeven con el precio todavia cerca de la
                    # entrada se rechaza, y despues nadie lo volvia a pedir. La
                    # posicion quedaba con el stop original (a 0.05, unos 50
                    # dolares por stop de 10 puntos). El vigilante lo reintenta
                    # cada 30 s, hasta que entre o la posicion cierre.
                    self._sl_pendientes[position.trade_id] = new_sl
                    fallidas.append(f"{position.symbol}: {order.reason} (se reintenta solo "
                                    "cada 30 s, cuando el precio se aleje)")
                    continue
                fallidas.append(f"{position.symbol}: {order.reason}")
                continue
            movidas += 1
            self._sl_pendientes.pop(position.trade_id, None)
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
        # El aviso dice breakeven tambien cuando el canal lo escribio como numero:
        # "SL movido a 4467" y "SL movido a breakeven" describen lo mismo, y el
        # segundo es el que se entiende desde el telefono.
        fue_breakeven = event.move_sl_to_breakeven or any(
            p.entry is not None
            and event.stop_loss is not None
            and _mismo_precio(event.stop_loss, p.entry)
            for p in targets
        )
        destino = "breakeven" if fue_breakeven else str(event.stop_loss)
        problemas = fallidas + descartadas

        # `results` incluye los rechazos, asi que contarlos como movidas decia
        # "SL movido en 1 posicion(es)" con el broker habiendo rechazado todo.
        # El estado ya estaba bien; lo que mentia era el aviso, que es lo unico
        # que la persona ve desde el telefono. Creerte protegido en breakeven
        # cuando el stop sigue donde estaba es peor que no recibir el aviso.
        if problemas:
            await self._avisar(
                f"SL a {destino}: salio en {movidas} de {len(problemas) + movidas}.\n"
                "NO se pudo mover en:\n" + "\n".join(f"  {p}" for p in problemas)
                + "\nEsas posiciones siguen con el stop anterior.",
                problema=True,
            )
            return {"status": "sl_movido_parcial", "count": movidas,
                    "fallidas": fallidas, "descartadas": descartadas,
                    "orders": results}

        await self._avisar(f"SL movido a {destino} en {movidas} posicion(es)")
        return {"status": "sl_movido", "count": movidas, "orders": results}

    async def _handle_move_tp(self, event: SignalEvent) -> dict[str, Any]:
        """Mueve el take profit, pero SOLO de las posiciones que persiguen el TP1.

        LA REGLA, COMO SE PIDIO
        -----------------------
        Si el canal manda "mover TP a X", se mueve el TP de la posicion que
        persigue el TP1, y las del TP2 y el TP3 se quedan donde estaban. Y todo
        queda registrado -cual se movio, de donde a donde, y por que las otras
        no- para poder revisarlo en el informe.

        Con POSITIONS_PER_SIGNAL=1 hay una sola posicion por senal y es la del
        TP1, asi que se mueve. Con 3, se mueve una de las tres.

        LO QUE NO SE MUEVE AUNQUE PERSIGA EL TP1
        ----------------------------------------
        - Una posicion abierta antes de que existiera `tp_indice`: no se sabe
          que TP perseguia, y adivinar podria mover el de la del TP3.
        - Un TP del lado equivocado: en un BUY va arriba del precio, en un SELL
          abajo. MT5 lo rechazaria igual, pero asi queda registrado con
          palabras y no con un numero de retcode.
        - Un TP que no da la escala del instrumento, como con el stop: un
          "mover TP a 4450" sin simbolo le llegaria tambien a un EURUSD.
        """
        # Lo que el broker ya cerro solo (TP, SL) no puede seguir contando: una
        # posicion fantasma volvia ambiguo el "mover TP" de la que sigue viva.
        await self._sincronizar_posiciones()
        decision, targets = evaluate_management(self.settings, self.store, event)
        if not decision.ok:
            self.store.append_event(
                "gestion_rechazada", {"signal": event.to_dict(), "reasons": decision.reasons}
            )
            return {"status": "rechazada", "reasons": decision.reasons}

        nuevo_tp = event.take_profits[0]
        movidas: list[dict[str, Any]] = []
        no_movidas: list[dict[str, Any]] = []
        fallidas: list[str] = []
        results: list[dict[str, Any]] = []

        # Primero: a cuantas posiciones les podria corresponder este TP.
        #
        # Con POSITIONS_PER_SIGNAL=1 TODAS las posiciones persiguen el TP1, asi
        # que con dos senales abiertas "la del TP1" no identifica a ninguna. Un
        # "mover TP a 4470" sin simbolo se aplicaba a las dos, y la que buscaba
        # +3.5 puntos pasaba a buscar +37.5: una ganancia chica probable
        # convertida en una moneda al aire, y el lugar ocupado mientras tanto.
        #
        # El usuario eligio que en ese caso NO se mueva ninguna y se le avise
        # (2026-09-16). No hay forma de saber desde el mensaje de cual habla, y
        # adivinar es peor que preguntar. Se cuentan solo las que de verdad
        # podrian recibirlo -mismo filtro que el de abajo-: si una es de otra
        # escala o el TP le quedaria del lado equivocado, no hay ambiguedad.
        motivos = {
            position.trade_id: await self._motivo_para_no_mover_tp(position, nuevo_tp)
            for position in targets
        }
        candidatas = [p for p in targets if motivos[p.trade_id] is None]

        if len(candidatas) > 1:
            return await self._tp_ambiguo(event, nuevo_tp, targets, candidatas, motivos)

        for position in targets:
            ficha = {
                "trade_id": position.trade_id,
                "ticket": position.broker_ticket,
                "symbol": position.symbol,
                "tp_indice": position.tp_indice,
                "tp_actual": position.tp_objetivo,
            }

            motivo = motivos[position.trade_id]
            if motivo is not None:
                no_movidas.append({**ficha, "motivo": motivo})
                continue

            order = await self.broker.modify_take_profit(
                ticket=position.broker_ticket, symbol=position.symbol, take_profit=nuevo_tp
            )
            results.append(order.to_dict())
            if not order.ok:
                if self._reconciliar_ausente(position, order):
                    no_movidas.append({**ficha, "motivo": (
                        "ya no existia en el broker, se saco del estado"
                    )})
                    continue
                logger.error("No se pudo mover el TP de %s: %s", position.symbol, order.reason)
                fallidas.append(f"{position.symbol} TP1: {order.reason}")
                continue

            anterior = position.tp_objetivo
            position.tp_objetivo = nuevo_tp
            movidas.append({**ficha, "tp_anterior": anterior, "tp_nuevo": nuevo_tp})
            self.store.append_paper_trade({
                "trade_id": position.trade_id,
                "status": "PAPER_TP_MOVED",
                "symbol": position.symbol,
                "tp_indice": position.tp_indice,
                "tp_anterior": anterior,
                "tp_nuevo": nuevo_tp,
                "order": order.to_dict(),
                "signal": event.to_dict(),
            })

        self.store.append_event("mover_tp", {
            "signal": event.to_dict(),
            "tp_nuevo": nuevo_tp,
            "movidas": movidas,
            "no_movidas": no_movidas,
            "fallidas": fallidas,
            "orders": results,
        })

        if fallidas:
            await self._avisar(
                f"TP1 a {nuevo_tp}: NO se pudo mover en:\n"
                + "\n".join(f"  {f}" for f in fallidas)
                + "\nEsas posiciones siguen con el TP anterior.",
                problema=True,
            )
            return {"status": "tp_movido_parcial", "movidas": movidas,
                    "no_movidas": no_movidas, "fallidas": fallidas, "orders": results}

        await self._avisar(
            f"TP1 movido a {nuevo_tp} en {len(movidas)} posicion(es). "
            f"Sin mover: {len(no_movidas)}."
        )
        return {"status": "tp_movido", "movidas": movidas,
                "no_movidas": no_movidas, "orders": results}

    async def _motivo_para_no_mover_tp(self, position, nuevo_tp: float) -> str | None:
        """Por que ESTA posicion no puede recibir este TP, o None si puede.

        Es un solo filtro para dos preguntas: cuales se mueven, y cuantas
        candidatas hay antes de decidir si el mensaje es ambiguo. Si fueran dos
        copias, tarde o temprano dirian cosas distintas.
        """
        if position.tp_indice is None:
            return ("no se sabe que TP perseguia (se abrio antes de que se "
                    "registrara ese dato)")
        if position.tp_indice != 1:
            return f"persigue el TP{position.tp_indice}: solo se mueve el TP1"

        precio = await self._precio_de_mercado(position.symbol)
        if stop_fuera_de_escala(nuevo_tp, precio) is not None:
            return (f"el TP {nuevo_tp} no da la escala del precio de "
                    f"{position.symbol} ({precio})")
        if precio is not None:
            compra = (position.side or "").upper() == "BUY"
            if (compra and nuevo_tp <= precio) or (not compra and nuevo_tp >= precio):
                lado = "arriba" if compra else "abajo"
                return (f"el TP {nuevo_tp} quedaria del lado equivocado: en un "
                        f"{position.side} tiene que ir {lado} del precio ({precio})")
        return None

    async def _tp_ambiguo(self, event, nuevo_tp, targets, candidatas, motivos):
        """No se mueve ninguna: el mensaje no dice de cual posicion habla.

        Se registra igual que un movimiento -con todas en `no_movidas`- para que
        el informe lo vea, y se deja dicho como PROBLEMA -WARNING en el log-,
        que es como se encuentra despues que el canal pidio algo que el bot no
        hizo.
        """
        motivo_ambiguo = (
            f"hay {len(candidatas)} posiciones que podrian recibir ese TP y el "
            "mensaje no dice de cual habla"
        )
        no_movidas = [
            {
                "trade_id": p.trade_id,
                "ticket": p.broker_ticket,
                "symbol": p.symbol,
                "tp_indice": p.tp_indice,
                "tp_actual": p.tp_objetivo,
                "motivo": motivos[p.trade_id] or motivo_ambiguo,
            }
            for p in targets
        ]
        self.store.append_event("mover_tp", {
            "signal": event.to_dict(),
            "tp_nuevo": nuevo_tp,
            "ambiguo": True,
            "movidas": [],
            "no_movidas": no_movidas,
            "fallidas": [],
            "orders": [],
        })

        lineas = []
        for p in candidatas:
            entrada = p.entry_real or p.entry
            lineas.append(f"  {p.symbol} {p.side} entrada {entrada}, TP {p.tp_objetivo}")
        await self._avisar(
            f"NO se movio el TP a {nuevo_tp}: hay {len(candidatas)} operaciones "
            "abiertas que podrian recibirlo y el mensaje no dice de cual habla.\n"
            + "\n".join(lineas)
            + "\nTodas siguen con su TP de antes. Si querias moverlo, hacelo a "
            "mano en MetaTrader.",
            problema=True,
        )
        return {"status": "tp_ambiguo", "movidas": [], "no_movidas": no_movidas,
                "orders": []}

    async def _handle_update(self, event: SignalEvent, avisar: bool = True) -> dict[str, Any]:
        """Modificacion suelta (SL/TP sin lado).

        No se ejecuta automaticamente: sin direccion ni simbolo no hay forma
        segura de saber a que posicion aplica. Se registra y se avisa para que
        la persona decida.
        """
        self.store.append_event("actualizacion", {"signal": event.to_dict()})
        if avisar:
            await self._avisar(
                "Llego una modificacion que no se pudo aplicar sola (sin simbolo o sin "
                f"direccion):\n{event.raw_message[:300]}",
                problema=True,
            )
        return {"status": "actualizacion_registrada", "signal": event.to_dict()}

    async def fijar_referencia_del_dia(self) -> None:
        """Toma el valor de la cuenta al arrancar, antes de la primera senal.

        El freno diario promete medir contra "el saldo con el que abrio el
        dia". Si la referencia se tomara con el primer mensaje que llega, seria
        el saldo de ese momento: horas mas tarde y, con posiciones abiertas de
        la noche anterior, varios dolares mas abajo. La perdida de ese tramo
        quedaria afuera de la cuenta del dia.
        """
        await self._actualizar_equity()

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
            # Sin dato no se rechaza nada, pero TAMPOCO se sigue usando el
            # anterior. Antes esto era un `return` pelado y `balance_actual`
            # conservaba la lectura vieja: con la terminal caida mientras la
            # cuenta bajaba, el freno comparaba contra un numero de hace horas
            # y daba por bueno un dia que ya se habia pasado del tope.
            logger.warning("No se pudo leer el equity de la cuenta", exc_info=True)
            self.store.balance_actual = None
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

    async def _sincronizar_posiciones(self) -> None:
        """Saca del estado las posiciones que el broker ya cerro por su cuenta.

        POR QUE HACE FALTA
        ------------------
        El canal de senales no manda mensajes de cierre: las operaciones
        terminan solas en el TP o en el SL. El broker las cierra y no se lo
        avisa a nadie, con lo cual el estado queda diciendo que siguen
        abiertas.

        La consecuencia no es cosmetica. La regla de "ya hay una posicion
        abierta en X" es una proteccion buena, pero medida contra una posicion
        que ya no existe rechaza la senal SIGUIENTE de ese instrumento. Con un
        canal que opera un solo simbolo, eso significa perder casi una senal de
        cada dos: se toma una, la siguiente se rechaza, la de mas alla se toma.

        Antes esto se reconciliaba solo de rebote, cuando llegaba un mensaje de
        gestion y el broker contestaba que la posicion no existia. Depender de
        eso es depender de que el canal mande un mensaje que puede no mandar.

        Se respeta la diferencia entre "no esta" y "no pude preguntar": solo un
        False del broker saca la posicion del estado. Un None la deja donde
        esta, porque darla por cerrada sin saberlo la soltaria del registro
        estando viva.
        """
        abiertas = self.store.open_positions()
        if not abiertas:
            return

        cerradas = []
        for position in list(abiertas):
            try:
                existe = await self.broker.posicion_existe(position.broker_ticket)
            except Exception:
                logger.warning(
                    "No se pudo verificar la posicion %s", position.symbol, exc_info=True
                )
                continue
            if existe is False:
                self.store.remove_position(position.trade_id)
                cerradas.append(position)

        if not cerradas:
            return

        for position in cerradas:
            self.store.append_event("cerrada_en_el_broker", {
                "trade_id": position.trade_id,
                "symbol": position.symbol,
                "side": position.side,
                "entry": position.entry,
                "stop_loss": position.stop_loss,
                "take_profits": position.take_profits,
            })
            logger.info(
                "%s ya no esta abierta en el broker (TP, SL o cierre a mano). "
                "Se saca del estado y el simbolo queda libre.", position.symbol,
            )

        await self._avisar(
            "Se cerraron solas en el broker (TP, SL o a mano):\n"
            + "\n".join(f"  {p.symbol} {p.side} entrada {p.entry}" for p in cerradas)
            + "\nEsos simbolos quedan libres para la proxima senal."
        )

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

    def _ia_de_fondo(self, text: str, metadata: dict[str, Any]) -> None:
        """Consulta a la IA sin hacer esperar a las senales que vienen detras."""
        tarea = asyncio.create_task(self._sugerencia_de_la_ia(text, dict(metadata)))
        # Asyncio guarda las tareas con una referencia debil: sin esto, una
        # puede desaparecer a mitad de camino.
        self._tareas_ia.add(tarea)
        tarea.add_done_callback(self._tareas_ia.discard)

    async def _sugerencia_de_la_ia(self, text: str, metadata: dict[str, Any]) -> None:
        interpretado = await self._consultar_ia(text, metadata)
        if interpretado is None or not _interpretacion_utilizable(interpretado):
            return
        # Solo el registro toma el turno, y dura milisegundos.
        async with self._turno:
            self.store.append_event("ia_sugerencia", {"signal": interpretado.to_dict()})
            self.store.save_state()
        await self._avisar(self._format_sugerencia_ia(interpretado), problema=True)
        logger.info(
            "La IA interpreto un mensaje que el parser no entendio (%s %s). "
            "Solo se aviso, no se opero.",
            interpretado.event_type.value, interpretado.symbol or "?",
        )

    async def revisar_el_broker(self) -> None:
        """Para el vigilante de `tct run`: si MetaTrader se reinicio, reconecta.

        Con el turno tomado, para no hablarle a la terminal a la vez que una
        orden: el paquete MetaTrader5 es un solo canal.
        """
        revisar = getattr(self.broker, "revisar_conexion", None)
        if revisar is None and not self._sin_confirmar and not self._sl_pendientes:
            return
        async with self._turno:
            if revisar is not None:
                await revisar()
            if self._sin_confirmar:
                await self._confirmar_sin_respuesta()
                self.store.save_state()
            if self._sl_pendientes:
                await self._reintentar_stops()
                self.store.save_state()

    async def _reintentar_stops(self) -> None:
        """Vuelve a pedir los stops que el broker rechazo por distancia minima."""
        abiertas = {p.trade_id: p for p in self.store.open_positions()}
        for trade_id, nuevo in list(self._sl_pendientes.items()):
            position = abiertas.get(trade_id)
            if position is None:
                self._sl_pendientes.pop(trade_id, None)  # ya cerro
                continue
            order = await self.broker.modify_stop_loss(
                ticket=position.broker_ticket, symbol=position.symbol, stop_loss=nuevo)
            if order.ok:
                self._sl_pendientes.pop(trade_id, None)
                antes, position.stop_loss = position.stop_loss, nuevo
                self.store.append_event("sl_movido_al_reintentar", {
                    "trade_id": trade_id, "antes": antes, "despues": nuevo})
                await self._avisar(f"El SL de {position.symbol} que el broker habia rechazado "
                                   f"por distancia minima ya entro: {antes} -> {nuevo}.")
            elif order.raw.get("ausente"):
                self._sl_pendientes.pop(trade_id, None)
            elif order.raw.get("retcode") != STOPS_INVALIDOS:
                # Otro motivo: no se insiste para siempre con algo que no es
                # la distancia. Ya se aviso cuando fallo la primera vez.
                self._sl_pendientes.pop(trade_id, None)

    async def reconciliar_al_arrancar(self) -> None:
        """Toma bajo gestion las posiciones del bot que el registro no conoce.

        POR QUE
        -------
        Al arrancar nunca se comparaba el registro con MetaTrader. Si el
        state.json se perdia (corte de luz, archivo ilegible) o quedo atras
        (el bot murio entre la orden y el guardado), las posiciones vivas del
        bot quedaban huerfanas: sin breakeven, sin cierre, y fuera de los
        topes (llegaron a quedar 4 de 0.05 con MAX_OPEN_TRADES=2). Se
        reconocen por la marca del bot (MAGIA); lo que abriste a mano no.
        """
        listar = getattr(self.broker, "posiciones_propias", None)
        if listar is None:
            return
        async with self._turno:
            await self._sincronizar_posiciones()
            try:
                vivas = await listar()
            except Exception:
                logger.warning("No se pudo revisar la cuenta al arrancar", exc_info=True)
                return
            if not vivas:
                return
            conocidos = {p.broker_ticket for p in self.store.open_positions()
                         if p.broker_ticket is not None}
            nuevas = [v for v in vivas if v["ticket"] not in conocidos]
            for viva in nuevas:
                tp = viva.get("tp") or None
                self.store.add_position(OpenPosition(
                    trade_id=uuid.uuid4().hex[:12],
                    symbol=viva["symbol"],
                    side=viva["side"],
                    lot=viva["lot"],
                    entry=viva.get("price"),
                    stop_loss=viva.get("sl") or None,
                    take_profits=[tp] if tp else [],
                    opened_at=utc_now_iso(),
                    signal_message_id=None,
                    broker_ticket=viva["ticket"],
                    mode=self.settings.trading_mode,
                    entry_real=viva.get("price"),
                    tp_indice=1 if tp else None,
                    tp_objetivo=tp,
                ))
            if not nuevas:
                return
            self.store.append_event("adoptadas_al_arrancar", {"posiciones": nuevas})
            self.store.save_state()
        await self._avisar(
            "Al arrancar habia posiciones del bot que el registro no tenia (se perdio "
            "o quedo atras el estado). Ahora las gestiona el bot:\n"
            + "\n".join(f"  {v['symbol']} {v['side']} {v['lot']} ticket {v['ticket']}"
                         + (" (pendiente)" if v.get("pendiente") else "")
                         for v in nuevas),
            problema=True,
        )

    async def _corregir_sl(self, event: SignalEvent, message_id: Any) -> dict[str, Any] | None:
        """El canal edito una senal que ya abrio y cambio el SL: se aplica.

        Solo a las posiciones de ESA senal, solo si el lado y el simbolo son
        los mismos (si no, no es una correccion del SL sino otra cosa), y solo
        si el SL nuevo queda del lado correcto de la entrada. None si no hay
        nada que corregir: el que llama sigue como antes (edicion ignorada).
        """
        propias = [p for p in self.store.open_positions()
                   if p.signal_message_id == message_id]
        nuevo = event.stop_loss
        if (not propias or nuevo is None
                or any(p.symbol != (event.symbol or "").upper()
                       or p.side != (event.side.value if event.side else "")
                       for p in propias)):
            return None
        a_corregir = [p for p in propias
                      if p.stop_loss is None or abs(p.stop_loss - nuevo) > 1e-9]
        if not a_corregir:
            return None
        entrada = propias[0].entry_real or propias[0].entry
        del_lado_correcto = entrada is None or (
            nuevo < entrada if event.side is Side.BUY else nuevo > entrada)
        if not del_lado_correcto:
            await self._avisar(
                f"El canal corrigio el SL de {event.symbol} a {nuevo}, pero queda del lado "
                f"equivocado de la entrada ({entrada}). NO se aplico: revisalo a mano.",
                problema=True,
            )
            return {"status": "correccion_rechazada", "signal": event.to_dict()}
        hechas, fallidas = [], []
        for position in a_corregir:
            antes = position.stop_loss
            order = await self.broker.modify_stop_loss(
                ticket=position.broker_ticket, symbol=position.symbol, stop_loss=nuevo)
            if order.ok or order.raw.get("retcode") == 10025:
                position.stop_loss = nuevo
                hechas.append(f"{position.symbol} {antes} -> {nuevo}")
            else:
                fallidas.append(f"{position.symbol}: {order.reason}")
        self.store.append_event("sl_corregido", {
            "signal": event.to_dict(), "hechas": hechas, "fallidas": fallidas})
        await self._avisar(
            "El canal CORRIGIO el SL de una senal ya abierta:\n"
            + "\n".join(f"  {h}" for h in hechas)
            + ("\nNO se pudo en:\n" + "\n".join(f"  {f}" for f in fallidas)
               if fallidas else ""),
            problema=bool(fallidas),
        )
        return {"status": "sl_corregido", "hechas": hechas, "fallidas": fallidas,
                "signal": event.to_dict()}

    async def _confirmar_sin_respuesta(self) -> None:
        """Busca en la cuenta las ordenes que order_send no confirmo.

        POR QUE
        -------
        El caso tipico de un order_send sin respuesta es que MetaTrader se
        reinicio justo al mandar. La orden pudo haber entrado, y sin esto
        quedaba una posicion real que el bot no gestionaba (sin breakeven, sin
        cierre) y que no contaba para MAX_OPEN_TRADES: con tope 2 llegaron a
        quedar 3 abiertas. Se busca antes de cada senal y en cada vuelta del
        vigilante (30 s), durante `BUSCAR_SIN_CONFIRMAR`.
        """
        buscar = getattr(self.broker, "buscar_sin_registrar", None)
        if buscar is None or not self._sin_confirmar:
            return
        ahora = datetime.now(timezone.utc)
        for pendiente in list(self._sin_confirmar):
            event = pendiente["event"]
            conocidos = {p.broker_ticket for p in self.store.open_positions()
                         if p.broker_ticket is not None}
            try:
                order = await buscar(symbol=event.symbol or "",
                                     side=event.side or Side.BUY, conocidos=conocidos)
            except Exception:
                logger.warning("No se pudo buscar la orden sin confirmar", exc_info=True)
                continue
            if order is None:
                if ahora > pendiente["hasta"]:
                    self._sin_confirmar.remove(pendiente)
                    logger.info("La orden de %s que no se confirmo no aparecio: no entro.",
                                event.symbol)
                continue
            self._sin_confirmar.remove(pendiente)
            position = self._nueva_posicion(
                event, pendiente["trade_id"], order, order.lot or pendiente["lot"],
                pendiente["take_profits"], pendiente["indice"], pendiente["objetivo"])
            self.store.add_position(position)
            self.store.append_event("apertura_confirmada_tarde", {
                "signal": event.to_dict(), "order": order.to_dict(),
                "trade_id": pendiente["trade_id"],
            })
            await self._avisar(
                f"La orden de {event.symbol} que MetaTrader no confirmo SI entro "
                f"(ticket {order.ticket}). Ahora la gestiona el bot.",
                problema=True,
            )

    def _nueva_posicion(self, event: SignalEvent, trade_id: str, order: OrderResult | None,
                        lot: float, take_profits: list[float], indice: int,
                        objetivo: float | None) -> OpenPosition:
        return OpenPosition(
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
            # El precio al que el broker lleno DE VERDAD. Es lo que despues
            # convierte un "MOVER SL A <la entrada>" en un breakeven real y
            # no en una perdida del tamano del spread.
            entry_real=order.price if order else None,
            # Que TP de la senal persigue esta posicion y el que tiene
            # puesto. Hace falta para "mover TP": se mueve solo la del TP1,
            # y sin este dato no hay forma de saber cual es.
            tp_indice=indice if objetivo is not None else None,
            tp_objetivo=objetivo,
        )

    async def esperar_la_ia(self) -> None:
        """Espera las consultas a la IA que quedaron de fondo (tests, cierre)."""
        while self._tareas_ia:
            await asyncio.gather(*list(self._tareas_ia), return_exceptions=True)

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

    async def _avisar(self, text: str, *, problema: bool = False) -> None:
        """Deja constancia de lo que el bot hizo o no pudo hacer. VA AL LOG.

        Antes esto mandaba un mensaje por Telegram. El usuario pidio que el bot
        no le escriba nunca —"solo quiero que lea los mensajes del telegram y
        lo haga"— asi que el sistema de avisos se saco del proyecto. Lo que NO
        se saco es lo que esos avisos decian: son la unica constancia de varias
        cosas que no quedan en ningun otro lado, y tirarlas habria sido cambiar
        "no me escribas" por "no me entero".

        `problema=True` marca lo que NO se hizo: una senal rechazada, una orden
        que el broker no acepto, un stop que no se pudo mover. Esos van como
        WARNING, para poder encontrarlos en el log sin leerlo entero. El resto
        es rutina y va como INFO.

        Donde se leen: la ventana del bot mientras corre, y el archivo que
        indica LOG_PATH en el .env. Lo que paso con cada senal, ademas, queda
        en el registro y se mira con `tct informe`.
        """
        if problema:
            logger.warning(text)
        else:
            logger.info(text)

    def _format_open(
        self,
        event: SignalEvent,
        lot: float,
        take_profits: list[float],
        order: OrderResult | None,
        precio_mercado: float | None = None,
        aperturas: list[dict[str, Any]] | None = None,
        fallidas: list[str] | None = None,
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

        # Con una sola posicion el aviso queda exactamente como siempre. Las
        # lineas de abajo solo aparecen cuando la senal abrio varias, que es
        # cuando hace falta ver el tamano total: tres veces el lote es tres
        # veces el riesgo, y eso tiene que estar en el aviso y no en el estado
        # de cuenta del dia siguiente.
        if aperturas and len(aperturas) > 1:
            total = round(sum(a["lot"] for a in aperturas), 4)
            lines.append(f"Abiertas: {len(aperturas)} posiciones, {total} de lote en total")
            for apertura in aperturas:
                ticket = (apertura["order"] or {}).get("ticket") or "-"
                lines.append(
                    f"  {apertura['etiqueta']} -> {apertura['tp']}  "
                    f"lote {apertura['lot']}  ticket {ticket}"
                )
        if fallidas:
            lines.append("NO se pudieron abrir:")
            lines.extend(f"  {f}" for f in fallidas)
        if event.warnings:
            lines.append("Avisos  : " + "; ".join(event.warnings))
        return "\n".join(lines)
