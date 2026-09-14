"""`scripts/LEEME.txt` tiene que describir TODOS los scripts.

POR QUE
-------
La carpeta tiene 16 archivos y el usuario -que no programa- pregunto cuales
podia borrar. La respuesta es ninguno: varios se llaman entre si, y borrar
`iniciar_auto.bat` deja el acceso directo del inicio de Windows apuntando a la
nada, sin ningun sintoma hasta que falten operaciones.

Asi que en vez de borrar archivos se explico cual es cual. Este test es lo que
evita que esa explicacion envejezca: agregar un script nuevo sin nombrarlo en
el LEEME lo vuelve a dejar sin explicacion, que es el problema original.
"""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
LEEME = SCRIPTS / "LEEME.txt"


def guiones() -> list[str]:
    return sorted(
        p.name for p in SCRIPTS.iterdir()
        if p.is_file() and p.suffix.lower() in {".bat", ".ps1", ".sh"}
    )


def test_el_leeme_existe():
    assert LEEME.is_file()


def test_nombra_todos_los_scripts():
    texto = LEEME.read_text(encoding="utf-8", errors="replace")

    sin_explicar = [g for g in guiones() if g not in texto]

    assert not sin_explicar, (
        "estos scripts no estan explicados en scripts/LEEME.txt: "
        + ", ".join(sin_explicar)
    )


def test_no_nombra_scripts_que_ya_no_existen():
    """La otra mitad: si alguien borra un script, el LEEME no puede seguir
    hablando de el."""
    texto = LEEME.read_text(encoding="utf-8", errors="replace")
    existentes = set(guiones())

    import re
    mencionados = set(re.findall(r"\b[\w_]+\.(?:bat|ps1|sh)\b", texto))
    fantasmas = sorted(m for m in mencionados if m not in existentes)

    assert not fantasmas, (
        "scripts/LEEME.txt nombra archivos que ya no existen: " + ", ".join(fantasmas)
    )


def test_avisa_de_los_que_no_hay_que_borrar():
    """Lo mas importante del archivo: que `iniciar_auto.bat` esta atado al
    acceso directo del inicio de Windows."""
    texto = LEEME.read_text(encoding="utf-8", errors="replace")

    assert "iniciar_auto.bat" in texto
    assert "inicio" in texto.lower()
