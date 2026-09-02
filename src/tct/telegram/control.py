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
import time
from typing import Any

logger = logging.getLogger(__name__)

# Cuanto vive una confirmacion de cierre pendiente, en segundos.
#
# Existe porque una confirmacion sin vencimiento es una bomba de tiempo: pedis
# /cerrar todo, te arrepentis, no contestas nada, y dos horas despues un "si"
# sobre cualquier otro tema encuentra la confirmacion todavia armada y cierra
# la cuenta. Con dos instancias corriendo, la que cierra puede ser la real.
VENTANA_CONFIRMACION_SEG = 120

_AFIRMATIVOS = frozenset({"SI", "SÍ", "YES", "DALE", "CONFIRMO"})

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
        # Confirmacion de cierre pendiente. None = no hay ninguna.
        #
        # Es un dict con CUANDO se armo, y no un bool, por dos motivos que
        # costaron caro: un bool no puede caducar, y no deja distinguir una
        # confirmacion propia de una que quedo colgada de un /cerrar anterior
        # dirigido a otra instancia. Vive solo en memoria: no sobrevive a un
        # reinicio, y eso es deliberado.
        self._confirmacion: dict[str, Any] | None = None

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
            return await self._resolver_confirmacion(texto)

        partes = texto[1:].split(maxsplit=1)
        # Una barra pelada ("/", o "/   ") deja `partes` vacia. Con `partes[0]`
        # a secas eso reventaba con IndexError ANTES de llegar a desarmar la
        # confirmacion, y en produccion la excepcion se la tragaba el listener:
        # la persona no recibia respuesta, la confirmacion quedaba armada, y el
        # "SI" siguiente cerraba. Un agujero justo en la propiedad que este
        # modulo existe para garantizar.
        comando = partes[0].lower() if partes else ""
        resto = partes[1] if len(partes) > 1 else ""

        # Cualquier comando cancela una confirmacion pendiente, INCLUIDO otro
        # /cerrar. Antes el /cerrar se exceptuaba, y ahi vivia el peor bug del
        # sistema: con dos instancias, un "/cerrar" a secas armaba a las DOS;
        # el "/cerrar demo" siguiente no desarmaba a la real (se salteaba este
        # reset) y ademas no le contestaba nada, asi que quedaba armada en
        # silencio; y el "SI" posterior, que no tiene destinatario, le cerraba
        # la cuenta REAL a alguien que creia estar cerrando la demo.
        #
        # Se desarma ANTES de mirar `_es_para_mi`: desarmar de mas es inocuo,
        # desarmar de menos cierra una cuenta. Quien sea el destinatario se
        # vuelve a armar solo, unas lineas mas abajo, en `_cerrar`.
        habia_confirmacion = self._confirmacion is not None
        self._confirmacion = None

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
        es_mio = accion is not None and self._es_para_mi(resto)

        # Cancelar en SILENCIO es el peligro simetrico al de no cancelar. Pedis
        # /cerrar todo, mandas un /posiciones para chequear, contestas SI... y
        # no pasa nada, sin un solo mensaje. Te vas creyendo que cerraste.
        #
        # Un /cerrar propio es la excepcion: se vuelve a armar ahi abajo y su
        # propio mensaje dice como quedo la cosa, asi que avisar "cancelado"
        # seria confuso.
        aviso = ""
        if habia_confirmacion and not (comando == "cerrar" and es_mio):
            aviso = (
                f"{self._cabecera()}\n"
                "Cierre pendiente CANCELADO: llego otro mensaje. NO se cerro nada.\n"
                "Si querias cerrar, mandame /cerrar todo de nuevo.\n\n"
            )

        if not es_mio:
            return aviso or None

        try:
            return aviso + await accion(resto)
        except Exception:
            logger.exception("Fallo el comando /%s", comando)
            return (
                f"{aviso}[{self.nombre}] El comando /{comando} fallo. "
                "El bot sigue vivo."
            )

    async def _resolver_confirmacion(self, texto: str) -> str | None:
        """Atiende un mensaje suelto cuando hay un cierre esperando confirmacion.

        Se consume la confirmacion pase lo que pase. El mensaje del bot promete
        "cualquier otra cosa lo cancela", y esa promesa tiene que ser cierta:
        antes un "no" explicito no cancelaba nada, porque solo se miraba si el
        texto era afirmativo y todo lo demas se ignoraba en silencio.
        """
        pendiente = self._confirmacion
        if pendiente is None:
            return None

        self._confirmacion = None
        vencida = (time.monotonic() - pendiente["momento"]) > VENTANA_CONFIRMACION_SEG

        if vencida:
            return (
                f"{self._cabecera()}\n"
                f"Esa confirmacion ya vencio (pasaron mas de {VENTANA_CONFIRMACION_SEG} "
                "segundos). NO se cerro nada.\n"
                "Si igual queres cerrar, mandame /cerrar todo de nuevo."
            )

        if texto.strip().upper() not in _AFIRMATIVOS:
            return f"{self._cabecera()}\nCierre CANCELADO. No se toco ninguna posicion."

        # Este camino no pasa por el try/except de `manejar`, asi que lleva el
        # suyo: si el broker se corta a mitad de un cierre masivo, la persona
        # tiene que enterarse. Quedarse sin respuesta mientras las posiciones
        # quedan a medio cerrar es la peor combinacion posible.
        try:
            return await self._cerrar_todo()
        except Exception:
            logger.exception("El cierre masivo fallo a mitad")
            return (
                f"{self._cabecera()}\n"
                "El cierre fallo a mitad de camino. Puede haber quedado alguna\n"
                "posicion abierta: revisala con /posiciones y en MetaTrader."
            )

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

        self._confirmacion = {"momento": time.monotonic(), "posiciones": len(abiertas)}
        detalle = ", ".join(f"{p.symbol} {p.side}" for p in abiertas)
        real = " en la cuenta REAL" if self.settings.is_live else ""
        return (
            f"{self._cabecera()}\n"
            f"Vas a cerrar {len(abiertas)} posicion(es){real}:\n  {detalle}\n\n"
            f"Respondeme SI dentro de {VENTANA_CONFIRMACION_SEG} segundos.\n"
            "Cualquier otra cosa lo cancela, y despues de ese rato tambien."
        )

    async def _cerrar_todo(self) -> str:
        abiertas = self.store.open_positions()
        if not abiertas:
            return f"{self._cabecera()}\nYa no habia nada abierto."

        cerradas, fallidas = 0, []
        try:
            for posicion in list(abiertas):
                resultado = await self.engine.broker.close_position(
                    ticket=posicion.broker_ticket, symbol=posicion.symbol, fraction=1.0
                )
                if resultado.ok:
                    self.store.remove_position(posicion.trade_id)
                    cerradas += 1
                else:
                    fallidas.append(f"{posicion.symbol}: {resultado.reason}")
        finally:
            # Se persiste pase lo que pase. Si el broker se corta a mitad del
            # cierre masivo, lo ya cerrado tiene que quedar escrito: sin esto,
            # un reinicio resucitaba en el estado posiciones que en MT5 ya no
            # existian, y el bot las seguia contando contra MAX_OPEN_TRADES.
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
