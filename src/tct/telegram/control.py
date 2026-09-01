"""Control del bot desde Telegram: pausar, reanudar, cerrar, ver estado.

POR QUE MENSAJES GUARDADOS
--------------------------
Los comandos se escuchan por defecto en tus **Mensajes Guardados** (el chat con
vos mismo). No hace falta crear ningun bot, ni tokens, ni agregar a nadie a un
grupo: ya existe, es privado, y esta en todos tus dispositivos. Escribis
"/pausa" desde el telefono y el bot que corre en la PC lo lee.

DOS BOTS AL MISMO TIEMPO
------------------------
El paquete MetaTrader5 solo permite UNA cuenta por proceso: `login()` cambia de
cuenta, no agrega. Operar demo y real a la vez son entonces dos procesos, cada
uno con su .env. Los dos escuchan los mismos Mensajes Guardados, asi que los
comandos aceptan destinatario:

    /pausa          -> los dos
    /pausa real     -> solo la instancia llamada "real"
    /pausa demo     -> solo la demo

Cada instancia responde identificandose, para que sepas cual te contesto.

SEGURIDAD
---------
Solo se atienden mensajes del chat de control configurado, que por defecto es
un chat con vos mismo: nadie mas puede escribir ahi. Los comandos que cierran
posiciones piden confirmacion explicita.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Vocabulario CERRADO de destinatarios. Es cerrado a proposito: la primera
# palabra despues del comando puede ser un destinatario ("/pausa real") o el
# principio de un motivo ("/pausa mercado raro"), y hay que distinguirlos sin
# ambiguedad.
#
# Si se aceptara cualquier palabra como destinatario, "/pausa real" llegando al
# bot demo no coincidiria con su nombre... y quedaria sin pausar nada, o peor,
# si se invirtiera la logica, la demo se pausaria creyendo que "real" es un
# motivo. Con una lista fija, cada instancia sabe con certeza si un token es un
# nombre de instancia o texto libre.
#
# `config.py` valida INSTANCE_NAME contra esta misma lista.
NOMBRES_DE_INSTANCIA = frozenset({"demo", "real", "papel", "paper"})
_TODOS = frozenset({"todo", "todos", "all", "ambos", "ambas"})

AYUDA = """Comandos disponibles:

/estado           Que esta haciendo el bot ahora
/pausa            Deja de operar (sigue leyendo y registrando)
/reanudar         Vuelve a operar
/posiciones       Lista las posiciones abiertas
/cerrar todo      Cierra TODAS las posiciones (pide confirmar)
/ayuda            Esto

Con dos bots corriendo, agrega el nombre para dirigirte a uno solo:
    /pausa real       solo el de la cuenta real
    /pausa demo       solo el de la demo
    /pausa            los dos
