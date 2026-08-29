"""Notificaciones hacia el usuario, via Bot API.

Es el canal de salida: le avisa a tu padre que el bot tomo (o rechazo) una
senal, sin que tenga que mirar los logs. Es opcional; si no hay token
configurado, todo el sistema funciona igual y solo se pierde el aviso.

El partido en chunks de 4096 esta portado de `app/alerts/telegram_notifier.py`
de tradingalertaIA: Telegram devuelve 400 con mensajes mas largos y antes se
perdian enteros.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

TELEGRAM_MAX_CHARS = 4096


def split_message(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Parte el texto en trozos <= limit, cortando por salto de linea si puede."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 1, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


class Notifier:
    """Envia avisos por Telegram. Nunca lanza: un fallo de aviso no es un fallo de trading."""

    def __init__(self, settings) -> None:
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_notify_chat_id

    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send(self, text: str) -> bool:
        if not self.enabled():
            return False
        return await asyncio.to_thread(self._send_sync, text)

    def _send_sync(self, text: str) -> bool:
        ok = True
        for chunk in split_message(text):
            ok = self._send_chunk(chunk) and ok
        return ok

    def _send_chunk(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        try:
            with urllib.request.urlopen(url, data=payload, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            # Se loguea el tipo de error pero nunca el token ni el chat_id.
            logger.warning("No se pudo enviar la notificacion: %s", type(exc).__name__)
            return False

        if not data.get("ok"):
            logger.warning("Telegram no confirmo el envio de la notificacion")
            return False
        return True
