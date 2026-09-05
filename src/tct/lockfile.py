"""Un solo proceso por carpeta de datos.

POR QUE EXISTE
--------------
Con dos bots corriendo, uno por cuenta de MetaTrader, alcanza un error de
tipeo en un `.bat` o un `.env` copiado a medias para que los dos terminen
apuntando a la MISMA carpeta de datos.

Ahi los dos leen y escriben `state.json`. El que guarda ultimo pisa las
posiciones del otro, y una posicion que desaparece del estado queda **viva en
el broker y sin registro**: ningun cierre posterior la encuentra y corre sola
hasta el stop. Es la "operacion huerfana" de la seccion 6 del CONTEXTO
MAESTRO, pero por duplicado y sin que nadie haya hecho nada raro.

El sintoma seria ademas dificil de leer: dos bots que se contradicen, cada uno
convencido de tener razon.

COMO
----
Un lock del sistema operativo sobre un archivo, no un archivo-con-PID adentro.
La diferencia importa: el sistema suelta el lock solo cuando el proceso muere,
con lo cual **no existe el problema del lock viejo** que queda tirado despues
de un corte de luz y obliga a borrarlo a mano. Un `.lock` huerfano en el disco
no bloquea nada; lo que bloquea es que otro proceso lo tenga abierto.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CarpetaOcupada(RuntimeError):
    """Otra instancia ya esta usando esta carpeta de datos."""


def _bloquear(handle) -> None:
    """Lock exclusivo y NO bloqueante. Lanza OSError si ya esta tomado."""
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _desbloquear(handle) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class LockDeInstancia:
    """Toma la carpeta de datos para este proceso, o falla diciendo por que."""

    def __init__(self, path: str | Path, instancia: str = "") -> None:
        self.path = Path(path)
        self.instancia = instancia
        self._handle: Any = None

    def tomar(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            _bloquear(handle)
        except OSError as exc:
            handle.close()
            raise CarpetaOcupada(self._explicacion()) from exc

        self._handle = handle
        # El PID es solo informativo, para poder mirar quien la tiene. Si la
        # escritura falla el lock ya esta tomado igual, que es lo que importa.
        try:
            handle.seek(0)
            handle.write(f"{os.getpid()}\n")
            handle.flush()
        except OSError:  # pragma: no cover - no cambia la garantia
            pass

    def _explicacion(self) -> str:
        quien = f" '{self.instancia}'" if self.instancia else ""
        return (
            f"Ya hay otro bot usando esta carpeta de datos:\n"
            f"    {self.path.parent}\n\n"
            "Dos procesos sobre la misma carpeta se pisan el estado, y una\n"
            "posicion que desaparece del estado queda abierta en MetaTrader sin\n"
            "que el bot la conozca.\n\n"
            "Casi siempre es una de estas dos:\n"
            f"  1. El bot{quien} ya esta corriendo en otra ventana. Fijate en la\n"
            "     barra de tareas antes de arrancar otro.\n"
            "  2. Dos .env distintos apuntan a la misma carpeta. Cada instancia\n"
            "     necesita la suya:\n"
            "         DATA_DIR=data/fxpro\n"
            "         PAPER_TRADES_PATH=data/fxpro/paper_trades.jsonl\n"
            "         EVENTS_PATH=data/fxpro/events.jsonl\n"
            "         STATE_PATH=data/fxpro/state.json"
        )

    def soltar(self) -> None:
        if self._handle is None:
            return
        try:
            _desbloquear(self._handle)
        except OSError:  # pragma: no cover - se suelta igual al cerrar
            logger.debug("No se pudo desbloquear %s", self.path, exc_info=True)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> LockDeInstancia:
        self.tomar()
        return self

    def __exit__(self, *_excepcion) -> None:
        self.soltar()


def lock_para(settings) -> LockDeInstancia:
    """El lock que le corresponde a esta configuracion.

    Se ata al `state.json` y no a la carpeta: es el archivo cuyo pisoteo
    duele, y dos instancias pueden compartir carpeta con estados separados.
    """
    return LockDeInstancia(
        Path(str(settings.state_path) + ".lock"),
        instancia=getattr(settings, "instance_name", ""),
    )
