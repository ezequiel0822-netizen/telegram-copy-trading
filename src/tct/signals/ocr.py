"""Hook de OCR para senales que vienen dentro de una imagen.

APAGADO POR DEFECTO (ENABLE_OCR=false).

Esta preparado pero desactivado a proposito. Encenderlo implica instalar
Tesseract, que en macOS es una dependencia de sistema aparte:

    brew install tesseract
    pip install pytesseract pillow

Y ademas exige calibracion: leer mal un digito de un precio es peor que no
leer nada, porque produce una operacion con numeros inventados en vez de un
rechazo visible. Por eso el pipeline trata el texto de OCR como sospechoso y
lo marca con `source="ocr"` en todos los registros, para poder auditar aparte
que tan bien viene funcionando antes de confiarle plata.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_UNAVAILABLE_LOGGED = False


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def extract_text_from_image(image_bytes: bytes) -> str:
    """Devuelve el texto de una imagen, o "" si no se pudo.

    Nunca lanza: si el OCR falla, el mensaje simplemente se ignora igual que
    si no tuviera texto.
    """
    global _UNAVAILABLE_LOGGED

    if not image_bytes:
        return ""

    try:
        import io

        import pytesseract
        from PIL import Image
    except ImportError:
        if not _UNAVAILABLE_LOGGED:
            logger.warning(
                "ENABLE_OCR=true pero falta pytesseract/pillow. "
                "Instala: brew install tesseract && pip install pytesseract pillow"
            )
            _UNAVAILABLE_LOGGED = True
        return ""

    try:
        image = Image.open(io.BytesIO(image_bytes))
        # Escala de grises y upscale x2: las capturas de Telegram vienen
        # comprimidas y Tesseract falla con texto chico.
        image = image.convert("L")
        image = image.resize((image.width * 2, image.height * 2))
        text = pytesseract.image_to_string(image)
        return (text or "").strip()
    except Exception:
        logger.exception("El OCR fallo sobre una imagen")
        return ""
