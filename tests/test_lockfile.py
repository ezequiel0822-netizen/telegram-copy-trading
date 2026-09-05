"""Que dos bots no puedan compartir la misma carpeta de datos.

El escenario que esto evita no es exotico: con dos instancias corriendo, un
`.env` copiado sin cambiar las rutas deja a los dos escribiendo el mismo
`state.json`. El que guarda ultimo pisa las posiciones del otro, y una
posicion que desaparece del estado queda viva en MetaTrader sin que ningun
bot la conozca.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from tct.lockfile import CarpetaOcupada, LockDeInstancia, lock_para
from tests.test_engine import build_settings


def test_el_segundo_no_puede_tomar_lo_que_el_primero_tiene(tmp_path):
    ruta = tmp_path / "state.json.lock"
    primero = LockDeInstancia(ruta, instancia="fxpro")
    primero.tomar()

    try:
        with pytest.raises(CarpetaOcupada):
            LockDeInstancia(ruta, instancia="exness").tomar()
    finally:
        primero.soltar()


def test_al_soltarlo_el_siguiente_puede_tomarlo(tmp_path):
    ruta = tmp_path / "state.json.lock"
    primero = LockDeInstancia(ruta)
    primero.tomar()
    primero.soltar()

    segundo = LockDeInstancia(ruta)
    segundo.tomar()  # no debe lanzar
    segundo.soltar()


def test_sirve_como_context_manager(tmp_path):
    ruta = tmp_path / "state.json.lock"

    with LockDeInstancia(ruta):
        with pytest.raises(CarpetaOcupada):
            LockDeInstancia(ruta).tomar()

    LockDeInstancia(ruta).tomar()  # afuera del with ya se solto


def test_un_lock_viejo_en_el_disco_no_bloquea_nada(tmp_path):
    """La diferencia entre un lock del sistema y un archivo-con-PID: si el bot
    murio por un corte de luz, el .lock queda en el disco y NO tiene que
    impedir arrancar de nuevo. Nadie deberia tener que borrarlo a mano."""
    ruta = tmp_path / "state.json.lock"
    ruta.write_text("99999\n", encoding="utf-8")  # de un proceso que ya no existe

    LockDeInstancia(ruta).tomar()  # no debe lanzar


def test_el_motivo_explica_las_dos_causas(tmp_path):
    ruta = tmp_path / "state.json.lock"
    primero = LockDeInstancia(ruta, instancia="fxpro")
    primero.tomar()

    try:
        with pytest.raises(CarpetaOcupada) as exc:
            LockDeInstancia(ruta, instancia="exness").tomar()
    finally:
        primero.soltar()

    texto = str(exc.value)
    assert "ya esta corriendo en otra ventana" in texto
    assert "DATA_DIR" in texto, "no muestra como separar las carpetas"
    assert "fxpro" in texto, "no dice de que instancia es el lock"


def test_el_lock_sale_del_state_path(tmp_path):
    """Se ata al state.json porque es el archivo cuyo pisoteo hace dano."""
    settings = build_settings(tmp_path, instance_name="demo")

    assert lock_para(settings).path.name == "state.json.lock"


def test_dos_instancias_con_carpetas_distintas_conviven(tmp_path):
    """Lo que NO hay que romper: el caso normal son dos bots corriendo a la
    vez, cada uno con su carpeta."""
    a = build_settings(tmp_path / "fxpro", state_path=tmp_path / "fxpro" / "state.json")
    b = build_settings(tmp_path / "exness", state_path=tmp_path / "exness" / "state.json")

    with lock_para(a), lock_para(b):
        pass  # los dos a la vez, sin quejarse


# --------------------------------------------------------------------------
# La garantia de verdad: dos PROCESOS distintos
# --------------------------------------------------------------------------


def test_otro_proceso_no_puede_tomarlo(tmp_path):
    """Los tests de arriba corren en un solo proceso. El caso real son dos, y
    es lo unico que prueba que el lock lo hace el sistema operativo y no una
    variable en memoria."""
    ruta = tmp_path / "state.json.lock"
    mio = LockDeInstancia(ruta, instancia="fxpro")
    mio.tomar()

    programa = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(_raiz_src())!r})
        from tct.lockfile import CarpetaOcupada, LockDeInstancia
        try:
            LockDeInstancia({str(ruta)!r}).tomar()
        except CarpetaOcupada:
            print("BLOQUEADO")
        else:
            print("LO TOMO")
    """)

    try:
        salida = subprocess.run(
            [sys.executable, "-c", programa],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        mio.soltar()

    assert "BLOQUEADO" in salida.stdout, (
        f"otro proceso pudo tomar el lock. stdout={salida.stdout!r} "
        f"stderr={salida.stderr!r}"
    )


def _raiz_src() -> str:
    from pathlib import Path

    import tct

    return str(Path(tct.__file__).resolve().parent.parent)


# --------------------------------------------------------------------------
# El cableado: que 'tct run' lo tome de verdad
#
# Este proyecto tiene historial de protecciones escritas y desconectadas: el
# control por Telegram y el freno diario estuvieron los dos en el codigo, con
# sus tests en verde, sin que nadie los llamara.
# --------------------------------------------------------------------------


def test_run_toma_el_lock(tmp_path, monkeypatch):
    """Se verifica por introspeccion del codigo de cmd_run, igual que se hizo
    con _run_async y el control por Telegram."""
    import inspect

    from tct import cli

    fuente = inspect.getsource(cli.cmd_run)

    assert "lock_para" in fuente, "cmd_run no pide el lock"
    assert "CarpetaOcupada" in fuente, "no maneja el caso de carpeta ocupada"
    assert "lock.soltar()" in fuente, "no lo suelta al terminar"


def test_run_se_niega_a_arrancar_si_la_carpeta_esta_ocupada(tmp_path, capsys):
    """El efecto, no solo el cableado: con el lock tomado, cmd_run devuelve
    error y NO llega a conectarse a nada.

    Se lee de capsys y no de caplog porque `setup_logging` llama a
    `basicConfig(force=True)`, que borra los handlers que pone pytest. El log
    va a stdout, asi que ahi se lo busca.
    """
    import argparse

    from tct import cli

    settings = build_settings(tmp_path, state_path=tmp_path / "state.json")
    ocupado = lock_para(settings)
    ocupado.tomar()

    llamadas = []

    def no_deberia_correr(_settings):
        llamadas.append("arranco")

    original_load = cli.load_settings
    cli.load_settings = lambda _ruta: settings
    cli._run_async = no_deberia_correr
    try:
        codigo = cli.cmd_run(argparse.Namespace(env_file=None, verbose=False))
    finally:
        cli.load_settings = original_load
        ocupado.soltar()

    assert codigo == 1, "arranco igual con la carpeta ocupada"
    assert llamadas == [], "llego a conectarse teniendo la carpeta tomada"
    assert "Ya hay otro bot" in capsys.readouterr().out