"""


class ControlTelegram:
    """Atiende los comandos que llegan al chat de control."""

    def __init__(self, settings, store, engine) -> None:
        self.settings = settings
        self.store = store
        self.engine = engine
        self.nombre = settings.instance_name.lower()
        # La confirmacion de cierre vive solo en memoria y solo para el
        # proximo mensaje: no debe sobrevivir a un reinicio ni quedar armada.
        self._espera_confirmacion = False

    # -- Enrutado ----------------------------------------------------------

    def _partir_destinatario(self, resto: str) -> tuple[str, str]:
        """Separa el destinatario del texto libre que venga despues.

        Devuelve (destinatario, resto). El destinatario es "" cuando el
        comando no nombra ninguna instancia, y entonces aplica a todas.
        """
        palabras = resto.strip().split()
        if not palabras:
            return "", ""
        primera = palabras[0].lower()
        if primera in NOMBRES_DE_INSTANCIA or primera in _TODOS:
            return primera, " ".join(palabras[1:])
        # No es un nombre de instancia: es texto libre (un motivo, por ejemplo).
        return "", resto.strip()

    def _es_para_mi(self, resto: str) -> bool:
        """True si el comando me corresponde.

        Sin destinatario, es para todos. Con destinatario, solo para quien
        coincida: asi un "/pausa real" no toca la demo, y viceversa.
        """
        destinatario, _ = self._partir_destinatario(resto)
        if not destinatario or destinatario in _TODOS:
            return True
        return destinatario == self.nombre

    async def manejar(self, texto: str) -> str | None:
        """Procesa un mensaje. Devuelve la respuesta, o None si no es para mi."""
        texto = (texto or "").strip()

        # Guarda contra bucles. El handler escucha el chat entero, y nuestras
        # propias respuestas se envian CON la cuenta del usuario, asi que
        # vuelven a entrar por la misma puerta. Todas empiezan con "[NOMBRE]",
        # que ningun comando puede tener: con eso alcanza para cortarlo.
        if texto.startswith("["):
            return None
        if not texto.startswith("/"):
            # Confirmacion pendiente de un /cerrar todo.
            if self._espera_confirmacion and texto.strip().upper() in {"SI", "SÍ", "YES"}:
                self._espera_confirmacion = False
                return await self._cerrar_todo()
            return None

        partes = texto[1:].split(maxsplit=1)
        comando = partes[0].lower()
        resto = partes[1] if len(partes) > 1 else ""

        # Cualquier comando nuevo cancela una confirmacion pendiente: si
        # cambiaste de tema, no queremos que un "si" posterior cierre todo.
        if comando != "cerrar":
            self._espera_confirmacion = False

        acciones = {
            "estado": self._estado,
            "status": self._estado,
            "pausa": self._pausar,
            "pausar": self._pausar,
            "reanudar": self._reanudar,
            "seguir": self._reanudar,
            "posiciones": self._posiciones,
            "cerrar": self._cerrar,
            "ayuda": self._ayuda,
            "help": self._ayuda,
        }
        accion = acciones.get(comando)
        if accion is None:
            return None

        if not self._es_para_mi(resto):
            return None

        try:
            return await accion(resto)
        except Exception:
            logger.exception("Fallo el comando /%s", comando)
            return f"[{self.nombre}] El comando /{comando} fallo. El bot sigue vivo."

    # -- Comandos ----------------------------------------------------------

    def _cabecera(self) -> str:
        marca = "  *** REAL ***" if self.settings.is_live else ""
        return f"[{self.nombre.upper()}]{marca}"

    async def _estado(self, _resto: str) -> str:
        abiertas = self.store.open_positions()
        lineas = [
            self._cabecera(),
            f"Estado    : {'PAUSADO' if self.store.is_paused else 'operando'}",
        ]
        if self.store.is_paused and self.store.state.paused_reason:
            lineas.append(f"Motivo    : {self.store.state.paused_reason}")
        lineas += [
            f"Modo      : {self.settings.trading_mode}",
            f"Broker    : {self.engine.broker.name}",
            f"Abiertas  : {len(abiertas)}",
            f"Senales   : {self.store.signals_today()}/{self.settings.max_signals_per_day} hoy",
            f"Lote      : {self.settings.default_lot}",
        ]
        return "\n".join(lineas)

    async def _pausar(self, resto: str) -> str:
        if self.store.is_paused:
            return f"{self._cabecera()}\nYa estaba pausado."
        _, motivo = self._partir_destinatario(resto)
        motivo = motivo or "pausado desde Telegram"
        self.store.pause(motivo)
        return (
            f"{self._cabecera()}\nPAUSADO.\n"
            "Sigue leyendo y registrando, pero no abre ni cierra nada.\n"
            "Las posiciones que ya estan abiertas siguen como estan.\n"
            "Para volver: /reanudar"
        )

    async def _reanudar(self, _resto: str) -> str:
        if not self.store.is_paused:
            return f"{self._cabecera()}\nNo estaba pausado."
        self.store.resume()
        aviso = "\n\nOJO: esto opera con DINERO REAL." if self.settings.is_live else ""
        return f"{self._cabecera()}\nOperando de nuevo.{aviso}"

    async def _posiciones(self, _resto: str) -> str:
        abiertas = self.store.open_positions()
        if not abiertas:
            return f"{self._cabecera()}\nSin posiciones abiertas."
        lineas = [self._cabecera(), f"{len(abiertas)} posicion(es):"]
        for p in abiertas:
            lineas.append(
                f"  {p.symbol} {p.side} lote={p.lot} entrada={p.entry} "
                f"SL={p.stop_loss} ({p.remaining_fraction:.0%} restante)"
            )
        return "\n".join(lineas)

    async def _cerrar(self, resto: str) -> str:
        objetivo = resto.strip().lower()
        # "/cerrar todo" cierra todo; "/cerrar real" es un destinatario, no una
        # orden de cierre, y ya lo filtro _es_para_mi.
        palabras = [p for p in objetivo.split() if p not in {self.nombre, "todo", "todos", "all"}]
        if palabras:
            return f"{self._cabecera()}\nNo entendi '{resto}'. Usa: /cerrar todo"

        abiertas = self.store.open_positions()
        if not abiertas:
            return f"{self._cabecera()}\nSin posiciones abiertas."

        self._espera_confirmacion = True
        detalle = ", ".join(f"{p.symbol} {p.side}" for p in abiertas)
        real = " en la cuenta REAL" if self.settings.is_live else ""
        return (
            f"{self._cabecera()}\n"
            f"Vas a cerrar {len(abiertas)} posicion(es){real}:\n  {detalle}\n\n"
            "Respondeme SI para confirmar. Cualquier otra cosa lo cancela."
        )

    async def _cerrar_todo(self) -> str:
        abiertas = self.store.open_positions()
        if not abiertas:
            return f"{self._cabecera()}\nYa no habia nada abierto."

        cerradas, fallidas = 0, []
        for posicion in list(abiertas):
            resultado = await self.engine.broker.close_position(
                ticket=posicion.broker_ticket, symbol=posicion.symbol, fraction=1.0
            )
            if resultado.ok:
                self.store.remove_position(posicion.trade_id)
                cerradas += 1
            else:
                fallidas.append(f"{posicion.symbol}: {resultado.reason}")
        self.store.save_state()

        lineas = [self._cabecera(), f"Cerradas {cerradas} de {len(abiertas)}."]
        if fallidas:
            lineas.append("\nNo se pudieron cerrar (hacelo a mano en MetaTrader):")
            lineas.extend(f"  {f}" for f in fallidas)
        return "\n".join(lineas)

    async def _ayuda(self, _resto: str) -> str:
        return f"{self._cabecera()}\n\n{AYUDA}"


async def escuchar_comandos(client, settings, control: ControlTelegram) -> Any:
    """Engancha el handler de comandos al cliente de Telethon ya conectado.

    Se reutiliza la sesion que ya abrio el lector: son el mismo cliente, asi
    que no hay un segundo login ni otro archivo .session.
    """
    from telethon import events

    try:
        destino = await client.get_entity(settings.telegram_control_chat)
    except Exception as exc:
        logger.error(
            "No se pudo resolver TELEGRAM_CONTROL_CHAT='%s': %s. "
            "El control por Telegram queda apagado.",
            settings.telegram_control_chat, exc,
        )
        return None

    @client.on(events.NewMessage(chats=destino))
    async def _on_comando(event):  # pragma: no cover - requiere red
        try:
            respuesta = await control.manejar(event.message.message or "")
            if respuesta:
                await event.reply(respuesta)
        except Exception:
            # Un comando que explota no puede dejar sordo al listener.
            logger.exception("Error atendiendo un comando de Telegram")

    nombre = getattr(destino, "title", None) or "Mensajes Guardados"
    logger.info("Control por Telegram activo en: %s", nombre)
    return destino
