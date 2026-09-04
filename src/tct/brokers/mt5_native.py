"""Broker MT5 nativo. SOLO Windows, y el camino recomendado ahi.

En Windows se habla directo con la terminal MT5 instalada en la maquina, sin
intermediarios ni servicios de terceros: menos latencia, menos piezas que
puedan fallar y nada que pagar. Es el motivo por el que conviene una PC
Windows dedicada antes que una Mac.

Fuera de Windows este modulo no puede funcionar: el paquete `MetaTrader5` solo
publica wheels `win_amd64`. `config.py` bloquea el modo con un mensaje claro y
en macOS el camino es MetaApi.

La logica dificil (negociacion de filling mode, normalizacion de volumen,
validacion de cuenta demo) esta portada de `app/brokers/mt5_demo_trader.py`
de tradingalertaIA, que ya la tenia resuelta contra brokers reales.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from tct.brokers.base import Broker, OrderResult
from tct.brokers.symbol_map import to_broker_symbol
from tct.signals.models import OrderType, Side

logger = logging.getLogger(__name__)

# Otros nombres con los que un broker puede bautizar al mismo instrumento.
# Se prueban despues del nombre canonico, cuando la busqueda exacta falla.
_ALIAS_DE_BROKER: dict[str, tuple[str, ...]] = {
    "XAUUSD": ("GOLD", "XAUUSD.", "GOLDUSD"),
    "XAGUSD": ("SILVER", "SILVERUSD"),
    "NAS100": ("USTEC", "US100", "NDX100", "NASDAQ100", "TECH100", "USTECH"),
    "US30": ("DJ30", "DOW30", "WS30", "USA30", "DJIUSD"),
    "US500": ("SPX500", "SP500", "USA500", "US500Cash"),
    "GER40": ("DE40", "GER30", "DAX40", "DE30"),
    "UK100": ("FTSE100", "UKX", "GB100"),
    "USOIL": ("XTIUSD", "WTI", "CRUDOIL", "OIL"),
    "UKOIL": ("XBRUSD", "BRENT"),
    "BTCUSD": ("BITCOIN", "BTCUSDT"),
    "ETHUSD": ("ETHEREUM", "ETHUSDT"),
}


def _volumen_confirmado(result: Any, pedido: float) -> float:
    """El volumen que el broker dice haber ejecutado, o el pedido si no lo dice.

    `OrderSendResult.volume` es el volumen CONFIRMADO por el broker, y no tiene
    por que coincidir con el solicitado: un llenado parcial ejecuta menos. El
    motor arma el estado con este numero, asi que informar el pedido lo dejaba
    creyendo tener abierto mas de lo que hay, y calculando los cierres
    parciales sobre un lote que no existe.
    """
    ejecutado = getattr(result, "volume", None)
    try:
        ejecutado = float(ejecutado) if ejecutado is not None else 0.0
    except (TypeError, ValueError):
        ejecutado = 0.0
    return ejecutado or float(pedido)


# Codigo que devuelve MT5 cuando no pudo lanzar la terminal. Es el unico que
# apunta a un problema de RUTA y no de estado de la terminal.
_IPC_INITIALIZE_FAILED = -10003


def _pistas_de_initialize(codigo: int, mt5_path: str) -> list[str]:
    """Que hacer ante un initialize() fallido, en castellano y accionable.

    El mensaje crudo de MT5 nombra funciones internas ("IPC initialize failed")
    y no sugiere nada. Quien lo lee no programa: necesita saber que apretar, no
    como se llama la capa que fallo.
    """
    if codigo == _IPC_INITIALIZE_FAILED:
        if mt5_path:
            return [
                "No se pudo ARRANCAR MetaTrader desde esa ruta.",
                "Casi siempre la ruta esta mal escrita, o MetaTrader se instalo",
                "en otra carpeta. Para encontrar la verdadera: clic derecho en el",
                "acceso directo de MetaTrader 5 -> Propiedades -> 'Destino'.",
                "O directamente dejá MT5_PATH vacio en el .env y abri MetaTrader",
                "a mano antes de arrancar el bot.",
            ]
        return [
            "No se encontro ninguna terminal MetaTrader 5 para arrancar.",
            "Abri MetaTrader 5 a mano y volve a intentar, o completá MT5_PATH",
            "en el .env con la ruta a terminal64.exe.",
        ]

    return [
        "Casi siempre es una de estas tres:",
        "  1. MetaTrader 5 no esta abierto. Abrilo.",
        "  2. Esta abierto pero sin loguear en ninguna cuenta.",
        "  3. Se abrio 'como administrador' y el bot no. Los dos tienen que",
        "     correr con el mismo nivel de permisos.",
    ]


class MT5NativeBroker(Broker):
    name = "mt5"

    def __init__(self, settings) -> None:
        self.settings = settings
        self._mt5 = None
        self._ready = False
        # Cache de simbolo canonico -> nombre real en este broker. None como
        # valor significa "ya se busco y no existe": evita repetir el barrido.
        self._symbol_cache: dict[str, str | None] = {}

    # -- Ciclo de vida -----------------------------------------------------

    async def connect(self) -> bool:
        return await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> bool:
        try:
            import MetaTrader5 as mt5
        except ImportError:
            logger.error(
                "El paquete MetaTrader5 no esta instalado. Solo existe para Windows; "
                "en macOS usa TRADING_MODE=PAPER_ONLY o PAPER_AND_METAAPI_DEMO."
            )
            return False

        self._mt5 = mt5
        kwargs: dict[str, Any] = {}
        if self.settings.mt5_path:
            # Se verifica ANTES de llamar a initialize(), porque el error que
            # devuelve MT5 cuando la ruta no existe es
            #     (-10003, "IPC initialize failed, Process create failed '<ruta>'")
            # que no dice que el problema sea la ruta, ni que la ruta salga del
            # .env, ni que se pueda dejar vacia. Una sola letra de menos en el
            # nombre de la carpeta ("MetaTrade 5") produce exactamente eso.
            if not Path(self.settings.mt5_path).exists():
                logger.error(
                    "MT5_PATH apunta a un archivo que no existe:\n"
                    "            %s\n"
                    "        Corregilo en el .env, o dejalo VACIO (MT5_PATH=) y abri\n"
                    "        MetaTrader 5 a mano antes de arrancar el bot: sin ruta, se\n"
                    "        conecta a la terminal que ya este abierta y no hace falta\n"
                    "        acertarle a la ruta.",
                    self.settings.mt5_path,
                )
                return False
            kwargs["path"] = self.settings.mt5_path

        if not mt5.initialize(**kwargs):
            codigo, mensaje = mt5.last_error()
            logger.error("mt5.initialize() fallo: %s (codigo %s)", mensaje, codigo)
            for linea in _pistas_de_initialize(codigo, self.settings.mt5_path):
                logger.error("        %s", linea)
            return False

        if self.settings.mt5_login and self.settings.mt5_password and self.settings.mt5_server:
            try:
                login = int(self.settings.mt5_login)
            except ValueError:
                logger.error("MT5_LOGIN tiene que ser numerico")
                return False
            if not mt5.login(
                login, password=self.settings.mt5_password, server=self.settings.mt5_server
            ):
                logger.error("mt5.login() fallo: %s", mt5.last_error())
                return False

        # El boton "AutoTrading" de la barra de MT5. Si esta apagado, todo
        # parece funcionar hasta que la primera orden vuelve con retcode
        # 10027 y un mensaje cripto. Se chequea aca para que el problema
        # aparezca al arrancar y con una instruccion concreta, no a mitad de
        # una senal real.
        terminal = mt5.terminal_info()
        if terminal is not None and getattr(terminal, "trade_allowed", True) is False:
            logger.error(
                "MT5 tiene el AutoTrading APAGADO: ninguna orden va a entrar.\n"
                "        Abri MetaTrader 5 y apreta el boton 'Algo Trading' de la barra\n"
                "        de arriba (tiene que quedar verde), o presiona Ctrl+E."
            )
            return False

        account = mt5.account_info()
        if account is None:
            logger.error("No se pudo leer account_info() de MT5")
            return False

        ok, reason = self._ensure_demo(account._asdict())
        if not ok:
            logger.error("MT5: %s", reason)
            return False

        self._ready = True
        logger.info("MT5 listo | servidor=%s balance=%s", account.server, account.balance)
        return True

    async def disconnect(self) -> None:
        if self._mt5 is not None:
            await asyncio.to_thread(self._mt5.shutdown)
        self._ready = False

    async def is_ready(self) -> bool:
        return self._ready and self._mt5 is not None

    def _ensure_demo(self, account: dict[str, Any]) -> tuple[bool, str]:
        if self.settings.allow_live_trading:
            return True, "ALLOW_LIVE_TRADING=true, chequeo de demo omitido"
        if account.get("trade_allowed") is False:
            return False, "La cuenta tiene trade_allowed=false"

        demo_const = getattr(self._mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_const is not None and account.get("trade_mode") == demo_const:
            return True, "ok"

        haystack = " ".join(
            str(account.get(key) or "") for key in ("server", "company", "name")
        ).upper()
        if "DEMO" in haystack:
            return True, "ok"

        return False, "La cuenta no es demo. Se bloquea la ejecucion."

    async def account_equity(self) -> float | None:
        if not await self.is_ready():
            return None
        return await asyncio.to_thread(self._equity_sync)

    def _equity_sync(self) -> float | None:
        try:
            cuenta = self._mt5.account_info()
        except Exception:
            logger.warning("No se pudo leer el equity de MT5", exc_info=True)
            return None
        return float(cuenta.equity) if cuenta is not None else None

    async def market_price(self, symbol: str) -> float | None:
        if not await self.is_ready():
            return None
        return await asyncio.to_thread(self._market_price_sync, symbol)

    def _market_price_sync(self, symbol: str) -> float | None:
        """Precio medio del instrumento, o None si el broker no lo da.

        Se resuelve el nombre igual que al abrir (`_resolver_contra_broker`,
        que ademas cachea), asi el control contra el mercado y la orden miran
        exactamente el mismo simbolo. Si divergieran, el control validaria un
        instrumento y la orden entraria en otro, que es justo el error que
        este chequeo existe para atajar.
        """
        try:
            broker_symbol = self._resolver_contra_broker(symbol) or to_broker_symbol(
                symbol, self.settings.mt5_broker_profile
            )
            if self._ensure_symbol(broker_symbol) is None:
                return None
            tick = self._mt5.symbol_info_tick(broker_symbol)
        except Exception:
            logger.warning("No se pudo leer la cotizacion de %s", symbol, exc_info=True)
            return None

        if tick is None:
            return None

        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        # Fuera de horario un lado puede venir en cero. Con uno solo alcanza:
        # la tolerancia se mide en puntos porcentuales y el spread no la mueve.
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        return bid or ask or None

    # -- Operaciones -------------------------------------------------------

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
        if not await self.is_ready():
            return OrderResult(False, "open", "MT5 no esta conectado", symbol=symbol)
        return await asyncio.to_thread(
            self._open_sync, symbol, side, order_type, lot, entry, stop_loss, take_profit
        )

    def _open_sync(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        lot: float,
        entry: float | None,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> OrderResult:
        mt5 = self._mt5

        # Primero se le pregunta al broker como se llama el instrumento; el
        # perfil de sufijos del .env queda como respaldo por si la terminal
        # todavia no tiene la lista cargada.
        broker_symbol = self._resolver_contra_broker(symbol) or to_broker_symbol(
            symbol, self.settings.mt5_broker_profile
        )

        info = self._ensure_symbol(broker_symbol)
        if info is None:
            return OrderResult(
                False, "open", f"El broker no expone el simbolo {broker_symbol}", symbol=symbol
            )

        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return OrderResult(False, "open", f"Sin cotizacion para {broker_symbol}", symbol=symbol)

        is_buy = side is Side.BUY
        market_price = tick.ask if is_buy else tick.bid

        volume = self._normalize_volume(info, lot)
        if volume is None:
            return OrderResult(
                False, "open", f"Volumen {lot} fuera de los limites de {broker_symbol}", symbol=symbol
            )

        # MAX_LOT es un techo, no una sugerencia, y este es el unico lugar donde
        # se conoce el numero definitivo. `_normalize_volume` puede SUBIR el
        # lote hasta el minimo del instrumento: un indice con volume_min=0.1
        # convierte un DEFAULT_LOT de 0.01 en una posicion diez veces mas
        # grande, y risk.py no lo ve porque compara default_lot contra max_lot,
        # nunca el volumen que se manda. Con los ALLOWED_SYMBOLS de fabrica
        # (NAS100, US30, US500) es una configuracion perfectamente posible.
        #
        # Solo aplica al ABRIR. Cerrar por encima del techo tiene que poder
        # hacerse siempre: negarse a cerrar es mucho peor que abrir de mas, y
        # ademas ahi la posicion ya existe.
        max_lot = getattr(self.settings, "max_lot", 0) or 0
        if max_lot and volume > max_lot + 1e-9:
            return OrderResult(
                False, "open",
                f"El lote minimo de {broker_symbol} es {volume} y supera MAX_LOT={max_lot}. "
                f"No se abre nada. Para operar este instrumento hay que poner "
                f"MAX_LOT={volume} en el .env, sabiendo que cada operacion suya va a "
                f"ser de ese tamano.",
                symbol=symbol, lot=volume,
            )

        if order_type is OrderType.MARKET or entry is None:
            action = mt5.TRADE_ACTION_DEAL
            mt5_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            price = market_price
        else:
            action = mt5.TRADE_ACTION_PENDING
            price = entry
            # LIMIT espera a que el precio vuelva; STOP a que rompa. Cual de
            # los dos corresponde depende de si la entrada esta por encima o
            # por debajo del mercado, no solo de lo que dijo el mensaje.
            if order_type is OrderType.LIMIT:
                mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
            else:
                mt5_type = mt5.ORDER_TYPE_BUY_STOP if is_buy else mt5.ORDER_TYPE_SELL_STOP

        request = {
            "action": action,
            "symbol": broker_symbol,
            "volume": volume,
            "type": mt5_type,
            "price": float(price),
            "deviation": 20,
            "magic": 20260829,
            "comment": "tct-copy",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        if stop_loss is not None:
            request["sl"] = float(stop_loss)
        if take_profit is not None:
            request["tp"] = float(take_profit)

        # Los brokers no coinciden en que modo de llenado aceptan y devuelven
        # 10030 (unsupported filling mode) sin decir cual sirve. Se prueban en
        # orden hasta que uno pase.
        last_result = None
        for filling in self._filling_modes(info):
            request["type_filling"] = filling
            result = mt5.order_send(request)
            last_result = result
            if result is None:
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return OrderResult(
                    ok=True,
                    action="open",
                    reason="orden ejecutada",
                    ticket=int(result.order or result.deal or 0) or None,
                    price=float(result.price or price),
                    # El volumen CONFIRMADO por el broker, no el que se pidio.
                    # MT5 puede llenar menos de lo solicitado, y el motor
                    # construye el estado con este numero: informar el pedido
                    # dejaba al bot creyendo tener abierto mas de lo que hay.
                    lot=_volumen_confirmado(result, volume),
                    symbol=symbol,
                    raw={"retcode": result.retcode, "comment": result.comment},
                )
            if result.retcode != getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030):
                break  # el rechazo no es por filling mode: no tiene sentido reintentar

        reason = (
            f"order_send rechazado: retcode={last_result.retcode} {last_result.comment}"
            if last_result is not None
            else f"order_send devolvio None: {mt5.last_error()}"
        )
        return OrderResult(False, "open", reason, symbol=symbol, lot=volume)

    async def close_position(
        self, *, ticket: int | None, symbol: str, fraction: float = 1.0
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "close", "MT5 no esta conectado", symbol=symbol)
        if ticket is None:
            return OrderResult(False, "close", "Falta el ticket de la posicion", symbol=symbol)
        return await asyncio.to_thread(self._close_sync, ticket, symbol, fraction)

    def _close_sync(self, ticket: int, symbol: str, fraction: float) -> OrderResult:
        mt5 = self._mt5
        action = "close" if fraction >= 1.0 else "partial_close"

        positions = mt5.positions_get(ticket=ticket)
        # None y () NO son lo mismo, y confundirlos cuesta caro en las dos
        # direcciones. None es un error de consulta (terminal caida, sin
        # conexion): ahi la posicion puede estar perfectamente viva y darla por
        # cerrada la dejaria corriendo sin registro. () es "la busque y no
        # esta", que es informacion buena.
        if positions is None:
            return OrderResult(
                False, action,
                f"No se pudo consultar la posicion {ticket}: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        if not positions:
            return OrderResult(
                False, action,
                f"La posicion {ticket} ya no existe en MT5: la cerro el SL o el TP, "
                "o la cerraste a mano. No habia nada que cerrar.",
                ticket=ticket, symbol=symbol, raw={"ausente": True},
            )
        position = positions[0]

        info = self._ensure_symbol(position.symbol)
        volume = position.volume if fraction >= 1.0 else self._normalize_volume(
            info, position.volume * fraction
        )
        if not volume:
            return OrderResult(False, action, "Volumen de cierre invalido", symbol=symbol)

        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            return OrderResult(False, action, f"Sin cotizacion para {position.symbol}", symbol=symbol)

        # Cerrar es abrir la operacion opuesta contra el mismo ticket.
        is_long = position.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": position.symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_long else tick.ask,
            "deviation": 20,
            "magic": 20260829,
            "comment": "tct-close",
        }

        last_result = None
        for filling in self._filling_modes(info):
            request["type_filling"] = filling
            result = mt5.order_send(request)
            last_result = result
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                return OrderResult(
                    ok=True, action=action, reason="cierre ejecutado", ticket=ticket,
                    price=float(result.price or 0) or None,
                    # Igual que al abrir: lo que el broker cerro de verdad. De
                    # este numero sale la fraccion que el motor da por cerrada.
                    lot=_volumen_confirmado(result, volume), symbol=symbol,
                    raw={"retcode": result.retcode},
                )
            if result is not None and result.retcode != getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030):
                break

        reason = (
            f"cierre rechazado: retcode={last_result.retcode} {last_result.comment}"
            if last_result is not None
            else f"order_send devolvio None: {mt5.last_error()}"
        )
        return OrderResult(False, action, reason, ticket=ticket, symbol=symbol)

    async def modify_stop_loss(
        self, *, ticket: int | None, symbol: str, stop_loss: float
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "modify_sl", "MT5 no esta conectado", symbol=symbol)
        if ticket is None:
            return OrderResult(False, "modify_sl", "Falta el ticket de la posicion", symbol=symbol)
        return await asyncio.to_thread(self._modify_sl_sync, ticket, symbol, stop_loss)

    def _modify_sl_sync(self, ticket: int, symbol: str, stop_loss: float) -> OrderResult:
        mt5 = self._mt5
        positions = mt5.positions_get(ticket=ticket)
        if positions is None:
            return OrderResult(
                False, "modify_sl",
                f"No se pudo consultar la posicion {ticket}: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        if not positions:
            return OrderResult(
                False, "modify_sl",
                f"La posicion {ticket} ya no existe en MT5: no hay stop que mover.",
                ticket=ticket, symbol=symbol, raw={"ausente": True},
            )
        position = positions[0]

        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": float(stop_loss),
            "tp": float(position.tp or 0.0),  # conservar el TP vigente
        })
        if result is None:
            return OrderResult(
                False, "modify_sl", f"order_send devolvio None: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        ok = result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(
            ok=ok, action="modify_sl",
            reason="SL modificado" if ok else f"rechazado: retcode={result.retcode} {result.comment}",
            ticket=ticket, price=stop_loss, symbol=symbol, raw={"retcode": result.retcode},
        )

    # -- Auxiliares (portados de tradingalertaIA) --------------------------

    def _ensure_symbol(self, symbol: str):
        """Devuelve symbol_info, activandolo en Market Watch si hace falta."""
        mt5 = self._mt5
        try:
            info = mt5.symbol_info(symbol)
        except Exception:
            return None
        if info is None:
            return None
        if not bool(getattr(info, "visible", True)):
            try:
                if not mt5.symbol_select(symbol, True):
                    return None
                info = mt5.symbol_info(symbol)
            except Exception:
                return None
        return info

    def _resolver_contra_broker(self, canonico: str) -> str | None:
        """Encuentra como se llama REALMENTE este instrumento en este broker.

        Se le pregunta a MT5 en vez de confiar en una tabla de sufijos escrita
        a mano. Cada broker bautiza distinto (XAUUSD, XAUUSDm, XAUUSD.r,
        GOLD...), y una tabla estatica queda desactualizada o simplemente no
        cubre al broker que termine usando el usuario. Con la terminal
        conectada, la lista autoritativa esta a una llamada de distancia.

        El resultado se cachea: `symbols_get()` devuelve miles de simbolos y
        recorrerlos en cada senal seria un desperdicio.
        """
        canonico = canonico.strip().upper()
        if canonico in self._symbol_cache:
            return self._symbol_cache[canonico]

        mt5 = self._mt5
        try:
            todos = mt5.symbols_get() or ()
        except Exception:
            logger.warning("No se pudo listar los simbolos del broker", exc_info=True)
            return None

        nombres = [getattr(s, "name", "") for s in todos]

        # 1) Nombre exacto.
        # 2) Nombre + sufijo del broker (XAUUSDm, XAUUSD.r, XAUUSD.s...).
        # 3) Alias conocidos del instrumento (GOLD para XAUUSD, US100 para
        #    NAS100), tambien con sufijo.
        candidatos = [canonico, *_ALIAS_DE_BROKER.get(canonico, ())]
        for candidato in candidatos:
            for nombre in nombres:
                if nombre.upper() == candidato:
                    self._symbol_cache[canonico] = nombre
                    return nombre
        for candidato in candidatos:
            for nombre in nombres:
                arriba = nombre.upper()
                # Solo se acepta sufijo corto: evita que "EURUSD" matchee con
                # un simbolo distinto tipo "EURUSDT" de cripto.
                if arriba.startswith(candidato) and len(arriba) - len(candidato) <= 4:
                    resto = arriba[len(candidato):]
                    if resto == "" or not resto[0].isalnum() or len(resto) <= 2:
                        self._symbol_cache[canonico] = nombre
                        logger.info("Simbolo %s resuelto como '%s' en este broker", canonico, nombre)
                        return nombre

        logger.error(
            "El broker no expone ningun simbolo para %s. Revisa que este en Market Watch.",
            canonico,
        )
        self._symbol_cache[canonico] = None
        return None

    @staticmethod
    def _normalize_volume(info: Any, lot: float) -> float | None:
        """Ajusta el lote al paso del broker y verifica min/max."""
        if info is None:
            return None
        step = float(getattr(info, "volume_step", 0.01) or 0.01)
        minimum = float(getattr(info, "volume_min", 0.01) or 0.01)
        maximum = float(getattr(info, "volume_max", 100.0) or 100.0)

        steps = round(lot / step)
        volume = round(steps * step, 8)
        if volume < minimum:
            volume = minimum
        if volume > maximum:
            return None
        # Se redondea a la precision del paso: 0.01 -> 2 decimales.
        precision = max(0, len(f"{step:.8f}".rstrip("0").split(".")[-1]))
        return round(volume, precision)

    def _filling_modes(self, info: Any) -> list[int]:
        """Modos de llenado a probar, en orden de preferencia.

        `symbol_info.filling_mode` viene como flags de capacidad del simbolo,
        mientras que `order_send` espera un enum ORDER_FILLING_*. No son la
        misma escala y confundirlos es la causa clasica del retcode 10030.
        """
        mt5 = self._mt5
        mode = getattr(info, "filling_mode", None)
        order_fok = getattr(mt5, "ORDER_FILLING_FOK", 0)
        order_ioc = getattr(mt5, "ORDER_FILLING_IOC", 1)
        order_return = getattr(mt5, "ORDER_FILLING_RETURN", 2)
        symbol_fok = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
        symbol_ioc = getattr(mt5, "SYMBOL_FILLING_IOC", 2)

        modes: list[int] = []
        if isinstance(mode, int):
            if mode & symbol_ioc:
                modes.append(order_ioc)
            if mode & symbol_fok:
                modes.append(order_fok)
        for fallback in (order_ioc, order_fok, order_return):
            if fallback not in modes:
                modes.append(fallback)
        return modes
