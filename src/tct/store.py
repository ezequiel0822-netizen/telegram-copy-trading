"""Persistencia en archivos planos: JSONL para historial, JSON para estado.

Se eligio JSONL y no SQLite a proposito. En esta etapa el valor esta en poder
abrir `data/events.jsonl` con cualquier editor y entender que paso, sin
herramientas. Cuando el volumen lo pida, migrar a SQLite es directo porque
todo el acceso pasa por esta clase.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class OpenPosition:
    """Una operacion que el bot considera viva.

    `broker_ticket` es None en paper trading. `signal_message_id` es la clave
    que permite atar un "close half" posterior a la senal que lo abrio.
    """

    trade_id: str
    symbol: str
    side: str
    lot: float
    entry: float | None
    stop_loss: float | None
    take_profits: list[float]
    opened_at: str
    signal_message_id: int | None = None
    broker_ticket: int | None = None
    remaining_fraction: float = 1.0
    mode: str = "paper"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "side": self.side,
            "lot": self.lot,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profits": self.take_profits,
            "opened_at": self.opened_at,
            "signal_message_id": self.signal_message_id,
            "broker_ticket": self.broker_ticket,
            "remaining_fraction": self.remaining_fraction,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenPosition:
        return cls(
            trade_id=data["trade_id"],
            symbol=data["symbol"],
            side=data["side"],
            lot=float(data.get("lot") or 0),
            entry=data.get("entry"),
            stop_loss=data.get("stop_loss"),
            take_profits=list(data.get("take_profits") or []),
            opened_at=data.get("opened_at") or utc_now_iso(),
            signal_message_id=data.get("signal_message_id"),
            broker_ticket=data.get("broker_ticket"),
            remaining_fraction=float(data.get("remaining_fraction", 1.0)),
            mode=data.get("mode") or "paper",
        )


@dataclass
class State:
    """Estado que tiene que sobrevivir a un reinicio.

    Sin esto, reiniciar el bot significaria reprocesar mensajes viejos y
    duplicar operaciones.
    """

    last_message_id: dict[str, int] = field(default_factory=dict)
    processed_message_ids: list[str] = field(default_factory=list)
    open_positions: list[OpenPosition] = field(default_factory=list)
    signals_today: int = 0
    signals_day: str = field(default_factory=_today_utc)

    # Pausa manual. Persiste a proposito: si pausaste desde el telefono porque
    # el mercado se puso feo, un reinicio del bot NO debe reanudar solo.
    paused: bool = False
    paused_reason: str = ""

    # Balance al abrir el dia, para medir la perdida diaria. None = sin tomar.
    day_start_balance: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_message_id": self.last_message_id,
            # Se recorta a los ultimos 500: alcanza de sobra para deduplicar y
            # evita que el archivo de estado crezca sin techo.
            "processed_message_ids": self.processed_message_ids[-500:],
            "open_positions": [p.to_dict() for p in self.open_positions],
            "signals_today": self.signals_today,
            "signals_day": self.signals_day,
            "paused": self.paused,
            "paused_reason": self.paused_reason,
            "day_start_balance": self.day_start_balance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        return cls(
            last_message_id={str(k): int(v) for k, v in (data.get("last_message_id") or {}).items()},
            processed_message_ids=list(data.get("processed_message_ids") or []),
            open_positions=[OpenPosition.from_dict(p) for p in (data.get("open_positions") or [])],
            signals_today=int(data.get("signals_today") or 0),
            signals_day=data.get("signals_day") or _today_utc(),
            paused=bool(data.get("paused")),
            paused_reason=data.get("paused_reason") or "",
            day_start_balance=data.get("day_start_balance"),
        )


class Store:
    def __init__(self, events_path: Path, paper_trades_path: Path, state_path: Path) -> None:
        self.events_path = Path(events_path)
        self.paper_trades_path = Path(paper_trades_path)
        self.state_path = Path(state_path)
        for path in (self.events_path, self.paper_trades_path, self.state_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    # -- Historial ---------------------------------------------------------

    def append_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Registra CUALQUIER cosa que pase, aceptada o rechazada.

        Que se registren tambien los rechazos es lo que despues permite
        contestar "por que el bot no tomo esta senal".
        """
        event = {"ts": utc_now_iso(), "kind": kind, **payload}
        self._append_jsonl(self.events_path, event)
        return event

    def append_paper_trade(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"ts": utc_now_iso(), **payload}
        self._append_jsonl(self.paper_trades_path, event)
        return event

    def read_paper_trades(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.paper_trades_path)

    def read_events(self) -> list[dict[str, Any]]:
        return self._read_jsonl(self.events_path)

    # -- Deduplicacion -----------------------------------------------------

    def already_processed(self, chat_id: Any, message_id: Any) -> bool:
        return f"{chat_id}:{message_id}" in set(self.state.processed_message_ids)

    def mark_processed(self, chat_id: Any, message_id: Any) -> None:
        key = f"{chat_id}:{message_id}"
        if key not in self.state.processed_message_ids:
            self.state.processed_message_ids.append(key)
        try:
            current = self.state.last_message_id.get(str(chat_id), 0)
            self.state.last_message_id[str(chat_id)] = max(current, int(message_id))
        except (TypeError, ValueError):
            pass

    # -- Posiciones --------------------------------------------------------

    def open_positions(self) -> list[OpenPosition]:
        return list(self.state.open_positions)

    def add_position(self, position: OpenPosition) -> None:
        self.state.open_positions.append(position)

    def remove_position(self, trade_id: str) -> OpenPosition | None:
        for index, position in enumerate(self.state.open_positions):
            if position.trade_id == trade_id:
                return self.state.open_positions.pop(index)
        return None

    def find_positions(self, symbol: str | None = None) -> list[OpenPosition]:
        """Posiciones vivas, opcionalmente filtradas por simbolo.

        Sin simbolo devuelve todas: un "close all" del grupo no menciona
        ningun instrumento.
        """
        if symbol is None:
            return self.open_positions()
        return [p for p in self.state.open_positions if p.symbol == symbol.upper()]

    # -- Cupo diario -------------------------------------------------------

    def bump_daily_counter(self) -> int:
        today = _today_utc()
        if self.state.signals_day != today:
            self.state.signals_day = today
            self.state.signals_today = 0
        self.state.signals_today += 1
        return self.state.signals_today

    def signals_today(self) -> int:
        if self.state.signals_day != _today_utc():
            return 0
        return self.state.signals_today

    # -- Pausa -------------------------------------------------------------

    def pause(self, reason: str = "") -> None:
        self.state.paused = True
        self.state.paused_reason = reason
        self.save_state()

    def resume(self) -> None:
        self.state.paused = False
        self.state.paused_reason = ""
        self.save_state()

    @property
    def is_paused(self) -> bool:
        return self.state.paused

    # -- Perdida diaria ----------------------------------------------------

    def day_start_balance(self, balance_actual: float | None) -> float | None:
        """Balance de referencia del dia. Se toma el primero que se ve.

        Se reinicia al cambiar de dia, junto con el cupo de senales, para que
        el tope de perdida sea diario de verdad y no acumulado desde siempre.
        """
        hoy = _today_utc()
        if self.state.signals_day != hoy:
            self.state.signals_day = hoy
            self.state.signals_today = 0
            self.state.day_start_balance = None
        if self.state.day_start_balance is None and balance_actual is not None:
            self.state.day_start_balance = float(balance_actual)
            self.save_state()
        return self.state.day_start_balance

    # -- Estado en disco ---------------------------------------------------

    def save_state(self) -> None:
        """Escritura atomica: si el proceso muere a mitad, el estado previo sobrevive."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp_path = tempfile.mkstemp(
            dir=str(self.state_path.parent), prefix=".state-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(self.state.to_dict(), file, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.state_path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def _load_state(self) -> State:
        if not self.state_path.exists():
            return State()
        try:
            with self.state_path.open(encoding="utf-8") as file:
                return State.from_dict(json.load(file))
        except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
            # Un estado corrupto no puede tumbar el arranque, pero tampoco se
            # pisa en silencio: se guarda al lado para poder revisarlo.
            backup = self.state_path.with_suffix(".corrupt.json")
            try:
                self.state_path.replace(backup)
                logger.error("Estado corrupto; se movio a %s y se arranca limpio", backup)
            except OSError:
                logger.exception("Estado corrupto y no se pudo respaldar")
            return State()

    # -- Utilidades --------------------------------------------------------

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    # Una linea rota no invalida el resto del historial.
                    logger.warning("Linea invalida en %s:%d, se saltea", path, line_number)
        return rows
