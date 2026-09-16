"""`simular --ejecutar` no toca una cuenta con dinero real.

POR QUE
-------
`simular` reproduce los mensajes de las ultimas N horas. Ejecutarlos de verdad
significa abrir posiciones siguiendo senales VIEJAS, a precios que ya pasaron.
No hay ninguna situacion en la que eso sea lo que alguien queria con plata
real.

Y el riesgo no era teorico: `simular` se usa en demo desde el primer dia del
proyecto, asi que agregarle `--env-file .env.real` por costumbre alcanzaba.
Medido contra una cuenta real de FxPro de 500, antes de este arreglo:

    Ejecutando contra: mt5 (modo LIVE)
      [aceptada] XAUUSD BUY 4438 SL 4430 TP1 4442 ...
      [aceptada] GOLD SELL 4437 SL 4445 TP1 4433 ...
      Quedaron 2 posicion(es) abiertas
      "Si operaste contra MT5 demo, revisalas ... y cerralas a mano"

Dos posiciones reales abiertas, y el mensaje final dando por sentado que
estabas en demo.

Lo que se afirma aca es la propiedad fuerte: con `is_live`, NUNCA se construye
un broker. No alcanza con que no mande ordenes -conectar ya elige una terminal
y una cuenta-.
"""

from __future__ import annotations

import asyncio

import pytest

from tct import cli
from tests.test_engine import build_settings

MENSAJE = ("GOLD BUY XAUUSD 4438 SL 4430 TP1 4442 TP2 4444 TP3 4446",
           {"message_id": 1, "chat_id": -100})


@pytest.fixture
def sin_telegram(monkeypatch):
    """El lector de Telegram devuelve una senal operable, sin red."""
    async def falso_fetch(settings, horas=24, limite=None):
        return [MENSAJE]

    monkeypatch.setattr(
        "tct.telegram.reader.fetch_recent_messages", falso_fetch, raising=False
    )


@pytest.fixture
def broker_prohibido(monkeypatch):
    """Construir un broker ya es elegir una terminal y una cuenta."""
    def explota(settings):
        raise AssertionError("se construyo un broker contra la cuenta real")

    monkeypatch.setattr("tct.brokers.base.build_broker", explota)


class Args:
    horas = 24
    limite = None
    ejecutar = True
    con_precios = False
    todos = False


def correr(settings):
    return asyncio.run(cli._simular_async(settings, Args()))


def test_con_dinero_real_no_ejecuta(tmp_path, sin_telegram, broker_prohibido, capsys):
    settings = build_settings(
        tmp_path, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="x", mt5_server="FxPro-MT5",
    )

    codigo = correr(settings)

    assert codigo == 1, "salio como si hubiera corrido bien"
    salida = capsys.readouterr().out
    assert "DINERO REAL" in salida
    assert "probar --operar" in salida, "no ofrece la alternativa que si sirve"


def test_en_demo_sigue_ejecutando(tmp_path, sin_telegram, monkeypatch):
    """Lo que no hay que romper: en demo es la herramienta que encontro dos
    bugs reales. Tiene que seguir llegando al broker."""
    settings = build_settings(tmp_path)
    llamadas = []

    def espia(s):
        llamadas.append(s)
        from tct.brokers.paper import PaperBroker
        return PaperBroker()

    monkeypatch.setattr("tct.brokers.base.build_broker", espia)

    correr(settings)

    assert llamadas, "en demo dejo de construir el broker"
