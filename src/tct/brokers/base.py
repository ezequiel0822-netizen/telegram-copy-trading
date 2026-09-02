"""Interfaz comun de brokers.

Toda la interfaz es async porque las dos patas del sistema lo son: Telethon
para leer Telegram y el SDK de MetaApi para ejecutar. El broker de MT5 nativo
es sincronico y se envuelve con `asyncio.to_thread`, asi una llamada lenta a
`order_send` no congela la lectura de mensajes.

El motor NUNCA importa un broker concreto: pide uno a `build_broker()` y habla
solo con esta interfaz. Eso es lo que permite que el mismo codigo corra en
paper en la Mac y contra MT5 demo por MetaApi sin tocar una linea.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from tct.signals.models import OrderType, Side


@dataclass(frozen=True)
class OrderResult:
    """Resultado de cualquier operacion contra un broker.

    `ok=False` no es una excepcion: un rechazo del broker (mercado cerrado,
    margen insuficiente) es un resultado esperado que hay que registrar.
    """

    ok: bool
    action: str
    reason: str = ""
    ticket: int | None = None
    price: float | None = None
    lot: float | None = None
    symbol: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "reason": self.reason,
            "ticket": self.ticket,
            "price": self.price,
            "lot": self.lot,
            "symbol": self.symbol,
            "raw": self.raw,
        }


class Broker(ABC):
    """Contrato minimo que tiene que cumplir cualquier destino de ordenes."""

    name: str = "base"

    @abstractmethod
    async def connect(self) -> bool:
        """Prepara la conexion. False si no se pudo (no lanza)."""

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def is_ready(self) -> bool:
        """True si el broker puede recibir ordenes ahora mismo."""

    @abstractmethod
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
        """Abre una posicion o coloca una orden pendiente.

        Se manda UN solo take profit (el primero utilizable): MT5 admite un
        unico TP por posicion. Los TPs restantes quedan registrados en el paper
        trade y se gestionan con mensajes de cierre parcial del grupo.
        """

    @abstractmethod
    async def close_position(
        self, *, ticket: int | None, symbol: str, fraction: float = 1.0
    ) -> OrderResult:
        """Cierra una posicion entera (fraction=1.0) o una parte.

        El broker informa una posicion AUSENTE con `raw={"ausente": True}`.
        Que no exista NO es un fallo del cierre: significa que ya esta
        cerrada. El motor la saca del estado en vez de reintentar para
        siempre. Sin eso, cerrar una posicion a mano en MetaTrader (que es
        justo lo que la guia le dice al usuario que haga) dejaba el simbolo
        bloqueado por la regla de "ya hay una posicion abierta".
        """

    @abstractmethod
    async def modify_stop_loss(
        self, *, ticket: int | None, symbol: str, stop_loss: float
    ) -> OrderResult:
        ...

    async def account_equity(self) -> float | None:
        """Valor actual de la cuenta, o None si no se puede leer.

        Se pide EQUITY y no BALANCE: el balance solo refleja lo ya cerrado, y
        el freno por perdida diaria tiene que reaccionar tambien a lo que se
        esta perdiendo en posiciones todavia abiertas.

        Devolver None significa "no se pudo leer", y `risk.py` lo interpreta
        como "no frenar": sin dato no se inventa un motivo de rechazo.
        """
        return None

    async def market_price(self, symbol: str) -> float | None:
        """Precio actual del instrumento, o None si no se puede leer.

        Es el unico dato del mundo real que entra a la evaluacion de riesgo.
        Todas las demas validaciones miran el mensaje contra si mismo, y por
        eso no pueden distinguir un precio coherente de un precio CORRECTO:
        un SL 10 puntos por debajo de una entrada de 2345 es geometricamente
        impecable aunque el oro este cotizando a 4438.

        Devolver None significa "no se pudo leer", y `risk.py` lo interpreta
        como "no opinar": misma politica que `account_equity()`. Sin dato no
        se inventa un motivo de rechazo, porque hacerlo dejaria al bot sin
        operar cada vez que el broker tarda en responder.

        El precio que se espera es el medio (bid+ask)/2: comparar contra bid o
        ask meteria el spread del broker adentro de una tolerancia que se mide
        en puntos porcentuales.
        """
        return None

    async def health(self) -> dict[str, Any]:
        """Info de diagnostico para el comando `status`. Nunca incluye secretos."""
        return {"broker": self.name, "ready": await self.is_ready()}


def build_broker(settings) -> Broker:
    """Elige el broker segun TRADING_MODE.

    Los imports van adentro para que la ausencia de un SDK opcional
    (`metaapi-cloud-sdk`, `MetaTrader5`) no rompa el arranque en modo paper.
    Es la misma politica de soft-fail que ya usabas en tradingalertaIA.
    """
    from tct.config import (
        LIVE,
        PAPER_AND_METAAPI_DEMO,
        PAPER_AND_MT5_DEMO,
        PAPER_ONLY,
    )

    if settings.trading_mode == PAPER_ONLY:
        from tct.brokers.paper import PaperBroker

        return PaperBroker()

    if settings.trading_mode == PAPER_AND_METAAPI_DEMO:
        from tct.brokers.metaapi import MetaApiBroker

        return MetaApiBroker(settings)

    if settings.trading_mode in {PAPER_AND_MT5_DEMO, LIVE}:
        from tct.brokers.mt5_native import MT5NativeBroker

        return MT5NativeBroker(settings)

    raise ValueError(f"TRADING_MODE desconocido: {settings.trading_mode}")
