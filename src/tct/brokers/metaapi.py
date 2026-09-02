"""Broker via MetaApi Cloud: MT5 desde macOS.

POR QUE EXISTE ESTE ARCHIVO
---------------------------
El paquete `MetaTrader5` de PyPI publica unicamente wheels `win_amd64` y no
tiene source distribution, asi que en una Mac `pip install MetaTrader5` falla
directamente. Ademas el terminal MT5 para macOS es un envoltorio de Wine que
la API de Python no alcanza.

MetaApi resuelve eso: hostea el terminal MT5 en su nube y expone la cuenta por
REST/WebSocket, con lo cual el sistema operativo del cliente deja de importar.

ESTADO
------
Escrito contra la API de `metaapi-cloud-sdk` 27.x pero NO probado contra una
cuenta real (haria falta un token y una cuenta MT5 demo conectada). Las
llamadas se resuelven con `getattr` y cada fallo devuelve un `OrderResult`
explicito en vez de reventar, para que el primer contacto con la cuenta demo
sea diagnosticable y no un stacktrace.

SEGURIDAD
---------
`_ensure_demo()` rechaza cualquier cuenta que MetaApi no reporte como demo,
salvo que ALLOW_LIVE_TRADING=true. Misma barrera que `_is_demo_account()` en
tradingalertaIA: la proteccion vive en el ejecutor, no en la configuracion.
"""

from __future__ import annotations

import logging
from typing import Any

from tct.brokers.base import Broker, OrderResult
from tct.brokers.symbol_map import to_broker_symbol
from tct.signals.models import OrderType, Side

logger = logging.getLogger(__name__)

_DEMO_MARKERS = {"ACCOUNT_TRADE_MODE_DEMO", "DEMO", "ACCOUNT_TRADE_MODE_CONTEST", "CONTEST"}


