"""Lectura del grupo de senales con Telethon (sesion de usuario).

POR QUE TELETHON Y NO LA BOT API
---------------------------------
Un bot solo ve los mensajes de un grupo si un administrador lo agrega Y le
desactiva el modo privacidad. En un grupo de senales ajeno eso no va a pasar.
Telethon entra como la cuenta del usuario, que ya es miembro, y ve lo mismo
que ve la persona en su telefono.

La primera vez pide telefono y codigo de verificacion y guarda un archivo
`.session`. Ese archivo ES una credencial: da acceso a la cuenta de Telegram.
Por eso `.gitignore` lo excluye.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Firma del callback que recibe cada mensaje relevante.
MessageHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class TelegramReader:
    def __init__(self, settings, on_message: MessageHandler) -> None:
        self.settings = settings
        self.on_message = on_message
        self._client = None
        self._resolved_chats: list[Any] = []

    async def start(self) -> bool:
        """Conecta, resuelve los chats y engancha los handlers."""
        try:
            from telethon import TelegramClient, events
        except ImportError:
            logger.error("Falta Telethon. Instalalo con: pip install telethon")
            return False

        if not self.settings.telegram_api_id or not self.settings.telegram_api_hash:
            logger.error(
                "Faltan TELEGRAM_API_ID y TELEGRAM_API_HASH. Se sacan de https://my.telegram.org"
            )
            return False

        self._client = TelegramClient(
            self.settings.telegram_session_name,
            self.settings.telegram_api_id,
            self.settings.telegram_api_hash,
        )
        # start() abre el flujo interactivo de login si no hay sesion guardada.
        await self._client.start()

        me = await self._client.get_me()
        logger.info("Telegram conectado como %s (id=%s)", me.username or me.first_name, me.id)

        self._resolved_chats = await self._resolve_chats()
        if not self._resolved_chats:
            logger.error(
                "Ningun chat de TELEGRAM_SOURCE_CHATS pudo resolverse. "
                "Corre 'python -m tct.cli chats' para ver los IDs disponibles."
            )
            return False

        # Los mensajes editados importan tanto como los nuevos: los grupos
        # corrigen un SL equivocado editando el mensaje original en vez de
        # mandar uno nuevo.
        @self._client.on(events.NewMessage(chats=self._resolved_chats))
        async def _on_new(event):  # pragma: no cover - requiere red
            await self._dispatch(event, is_edit=False)

        @self._client.on(events.MessageEdited(chats=self._resolved_chats))
        async def _on_edit(event):  # pragma: no cover - requiere red
            await self._dispatch(event, is_edit=True)

        return True

    async def run_forever(self) -> None:
        if self._client is None:
            raise RuntimeError("Hay que llamar a start() antes que a run_forever()")
        await self._client.run_until_disconnected()

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.disconnect()

    # -- Internos ----------------------------------------------------------

    async def _resolve_chats(self) -> list[Any]:
        """Convierte lo que puso el usuario en el .env en entidades de Telegram.

        Se acepta @usuario, un ID numerico o un titulo exacto, porque cada
        grupo se identifica distinto y obligar a un solo formato es una fuente
        garantizada de confusion en la configuracion.
        """
        resolved: list[Any] = []
        for raw in self.settings.telegram_source_chats:
            candidate: Any = raw
            if raw.lstrip("-").isdigit():
                candidate = int(raw)
            try:
                entity = await self._client.get_entity(candidate)
                resolved.append(entity)
                title = getattr(entity, "title", None) or getattr(entity, "username", raw)
                logger.info("Escuchando: %s (id=%s)", title, getattr(entity, "id", "?"))
            except Exception as exc:
                logger.error("No se pudo resolver el chat '%s': %s", raw, exc)
        return resolved

    async def _dispatch(self, event, *, is_edit: bool) -> None:
        try:
            message = event.message
            text = (message.message or "").strip()
            source = "text"

            # Una senal puede venir como caption de una imagen. Si no hay ni
            # texto ni caption, se intenta OCR (si esta habilitado).
            if not text and getattr(message, "photo", None):
                text, source = await self._maybe_ocr(message)

            if not text:
                return

            metadata = {
                "message_id": message.id,
                "chat_id": event.chat_id,
                "is_edit": is_edit,
                "reply_to_message_id": getattr(message.reply_to, "reply_to_msg_id", None)
                if getattr(message, "reply_to", None)
                else None,
                "source": source,
                "date": message.date.isoformat() if message.date else None,
            }
            await self.on_message(text, metadata)
        except Exception:
            # Un mensaje raro no puede tumbar el listener: si esta corrutina
            # lanza, Telethon deja de entregar mensajes y el bot queda sordo.
            logger.exception("Error procesando un mensaje de Telegram")

    async def _maybe_ocr(self, message) -> tuple[str, str]:
        if not self.settings.enable_ocr:
            logger.info("Mensaje con imagen ignorado (ENABLE_OCR=false)")
            return "", "image_skipped"

        from tct.signals.ocr import extract_text_from_image

        try:
            image_bytes = await message.download_media(file=bytes)
        except Exception:
            logger.exception("No se pudo descargar la imagen")
            return "", "image_error"

        text = extract_text_from_image(image_bytes)
        if text:
            logger.info("OCR extrajo %d caracteres de una imagen", len(text))
        return text, "ocr"


async def list_available_chats(settings, limit: int = 60) -> list[dict[str, Any]]:
    """Lista los chats de la cuenta. Sirve para completar TELEGRAM_SOURCE_CHATS.

    Es la primera cosa que hay que correr despues de configurar el .env: sin
    los IDs, el bot no sabe que escuchar.
    """
    from telethon import TelegramClient

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.start()
    try:
        rows: list[dict[str, Any]] = []
        async for dialog in client.iter_dialogs(limit=limit):
            rows.append({
                "id": dialog.id,
                "title": dialog.title,
                "type": "grupo" if dialog.is_group else "canal" if dialog.is_channel else "privado",
                "username": getattr(dialog.entity, "username", None),
            })
        return rows
    finally:
        await client.disconnect()
