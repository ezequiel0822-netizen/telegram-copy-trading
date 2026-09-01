"""Tests del interprete de respaldo con IA local.

No hacen falta ni Ollama ni red: se simula la respuesta del modelo. Lo que se
verifica es lo que importa de verdad — que una alucinacion no se convierta en
una operacion.
"""

from __future__ import annotations

import asyncio

import pytest

from tct.intelligence.ollama import (
    OllamaParser,
    _aparece_en_texto,
    vale_la_pena_consultar,
)
from tct.signals.models import EventType, Side


class FakeSettings:
    ollama_url = "http://localhost:11434"
    ollama_model = "qwen2.5:7b"
    ollama_timeout_seconds = 180
    ollama_auto_execute = False
    enable_ollama = True


def interpretar(respuesta_del_modelo: dict, mensaje: str):
    """Corre el parser con una respuesta simulada del modelo."""
    parser = OllamaParser(FakeSettings())
    parser._consultar_sync = lambda _mensaje: respuesta_del_modelo
    return asyncio.run(parser.interpretar(mensaje, {"message_id": 1, "chat_id": -100}))


SENAL = "XAUUSD compren oro ahora 2345 protejan en 2335 objetivo 2355"


# --------------------------------------------------------------------------
# Guarda contra alucinaciones — el punto central de todo el modulo
# --------------------------------------------------------------------------


def test_precio_inventado_descarta_la_interpretacion_entera():
    """Si el modelo alucina UN numero, no se rescata el resto del mensaje."""
    evento = interpretar({
        "es_senal": True, "tipo": "ABRIR", "simbolo": "XAUUSD", "direccion": "BUY",
        "entrada": "2345", "stop_loss": "2335",
        "take_profits": ["9999"],  # este no esta en el mensaje
        "confianza": "alta", "razon": "compra de oro",
    }, SENAL)
    assert evento is None, "un modelo que invento un precio no es confiable para el resto"


def test_senal_con_todos_los_numeros_reales_se_acepta():
    evento = interpretar({
        "es_senal": True, "tipo": "ABRIR", "simbolo": "XAUUSD", "direccion": "BUY",
        "entrada": "2345", "stop_loss": "2335", "take_profits": ["2355"],
        "confianza": "alta", "razon": "compra de oro",
    }, SENAL)
    assert evento is not None
    assert evento.event_type is EventType.OPEN
    assert evento.symbol == "XAUUSD"
    assert evento.side is Side.BUY
    assert evento.entry == 2345.0
    assert evento.stop_loss == 2335.0
    assert evento.take_profits == [2355.0]


def test_lo_interpretado_por_ia_queda_marcado_como_tal():
    """Sin esto no se puede auditar despues que salio del modelo y que no."""
    evento = interpretar({
        "es_senal": True, "tipo": "ABRIR", "simbolo": "XAUUSD", "direccion": "BUY",
        "entrada": "2345", "stop_loss": "2335", "take_profits": ["2355"],
        "confianza": "media", "razon": "parece compra",
    }, SENAL)
    assert evento.source == "ollama"
    assert any("IA local" in w for w in evento.warnings)
    assert any("confianza media" in w for w in evento.warnings)


@pytest.mark.parametrize("inventado", ["2346", "2400", "234", "23450", "1.2345"])
def test_variantes_de_numero_inventado_se_rechazan(inventado):
    evento = interpretar({
        "es_senal": True, "tipo": "ABRIR", "simbolo": "XAUUSD", "direccion": "BUY",
        "entrada": inventado, "stop_loss": "2335", "take_profits": ["2355"],
        "confianza": "alta", "razon": "x",
    }, SENAL)
    assert evento is None


def test_separador_de_miles_no_se_confunde_con_invento():
    """El modelo devuelve 39500 y el mensaje dice 39,500: es el mismo numero."""
    mensaje = "US30 arranquen largos en 39,500 con stop 39,300 y salida 39,800"
    evento = interpretar({
        "es_senal": True, "tipo": "ABRIR", "simbolo": "US30", "direccion": "BUY",
        "entrada": "39500", "stop_loss": "39300", "take_profits": ["39800"],
        "confianza": "alta", "razon": "x",
    }, mensaje)
    assert evento is not None
    assert evento.entry == 39500.0


