"""El contrato entre los lanzadores .bat y la CLI.

POR QUE
-------
El arranque automatico es la unica parte del sistema que corre SIN que nadie
mire. Si `iniciar_auto.bat` arma un comando que la CLI no entiende, el bot no
levanta al prender la PC y no hay ningun sintoma: no se abre una ventana con
un error, simplemente no hay operaciones ese dia.

Los .bat no se pueden correr desde pytest, pero si se puede verificar que el
comando que arman lo acepta el parser. Que es exactamente lo que se rompio una
vez: `--env-file` solo andaba ANTES del subcomando.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tct.cli import build_parser

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def test_el_lanzador_automatico_arma_un_comando_que_la_cli_entiende():
    """El comando exacto de iniciar_auto.bat, tal como queda con argumento."""
    args = build_parser().parse_args(
        ["--env-file", ".env.segunda", "run", "--esperar-mt5", "300"]
    )

    assert args.env_file == ".env.segunda"
    assert args.esperar_mt5 == 300
    assert args.command == "run"


def test_tambien_con_el_env_por_defecto():
    """Sin argumento en el acceso directo, el .bat pasa '.env'."""
    args = build_parser().parse_args(["--env-file", ".env", "run", "--esperar-mt5", "300"])

    assert args.env_file == ".env"


def test_el_lanzador_pasa_el_archivo_a_la_cli():
    """Que el .bat siga mandando --env-file. Sin esto, el acceso directo de la
    segunda instancia arrancaria el bot PRINCIPAL: dos procesos sobre la misma
    cuenta, y el segundo muriendo por carpeta ocupada."""
    texto = (SCRIPTS / "iniciar_auto.bat").read_text(encoding="utf-8", errors="replace")

    assert "--env-file" in texto, "el lanzador dejo de pasar la configuracion"
    assert "%ARCHIVO%" in texto, "el lanzador dejo de aceptar el argumento"


def test_el_lanzador_sigue_esperando_a_metatrader():
    """Sin `--esperar-mt5` el bot pierde la carrera contra MetaTrader al
    encender la PC, que es el bug que motivo que este archivo exista."""
    texto = (SCRIPTS / "iniciar_auto.bat").read_text(encoding="utf-8", errors="replace")

    assert "--esperar-mt5" in texto


def test_el_lanzador_cae_en_el_env_de_siempre_sin_argumento():
    """Los accesos directos creados por la version anterior no pasan ningun
    argumento. Tienen que seguir arrancando el bot principal."""
    texto = (SCRIPTS / "iniciar_auto.bat").read_text(encoding="utf-8", errors="replace")

    assert re.search(r'if\s+"%ARCHIVO%"==""\s+set\s+"?ARCHIVO=\.env"?', texto), (
        "sin argumento ya no cae en .env"
    )


@pytest.mark.parametrize("guion", ["autoarranque.ps1", "iniciar_auto.bat",
                                   "iniciar_bot.bat", "iniciar_segunda.bat"])
def test_los_guiones_del_arranque_existen(guion):
    """`autoarranque.ps1` crea accesos directos que apuntan a estos archivos.
    Renombrar uno deja el acceso directo del inicio apuntando a la nada, y eso
    solo se descubre al reiniciar la PC."""
    assert (SCRIPTS / guion).is_file()


def test_el_script_de_arranque_conoce_las_dos_instancias():
    texto = (SCRIPTS / "autoarranque.ps1").read_text(encoding="utf-8", errors="replace")

    assert ".env.segunda" in texto
    assert "Bot de Trading (segunda).lnk" in texto, "el segundo acceso cambio de nombre"
    assert "Bot de Trading.lnk" in texto, (
        "el nombre del acceso principal cambio: los que ya estan puestos en el "
        "inicio quedarian huerfanos y habria dos"
    )