class MetaApiBroker(Broker):
    name = "metaapi"

    def __init__(self, settings) -> None:
        self.settings = settings
        self._api = None
        self._account = None
        self._connection = None
        self._ready = False
        self._account_info: dict[str, Any] = {}

    # -- Ciclo de vida -----------------------------------------------------

    async def connect(self) -> bool:
        try:
            from metaapi_cloud_sdk import MetaApi
        except ImportError:
            logger.error(
                "Falta el SDK de MetaApi. Instalalo con: pip install metaapi-cloud-sdk"
            )
            return False

        try:
            self._api = MetaApi(self.settings.metaapi_token)
            self._account = await self._api.metatrader_account_api.get_account(
                self.settings.metaapi_account_id
            )

            # Una cuenta puede estar "undeployed" (apagada para no gastar).
            state = getattr(self._account, "state", None)
            if state in {"UNDEPLOYED", "DEPLOYING"}:
                logger.info("Desplegando la cuenta en MetaApi...")
                await self._account.deploy()

            logger.info("Esperando que MetaApi conecte con el broker...")
            await self._account.wait_connected()

            # RPC alcanza y es mas simple que streaming: se piden datos cuando
            # se necesitan, sin mantener un libro sincronizado en memoria.
            self._connection = self._account.get_rpc_connection()
            await self._connection.connect()
            await self._connection.wait_synchronized()

            self._account_info = await self._connection.get_account_information() or {}

            ok, reason = self._ensure_demo(self._account_info)
            if not ok:
                logger.error("MetaApi: %s", reason)
                self._ready = False
                return False

            self._ready = True
            logger.info(
                "MetaApi listo | broker=%s tipo=%s moneda=%s balance=%s",
                self._account_info.get("broker"),
                self._account_info.get("type"),
                self._account_info.get("currency"),
                self._account_info.get("balance"),
            )
            return True

        except Exception:
            logger.exception("No se pudo conectar a MetaApi")
            self._ready = False
            return False

    async def disconnect(self) -> None:
        try:
            if self._connection is not None:
                await self._connection.close()
        except Exception:
            logger.warning("Error cerrando la conexion de MetaApi", exc_info=True)
        finally:
            self._ready = False

    async def is_ready(self) -> bool:
        return self._ready and self._connection is not None

    def _ensure_demo(self, account_info: dict[str, Any]) -> tuple[bool, str]:
        """Bloquea cuentas que no sean demo. Es la barrera real del sistema."""
        if self.settings.allow_live_trading:
            return True, "ALLOW_LIVE_TRADING=true, chequeo de demo omitido"

        account_type = str(account_info.get("type") or "").upper()
        if account_type in _DEMO_MARKERS:
            return True, "ok"

        # Si MetaApi no reporta el tipo, se cae al nombre del servidor.
        haystack = " ".join(
            str(account_info.get(key) or "") for key in ("server", "broker", "name")
        ).upper()
        if "DEMO" in haystack:
            return True, "ok"

        return False, (
            f"La cuenta no figura como demo (type='{account_type or 'desconocido'}'). "
            "Se bloquea la ejecucion. Para operar real hace falta ALLOW_LIVE_TRADING=true."
        )

    async def account_equity(self) -> float | None:
        if not await self.is_ready():
            return None
        try:
            info = await self._connection.get_account_information() or {}
        except Exception:
            logger.warning("No se pudo leer el equity de MetaApi", exc_info=True)
            return None
        valor = info.get("equity")
        return float(valor) if valor is not None else None

    async def market_price(self, symbol: str) -> float | None:
        """Precio medio del instrumento segun MetaApi.

        Se resuelve por `getattr` como el resto del modulo: si esta version
        del SDK no expone `get_symbol_price`, el control contra el mercado se
        queda sin dato y no opina, en vez de romper la senal entera.
        """
        if not await self.is_ready():
            return None

        method = getattr(self._connection, "get_symbol_price", None)
        if method is None:
            logger.warning(
                "El SDK de MetaApi no expone get_symbol_price: el control "
                "contra el precio de mercado queda sin dato."
            )
            return None

        broker_symbol = to_broker_symbol(symbol, self.settings.mt5_broker_profile)
        try:
            precio = await method(broker_symbol) or {}
        except Exception:
            logger.warning("No se pudo leer la cotizacion de %s", symbol, exc_info=True)
            return None

        if not isinstance(precio, dict):
            return None
        bid = float(precio.get("bid") or 0.0)
        ask = float(precio.get("ask") or 0.0)
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
            return OrderResult(False, "open", "MetaApi no esta conectado", symbol=symbol)

        broker_symbol = to_broker_symbol(symbol, self.settings.mt5_broker_profile)
        is_buy = side is Side.BUY

        # Una orden pendiente sin precio no tiene sentido: se degrada a mercado
        # en vez de mandar una orden invalida.
        effective_type = order_type
        if order_type in {OrderType.LIMIT, OrderType.STOP} and entry is None:
            effective_type = OrderType.MARKET

        method_name = {
            (OrderType.MARKET, True): "create_market_buy_order",
            (OrderType.MARKET, False): "create_market_sell_order",
            (OrderType.LIMIT, True): "create_limit_buy_order",
            (OrderType.LIMIT, False): "create_limit_sell_order",
            (OrderType.STOP, True): "create_stop_buy_order",
            (OrderType.STOP, False): "create_stop_sell_order",
        }[(effective_type, is_buy)]

        method = getattr(self._connection, method_name, None)
        if method is None:
            return OrderResult(
                False, "open", f"El SDK de MetaApi no expone {method_name}", symbol=symbol
            )

        try:
            if effective_type is OrderType.MARKET:
                response = await method(broker_symbol, lot, stop_loss, take_profit)
            else:
                response = await method(broker_symbol, lot, entry, stop_loss, take_profit)
        except Exception as exc:
            return OrderResult(
                False, "open", f"MetaApi rechazo la orden: {exc}", symbol=symbol, lot=lot
            )

        return self._to_result("open", response, symbol=symbol, lot=lot, price=entry)

    async def close_position(
        self, *, ticket: int | None, symbol: str, fraction: float = 1.0
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "close", "MetaApi no esta conectado", symbol=symbol)
        if ticket is None:
            return OrderResult(False, "close", "Falta el ticket de la posicion", symbol=symbol)

        try:
            if fraction >= 1.0:
                response = await self._connection.close_position(str(ticket))
                action = "close"
            else:
                volume = await self._partial_volume(str(ticket), fraction)
                if volume is None:
                    return OrderResult(
                        False, "partial_close",
                        f"No se encontro la posicion {ticket} en el broker", symbol=symbol,
                    )
                response = await self._connection.close_position_partially(str(ticket), volume)
                action = "partial_close"
        except Exception as exc:
            return OrderResult(False, "close", f"MetaApi rechazo el cierre: {exc}", symbol=symbol)

        return self._to_result(action, response, symbol=symbol, ticket=ticket)

    async def modify_stop_loss(
        self, *, ticket: int | None, symbol: str, stop_loss: float
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "modify_sl", "MetaApi no esta conectado", symbol=symbol)
        if ticket is None:
            return OrderResult(False, "modify_sl", "Falta el ticket de la posicion", symbol=symbol)

        try:
            # Se conserva el TP actual: modify_position lo pisa con None si no
            # se lo pasa, y eso dejaria la posicion sin objetivo.
            position = await self._get_position(str(ticket))
            take_profit = (position or {}).get("takeProfit")
            response = await self._connection.modify_position(str(ticket), stop_loss, take_profit)
        except Exception as exc:
            return OrderResult(
                False, "modify_sl", f"MetaApi rechazo la modificacion: {exc}", symbol=symbol
            )

        return self._to_result("modify_sl", response, symbol=symbol, ticket=ticket, price=stop_loss)

    # -- Auxiliares --------------------------------------------------------

    async def _get_position(self, ticket: str) -> dict[str, Any] | None:
        try:
            positions = await self._connection.get_positions() or []
        except Exception:
            logger.warning("No se pudieron leer las posiciones de MetaApi", exc_info=True)
            return None
        for position in positions:
            if str(position.get("id")) == ticket:
                return position
        return None

    async def _partial_volume(self, ticket: str, fraction: float) -> float | None:
        position = await self._get_position(ticket)
        if not position:
            return None
        volume = float(position.get("volume") or 0)
        # Se redondea a 2 decimales: los brokers trabajan en pasos de 0.01 lote.
        return round(volume * fraction, 2) or None

    @staticmethod
    def _to_result(
        action: str,
        response: Any,
        *,
        symbol: str,
        lot: float | None = None,
        ticket: int | None = None,
        price: float | None = None,
    ) -> OrderResult:
        data = response if isinstance(response, dict) else {}
        string_code = str(data.get("stringCode") or data.get("string_code") or "")
        # MetaApi devuelve stringCode 'TRADE_RETCODE_DONE' cuando salio bien.
        ok = not string_code or "DONE" in string_code.upper()

        raw_ticket = data.get("positionId") or data.get("orderId") or ticket
        try:
            resolved_ticket = int(raw_ticket) if raw_ticket is not None else None
        except (TypeError, ValueError):
            resolved_ticket = ticket

        return OrderResult(
            ok=ok,
            action=action,
            reason=str(data.get("message") or string_code or "ok"),
            ticket=resolved_ticket,
            price=price,
            lot=lot,
            symbol=symbol,
            raw=data,
        )

    async def health(self) -> dict[str, Any]:
        return {
            "broker": self.name,
            "ready": await self.is_ready(),
            "account_type": self._account_info.get("type"),
            "broker_name": self._account_info.get("broker"),
            "currency": self._account_info.get("currency"),
            "balance": self._account_info.get("balance"),
        }
