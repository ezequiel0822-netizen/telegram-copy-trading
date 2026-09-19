"""Las variables del sistema de avisos que se saco no se ignoran callado.

El bot mandaba avisos por Telegram y el usuario pidio que no le escriba nunca,
asi que el sistema se saco del proyecto: TELEGRAM_BOT_TOKEN,
TELEGRAM_NOTIFY_CHAT_ID y TELEGRAM_NOTIFY_LEVEL ya no hacen nada.

Pero sus .env las tienen. El `.env` de siempre tiene un token puesto, y en los
pasos para armar `.env.real` se le dijo que pusiera TELEGRAM_NOTIFY_LEVEL=none.
Si se ignoraran en silencio, la persona queda creyendo que configuro algo. Y
antes, un nivel mal escrito levantaba un error al arrancar: sacar el sistema
convirtio ese error en silencio, que es justo lo que ese error evitaba.

No es un error -el bot anda igual-: es un aviso que dice que se puede borrar.
"""

from __future__ import annotations

from tct.config import load_settings

BASE = (
    "TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\n"
    "TELEGRAM_SESSION_NAME=s\nTELEGRAM_SOURCE_CHATS=-100\n"
    "TRADING_MODE=PAPER_ONLY\n"
)


def cargar(tmp_path, extra=""):
    (tmp_path / ".env").write_text(BASE + extra, encoding="utf-8")
    return load_settings(tmp_path / ".env")


def avisos_de_obsoletas(settings):
    return [w for w in settings.warnings if "ya no se usa" in w]


def test_un_token_viejo_se_avisa(tmp_path):
    """El caso del `.env` de siempre del usuario."""
    settings = cargar(tmp_path, "TELEGRAM_BOT_TOKEN=123:ABC\n")

    avisos = avisos_de_obsoletas(settings)
    assert avisos, "un token que no hace nada se ignoro callado"
    assert "TELEGRAM_BOT_TOKEN" in avisos[0]
    assert "borrar" in avisos[0], "no dice que hacer"


def test_el_nivel_que_se_le_dijo_que_pusiera_tambien(tmp_path):
    """Se le dijo TELEGRAM_NOTIFY_LEVEL=none para .env.real antes de sacar el
    sistema. Esa linea ahora sobra, y hay que decirselo."""
    settings = cargar(tmp_path, "TELEGRAM_NOTIFY_LEVEL=none\n")

    assert "TELEGRAM_NOTIFY_LEVEL" in avisos_de_obsoletas(settings)[0]


def test_las_tres_juntas_en_un_solo_aviso(tmp_path):
    settings = cargar(tmp_path, "TELEGRAM_BOT_TOKEN=x\nTELEGRAM_NOTIFY_CHAT_ID=1\n"
                                "TELEGRAM_NOTIFY_LEVEL=all\n")

    avisos = avisos_de_obsoletas(settings)
    assert len(avisos) == 1, "tres lineas de lo mismo es ruido"
    for clave in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_NOTIFY_CHAT_ID", "TELEGRAM_NOTIFY_LEVEL"):
        assert clave in avisos[0]


def test_vacias_no_molestan(tmp_path):
    """Las plantillas viejas las traian vacias. Una linea vacia no configura
    nada, asi que no hay nada que avisar."""
    settings = cargar(tmp_path, "TELEGRAM_BOT_TOKEN=\nTELEGRAM_NOTIFY_CHAT_ID=\n")

    assert avisos_de_obsoletas(settings) == []


def test_un_env_limpio_no_avisa_nada(tmp_path):
    assert avisos_de_obsoletas(cargar(tmp_path)) == []
