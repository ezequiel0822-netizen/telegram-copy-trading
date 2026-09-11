"""Las comillas dobles del .env rompen TODA ruta de MetaTrader.

LA TRAMPA
---------
`python-dotenv` interpreta las secuencias de escape solo cuando el valor esta
entre comillas DOBLES. Y toda instalacion de MetaTrader termina en
"\\terminal64.exe", asi que el `\\t` se convierte en un tabulador:

    MT5_PATH="C:\\Program Files\\FxPro MT5\\terminal64.exe"
                                          ^^ esto se vuelve un TAB

No es un caso raro: entrecomillar una ruta con espacios es lo que piden cmd y
PowerShell, asi que la costumbre correcta en todos lados rompe justamente la
unica variable donde el `\\t` es inevitable.

Y fallaba tarde y mal. El error salia recien al conectar con el broker, decia
"MT5_PATH apunta a un archivo que no existe" e imprimia la ruta con un hueco
en el medio que no se distingue de un espacio. Paso en produccion.
"""

from __future__ import annotations

import pytest

from tct.config import ConfigError, load_settings

RUTA = r"C:\Program Files\FxPro Markets MT5\terminal64.exe"
BASE = (
    "TELEGRAM_API_ID=1\n"
    "TELEGRAM_API_HASH=x\n"
    "TELEGRAM_SESSION_NAME=s\n"
    "TELEGRAM_SOURCE_CHATS=-100\n"
)


def escribir(tmp_path, linea):
    (tmp_path / ".env").write_text(BASE + linea + "\n", encoding="utf-8")
    return tmp_path / ".env"


def test_con_comillas_dobles_no_arranca(tmp_path):
    """El caso que paso de verdad."""
    env = escribir(tmp_path, 'MT5_PATH="' + RUTA + '"')

    with pytest.raises(ConfigError) as exc:
        load_settings(env)

    assert "MT5_PATH" in str(exc.value)


def test_el_error_dice_QUE_HACER(tmp_path):
    """El usuario no programa. "caracter invalido" no le sirve de nada: el
    mensaje tiene que nombrar las comillas y mostrar como queda bien."""
    env = escribir(tmp_path, 'MT5_PATH="' + RUTA + '"')

    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    mensaje = str(exc.value)

    assert "COMILLAS" in mensaje, "no nombra la causa"
    assert "MT5_PATH=C:" in mensaje, "no muestra como queda bien"


def test_sin_comillas_funciona(tmp_path):
    """Es la forma correcta, y los espacios no molestan."""
    settings = load_settings(escribir(tmp_path, "MT5_PATH=" + RUTA))

    assert settings.mt5_path == RUTA


def test_con_comillas_simples_tambien(tmp_path):
    """python-dotenv no interpreta escapes entre comillas simples."""
    settings = load_settings(escribir(tmp_path, "MT5_PATH='" + RUTA + "'"))

    assert settings.mt5_path == RUTA


def test_vacio_sigue_siendo_valido(tmp_path):
    """Con una sola instancia, vacio es lo MAS robusto: se engancha a la
    terminal que este abierta. No se puede romper eso."""
    assert load_settings(escribir(tmp_path, "MT5_PATH=")).mt5_path == ""


@pytest.mark.parametrize("escape", ["t", "n", "r", "b", "f", "v"])
def test_los_otros_escapes_tambien_se_atajan(tmp_path, escape):
    """`\\t` es el que pasa siempre por terminal64.exe, pero una carpeta que
    empiece con n, r, b, f o v tiene el mismo problema."""
    ruta = "C:\\Program Files\\MT5\\" + escape + "ueva\\terminal64.exe"
    env = escribir(tmp_path, 'MT5_PATH="' + ruta + '"')

    with pytest.raises(ConfigError):
        load_settings(env)


def test_una_ruta_normal_con_espacios_no_se_confunde(tmp_path):
    """La contracara: no puede rechazar rutas legitimas. Los espacios son
    normales en Windows y no tienen nada que ver con el problema."""
    ruta = r"C:\Program Files\MetaTrader 5 de FxPro\terminal64.exe"

    settings = load_settings(escribir(tmp_path, "MT5_PATH=" + ruta))

    assert settings.mt5_path == ruta
