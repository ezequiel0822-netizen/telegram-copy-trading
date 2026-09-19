"""Una instancia REAL sin control por Telegram arranca, pero lo dice.

LA DECISION, del usuario (2026-09-18): "no quiero que ningun bot me avise si
abrio o no, solo quiero que lea los mensajes del telegram y lo haga". Avisos
apagados y control apagado, tambien en la cuenta real. Se respeta.

EL HUECO QUE DEJABA. La regla de la seccion 9 dice que con dinero real, si el
control no se puede activar, el bot NO arranca. Pero esa guarda vive DENTRO de
`if settings.enable_telegram_control:`: con el control apagado el bloque entero
se salteaba y no se imprimia una sola linea. Una instancia con dinero real y sin
freno remoto arrancaba igual que una con freno, en silencio.

Arrancar es lo que el usuario pidio. Callarselo, no: va al log del arranque,
que es la ventana que abre a mano, y no por Telegram.
"""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path

import pytest

from tct import cli
from tests.test_engine import build_settings


def settings(**extra):
    return build_settings(Path(tempfile.mkdtemp()), **extra)


def real(**extra):
    return settings(trading_mode="LIVE", allow_live_trading=True,
                    mt5_login="555", mt5_password="x", mt5_server="FxPro-MT5", **extra)


def test_real_sin_control_avisa():
    aviso = cli._aviso_sin_freno_remoto(real(enable_telegram_control=False))

    assert aviso is not None, "arranco con dinero real y sin freno sin decir nada"
    assert "DINERO REAL" in aviso
    assert "cerrar esta ventana" in aviso, "no dice como frenarlo"
    assert "ENABLE_TELEGRAM_CONTROL=true" in aviso, "no dice como recuperarlo"


def test_real_con_control_no_avisa_nada():
    assert cli._aviso_sin_freno_remoto(real(enable_telegram_control=True)) is None


@pytest.mark.parametrize("control", [True, False])
def test_en_demo_no_aplica(control):
    """En demo, sin control, no hay nada que advertir: no hay plata."""
    assert cli._aviso_sin_freno_remoto(settings(enable_telegram_control=control)) is None


def test_el_arranque_lo_usa():
    """El cableado. Los dos bugs mas caros del proyecto fueron codigo correcto
    que nadie llamaba."""
    fuente = inspect.getsource(cli._run_async)

    assert "_aviso_sin_freno_remoto" in fuente


def test_la_guarda_vieja_sigue_estando():
    """Lo que no hay que romper: si el control esta PRENDIDO y no se puede
    activar, una instancia real no arranca. Es otra cosa que esta."""
    fuente = inspect.getsource(cli._run_async)

    assert "Se aborta" in fuente
    assert "await reader.stop()" in fuente