def test_decimales_recortados_por_el_modelo_se_aceptan():
    """El mensaje dice 1.2650 y el modelo devuelve 1.265: es el mismo numero."""
    mensaje = "libra compren en 1.2650 stop 1.2600 target 1.2700"
    evento = interpretar({
        "es_senal": True, "tipo": "ABRIR", "simbolo": "GBPUSD", "direccion": "BUY",
        "entrada": "1.265", "stop_loss": "1.26", "take_profits": ["1.27"],
        "confianza": "alta", "razon": "x",
    }, mensaje)
    assert evento is not None
    assert evento.entry == pytest.approx(1.265)


# --------------------------------------------------------------------------
# Descarte
# --------------------------------------------------------------------------


def test_si_el_modelo_dice_que_no_es_senal_se_ignora():
    assert interpretar({
        "es_senal": False, "tipo": "NINGUNO", "confianza": "alta", "razon": "es charla",
    }, SENAL) is None


def test_tipo_ninguno_se_ignora_aunque_diga_que_es_senal():
    assert interpretar({
        "es_senal": True, "tipo": "NINGUNO", "confianza": "baja", "razon": "no se",
    }, SENAL) is None


def test_si_ollama_no_responde_se_devuelve_none():
    parser = OllamaParser(FakeSettings())
    parser._consultar_sync = lambda _m: None
    assert asyncio.run(parser.interpretar(SENAL, {})) is None


def test_gestion_sin_numeros_se_acepta():
    """'cierren la mitad' no tiene precios que verificar, y esta bien."""
    evento = interpretar({
        "es_senal": True, "tipo": "CIERRE_PARCIAL", "simbolo": "XAUUSD",
        "direccion": "", "entrada": "", "stop_loss": "", "take_profits": [],
        "confianza": "alta", "razon": "cierre parcial",
    }, "muchachos cierren la mitad del oro que ya dio 50 pips")
    assert evento is not None
    assert evento.event_type is EventType.PARTIAL_CLOSE


# --------------------------------------------------------------------------
# Filtro previo: a quien se molesta al modelo
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "charla",
    ["Buenos dias grupo", "Gracias maestro!!", "Hola", "sube el precio hoy", "", "2345"],
)
def test_la_charla_no_llega_al_modelo(charla):
    assert vale_la_pena_consultar(charla) is False


@pytest.mark.parametrize(
    "candidato",
    ["oro compra 2345", "XAUUSD algo raro 2345 tp", "cierren 50% del eurusd"],
)
def test_los_mensajes_con_pinta_de_senal_si_llegan(candidato):
    assert vale_la_pena_consultar(candidato) is True


def test_un_mensaje_enorme_no_llega_al_modelo():
    """Satura el contexto de un modelo chico y casi nunca es una senal."""
    assert vale_la_pena_consultar("XAUUSD BUY 2345 " + "bla " * 500) is False


def test_el_filtro_previo_evita_la_llamada():
    """Verifica que no se gaste CPU: _consultar_sync no debe ejecutarse."""
    llamadas = []
    parser = OllamaParser(FakeSettings())
    parser._consultar_sync = lambda m: llamadas.append(m)
    asyncio.run(parser.interpretar("Buenos dias a todos", {}))
    assert llamadas == []


# --------------------------------------------------------------------------
# Verificacion de numeros, a bajo nivel
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor,mensaje",
    [
        (2345.0, "compra en 2345"),
        (39500.0, "entry 39,500"),
        (1.265, "buy at 1.2650"),
        (2345.5, "entrada 2345.5"),
    ],
)
def test_numeros_presentes_se_reconocen(valor, mensaje):
    assert _aparece_en_texto(valor, mensaje) is True


@pytest.mark.parametrize(
    "valor,mensaje",
    [
        (2350.0, "compra en 2345"),
        (234.0, "compra en 2345"),
        (23450.0, "compra en 2345"),
        (1.27, "buy at 1.2650"),
    ],
)
def test_numeros_ausentes_se_detectan(valor, mensaje):
    assert _aparece_en_texto(valor, mensaje) is False
