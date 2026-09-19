"""Limpieza entre tests.

`AvisosDelLog` se engancha al logger del motor para poder afirmar sobre lo que
el bot deja dicho. Si esos enganches no se sacaran, se irian acumulando de test
en test: es la misma familia del bug que dejaba `cli._run_async` reemplazado
para toda la corrida y envenenaba a los tests siguientes.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _sin_enganches_al_log():
    logger = logging.getLogger("tct.engine")
    antes = list(logger.handlers)
    nivel = logger.level
    yield
    for handler in list(logger.handlers):
        if handler not in antes:
            logger.removeHandler(handler)
    logger.setLevel(nivel)
