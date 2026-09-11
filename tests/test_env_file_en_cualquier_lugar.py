"""`--env-file` tiene que aceptarse antes Y despues del comando.

POR QUE
-------
Argparse, por defecto, solo acepta las opciones del parser principal ANTES del
subcomando:

    tct --env-file .env.segunda probar     funciona
    tct probar --env-file .env.segunda     "unrecognized arguments"

Pero la segunda es la que sale sola de escribir: uno piensa "quiero probar ESTE
archivo", no "con este archivo, quiero probar". Y el error de argparse no dice
que haya que moverlo de lugar, asi que no hay forma de deducir el arreglo si no
sabes como funciona argparse.

Esto importa justo cuando mas se usa la opcion: con dos cuentas a la vez, cada
comando del segundo bot la lleva. Se equivoco hasta la documentacion, que la
recomendaba en la forma que no andaba.
"""

from __future__ import annotations

import pytest

from tct.cli import build_parser

RUTA = ".env.segunda"


@pytest.mark.parametrize("argv", [
    ["--env-file", RUTA, "check"],
    ["check", "--env-file", RUTA],
    ["--env-file", RUTA, "probar"],
    ["probar", "--env-file", RUTA],
    ["probar", "--operar", "--env-file", RUTA],
    ["--env-file", RUTA, "informe", "--horas", "6"],
    ["informe", "--horas", "6", "--env-file", RUTA],
    ["--env-file", RUTA, "run"],
    ["run", "--esperar-mt5", "300", "--env-file", RUTA],
    ["--env-file", RUTA, "simular", "--horas", "2"],
    ["simular", "--horas", "2", "--env-file", RUTA],
    ["status", "--env-file", RUTA],
    ["mt5", "--env-file", RUTA],
])
def test_las_dos_posiciones_llegan_al_mismo_lado(argv):
    args = build_parser().parse_args(argv)

    assert args.env_file == RUTA


def test_sin_la_opcion_queda_en_none():
    """El default tiene que seguir siendo None: es lo que hace que se use el
    .env de siempre."""
    assert build_parser().parse_args(["check"]).env_file is None


def test_el_subcomando_no_pisa_el_valor_del_principal():
    """La trampa de este arreglo. Si el subparser tuviera default=None en vez de
    SUPPRESS, escribiria None encima del valor que el parser principal ya habia
    puesto, y la forma que SI funcionaba dejaria de funcionar."""
    args = build_parser().parse_args(["--env-file", RUTA, "probar", "--operar"])

    assert args.env_file == RUTA
    assert args.operar is True


@pytest.mark.parametrize("argv", [["-v", "check"], ["check", "-v"]])
def test_verbose_tambien_va_en_los_dos_lugares(argv):
    assert build_parser().parse_args(argv).verbose is True


def test_sin_verbose_queda_en_false():
    assert build_parser().parse_args(["check"]).verbose is False
