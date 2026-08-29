"""Tests de la clasificacion de adjuntos y del despacho de mensajes.

No necesitan Telethon ni red: se usan mensajes falsos con la misma forma que
los de Telethon (`.message`, `.photo`, `.sticker`, `.document`...).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from tct.telegram.reader import TelegramReader, _media_kind


class FakeDocument:
    def __init__(self, mime_type: str = "") -> None:
        self.mime_type = mime_type


class FakeMessage:
    """Imita un `telethon.tl.custom.Message` con solo lo que usa el lector."""

    def __init__(self, text: str = "", *, message_id: int = 1, **media) -> None:
        self.message = text
        self.id = message_id
        self.date = datetime.now(timezone.utc)
        self.reply_to = None
        # Todo adjunto no declarado queda en None, igual que en Telethon.
        for name in (
            "sticker", "photo", "document", "gif", "dice", "game",
            "voice", "video_note", "contact", "geo", "poll",
        ):
            setattr(self, name, media.get(name))


class FakeEvent:
    def __init__(self, message: FakeMessage, chat_id: int = -100) -> None:
        self.message = message
        self.chat_id = chat_id


class FakeSettings:
    enable_ocr = False


def collect(message: FakeMessage, *, enable_ocr: bool = False) -> list[tuple[str, dict]]:
    """Corre _dispatch y devuelve lo que se le paso al motor (vacio = ignorado)."""
    recibido: list[tuple[str, dict]] = []

    async def on_message(text: str, metadata: dict) -> None:
        recibido.append((text, metadata))

    settings = FakeSettings()
    settings.enable_ocr = enable_ocr
    reader = TelegramReader(settings, on_message)
    asyncio.run(reader._dispatch(FakeEvent(message), is_edit=False))
    return recibido


# --------------------------------------------------------------------------
# Clasificacion de adjuntos
# --------------------------------------------------------------------------


def test_sticker_se_clasifica_como_sticker_y_no_como_documento():
    """Un sticker tambien es un Document: el orden del chequeo importa."""
    message = FakeMessage(sticker=FakeDocument("image/webp"), document=FakeDocument("image/webp"))
    assert _media_kind(message) == "sticker"


@pytest.mark.parametrize(
    "adjunto", ["sticker", "gif", "dice", "game", "voice", "video_note", "contact", "geo", "poll"]
)
def test_media_no_accionable_se_reconoce(adjunto):
    assert _media_kind(FakeMessage(**{adjunto: object()})) == adjunto


def test_foto_e_imagen_como_archivo():
    assert _media_kind(FakeMessage(photo=object())) == "photo"
    assert _media_kind(FakeMessage(document=FakeDocument("image/png"))) == "image_document"


def test_documento_que_no_es_imagen():
    assert _media_kind(FakeMessage(document=FakeDocument("application/pdf"))) == "document"


def test_mensaje_sin_adjunto():
    assert _media_kind(FakeMessage("hola")) == "none"


# --------------------------------------------------------------------------
# Despacho
# --------------------------------------------------------------------------


def test_sticker_sin_texto_se_ignora():
    """El caso que motiva todo esto: el grupo festeja un TP con un sticker."""
    assert collect(FakeMessage(sticker=FakeDocument("image/webp"))) == []


def test_sticker_no_llega_al_ocr_ni_con_ocr_encendido():
    """Un sticker ES una imagen. Con OCR encendido igual tiene que descartarse:
    el texto basura de un dibujo no puede terminar interpretado como senal."""
    assert collect(FakeMessage(sticker=FakeDocument("image/webp")), enable_ocr=True) == []


@pytest.mark.parametrize("adjunto", ["gif", "dice", "voice", "poll", "contact"])
def test_otros_adjuntos_sin_texto_se_ignoran(adjunto):
    assert collect(FakeMessage(**{adjunto: object()})) == []


def test_texto_suelto_llega_al_motor():
    recibido = collect(FakeMessage("XAUUSD BUY 2345"))
    assert len(recibido) == 1
    assert recibido[0][0] == "XAUUSD BUY 2345"
    assert recibido[0][1]["source"] == "text"


def test_caption_de_una_foto_llega_marcado_como_caption():
    recibido = collect(FakeMessage("XAUUSD BUY 2345", photo=object()))
    assert len(recibido) == 1
    assert recibido[0][1]["source"] == "caption"


def test_un_sticker_con_caption_igual_se_lee():
    """Raro, pero si hay texto el texto manda: no se pierde una senal."""
    recibido = collect(FakeMessage("Close 50% XAUUSD", sticker=FakeDocument("image/webp")))
    assert len(recibido) == 1
    assert recibido[0][0] == "Close 50% XAUUSD"


def test_foto_sin_texto_y_sin_ocr_se_ignora():
    assert collect(FakeMessage(photo=object()), enable_ocr=False) == []


def test_mensaje_vacio_se_ignora():
    assert collect(FakeMessage("   ")) == []


def test_los_metadatos_llegan_completos():
    recibido = collect(FakeMessage("XAUUSD BUY 2345", message_id=77))
    _, metadata = recibido[0]
    assert metadata["message_id"] == 77
    assert metadata["chat_id"] == -100
    assert metadata["is_edit"] is False


def test_un_mensaje_roto_no_tumba_el_listener():
    """Si _dispatch lanza, Telethon deja de entregar y el bot queda sordo."""

    class MensajeRoto:
        id = 1

        @property
        def message(self):
            raise RuntimeError("mensaje corrupto")

    recibido: list = []

    async def on_message(text, metadata):
        recibido.append(text)

    reader = TelegramReader(FakeSettings(), on_message)
    # No debe propagar la excepcion.
    asyncio.run(reader._dispatch(FakeEvent(MensajeRoto()), is_edit=False))
    assert recibido == []
