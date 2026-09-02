"""Tests del control por Telegram y de la pausa.

Es la capa que permite frenar el bot desde el telefono, asi que lo que se
verifica no es que "responda bonito" sino que la pausa realmente corte las
operaciones y que un comando dirigido a la instancia real no toque la demo.
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.store import Store
from tct.telegram.control import ControlTelegram
from tests.test_engine import build_settings, send


def armar(tmp_path, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker())
    control = ControlTelegram(settings, store, engine)
    return settings, store, engine, control


def cmd(control: ControlTelegram, texto: str) -> str | None:
    return asyncio.run(control.manejar(texto))


# --------------------------------------------------------------------------
# La pausa corta de verdad
# --------------------------------------------------------------------------


def test_pausado_registra_pero_no_opera(tmp_path):
    _, store, engine, control = armar(tmp_path)
    cmd(control, "/pausa")

    resultado = send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    assert resultado["status"] == "pausado"
    assert store.read_paper_trades() == [], "no debe registrar operaciones"
    assert store.open_positions() == [], "no debe abrir nada"
    assert any(e["kind"] == "pausado" for e in store.read_events()), "pero si dejar rastro"


def test_reanudar_vuelve_a_operar(tmp_path):
    _, store, engine, control = armar(tmp_path)
    cmd(control, "/pausa")
    cmd(control, "/reanudar")

    assert send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")["status"] == "aceptada"
    assert len(store.read_paper_trades()) == 1


def test_la_pausa_sobrevive_a_un_reinicio(tmp_path):
    """Si pausaste porque el mercado se puso feo, reiniciar NO debe reanudar."""
    settings, store, _, control = armar(tmp_path)
    cmd(control, "/pausa mercado raro")

    store2 = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    assert store2.is_paused
    assert "mercado raro" in store2.state.paused_reason


def test_pausar_no_cierra_lo_que_ya_estaba_abierto(tmp_path):
    _, store, engine, control = armar(tmp_path)
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    assert len(store.open_positions()) == 1

    cmd(control, "/pausa")

    assert len(store.open_positions()) == 1, "pausar frena lo nuevo, no liquida lo viejo"


# --------------------------------------------------------------------------
# Destinatarios: no confundir la real con la demo
# --------------------------------------------------------------------------


def test_un_comando_dirigido_a_otra_instancia_se_ignora(tmp_path):
    """El caso que importa: /pausa demo no debe frenar el bot real."""
    _, store, _, control = armar(tmp_path, instance_name="real")

    assert cmd(control, "/pausa demo") is None
    assert store.is_paused is False, "la instancia real no debia hacerle caso"


def test_un_comando_dirigido_a_mi_instancia_se_atiende(tmp_path):
    _, store, _, control = armar(tmp_path, instance_name="real")
    respuesta = cmd(control, "/pausa real")
    assert respuesta is not None
    assert store.is_paused is True


def test_un_comando_sin_destinatario_aplica_a_todos(tmp_path):
    _, store, _, control = armar(tmp_path, instance_name="real")
    cmd(control, "/pausa")
    assert store.is_paused is True


def test_la_respuesta_identifica_la_instancia(tmp_path):
    """Con dos bots contestando, hay que saber cual hablo."""
    _, _, _, control = armar(tmp_path, instance_name="real")
    assert "[REAL]" in cmd(control, "/estado")


def test_la_instancia_real_se_marca_en_las_respuestas(tmp_path):
    from tct.config import LIVE

    _, _, _, control = armar(
        tmp_path, instance_name="real", trading_mode=LIVE, allow_live_trading=True
    )
    assert "*** REAL ***" in cmd(control, "/estado")


# --------------------------------------------------------------------------
# Cerrar todo pide confirmacion
# --------------------------------------------------------------------------


def test_cerrar_todo_no_cierra_sin_confirmar(tmp_path):
    _, store, engine, control = armar(tmp_path)
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    respuesta = cmd(control, "/cerrar todo")

    assert "SI" in respuesta
    assert len(store.open_positions()) == 1, "todavia no debe haber cerrado nada"


def test_cerrar_todo_cierra_al_confirmar(tmp_path):
    _, store, engine, control = armar(tmp_path)
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    cmd(control, "/cerrar todo")
    respuesta = cmd(control, "SI")

    assert "Cerradas 1" in respuesta
    assert store.open_positions() == []


def test_otro_comando_cancela_la_confirmacion_pendiente(tmp_path):
    """Si cambiaste de tema, un 'si' posterior no debe cerrar nada."""
    _, store, engine, control = armar(tmp_path)
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    cmd(control, "/cerrar todo")
    cmd(control, "/estado")
    cmd(control, "SI")

    assert len(store.open_positions()) == 1, "la confirmacion tenia que haber caducado"


def test_cerrar_sin_posiciones_no_arma_confirmacion(tmp_path):
    _, _, _, control = armar(tmp_path)
    assert "Sin posiciones" in cmd(control, "/cerrar todo")
    assert control._confirmacion is None


# --------------------------------------------------------------------------
# Varios
# --------------------------------------------------------------------------


def test_los_mensajes_que_no_son_comandos_se_ignoran(tmp_path):
    _, _, _, control = armar(tmp_path)
    assert cmd(control, "hola que tal") is None
    assert cmd(control, "XAUUSD BUY 2345") is None


def test_un_comando_inexistente_se_ignora(tmp_path):
    _, _, _, control = armar(tmp_path)
    assert cmd(control, "/vender_todo_ya") is None


def test_estado_muestra_lo_que_importa(tmp_path):
    _, _, engine, control = armar(tmp_path)
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    respuesta = cmd(control, "/estado")
    assert "operando" in respuesta
    assert "Abiertas  : 1" in respuesta


def test_posiciones_lista_lo_abierto(tmp_path):
    _, _, engine, control = armar(tmp_path)
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")
    assert "XAUUSD" in cmd(control, "/posiciones")


def test_un_comando_que_explota_no_tumba_el_control(tmp_path):
    _, _, _, control = armar(tmp_path)

    def romper(*_a, **_k):
        raise RuntimeError("boom")

    control._estado = romper
    respuesta = cmd(control, "/estado")
    assert respuesta is not None and "fallo" in respuesta.lower()


# --------------------------------------------------------------------------
# Tope de perdida diaria
# --------------------------------------------------------------------------


SENAL_SIMPLE = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"


def _con_equity(tmp_path, inicial, actual, tope):
    """Arma un motor con la cuenta abriendo el dia en `inicial` y valiendo
    `actual` ahora. El equity se mueve en el BROKER, que es de donde el motor
    lo lee: setearlo en el store seria probar un mecanismo que no existe."""
    settings, store, engine, control = armar(tmp_path, max_daily_loss_pct=tope)
    engine.broker.equity_simulado = inicial
    store.day_start_balance(inicial)
    engine.broker.equity_simulado = actual
    return settings, store, engine, control


def test_el_tope_de_perdida_diaria_frena_las_aperturas(tmp_path):
    """El freno mas importante con dinero real. Estuvo escrito y desconectado:
    risk.py leia un valor que nadie asignaba fuera de los tests."""
    _, _, engine, _ = _con_equity(tmp_path, 10000.0, 9400.0, tope=5.0)  # -6%

    resultado = send(engine, SENAL_SIMPLE)

    assert resultado["status"] == "rechazada"
    assert any("perdida diaria" in r for r in resultado["reasons"])


def test_sin_tope_configurado_no_frena_nada(tmp_path):
    _, _, engine, _ = _con_equity(tmp_path, 10000.0, 1000.0, tope=0.0)  # -90%
    assert send(engine, SENAL_SIMPLE)["status"] == "aceptada"


def test_una_perdida_por_debajo_del_tope_deja_operar(tmp_path):
    _, _, engine, _ = _con_equity(tmp_path, 10000.0, 9700.0, tope=5.0)  # -3%
    assert send(engine, SENAL_SIMPLE)["status"] == "aceptada"


def test_si_el_broker_no_da_el_equity_no_se_inventa_un_rechazo(tmp_path):
    """Sin dato no se bloquea por las dudas: se opera y se sigue."""
    _, _, engine, _ = armar(tmp_path, max_daily_loss_pct=5.0)
    engine.broker.equity_simulado = None

    assert send(engine, SENAL_SIMPLE)["status"] == "aceptada"


def test_el_motor_lee_el_equity_del_broker(tmp_path):
    """La conexion que faltaba: que el valor viaje del broker al riesgo."""
    _, store, engine, _ = armar(tmp_path, max_daily_loss_pct=5.0)
    engine.broker.equity_simulado = 8000.0

    send(engine, SENAL_SIMPLE)

    assert store.balance_actual == 8000.0, "el motor no leyo el equity del broker"
    assert store.state.day_start_balance == 8000.0, "no se fijo la referencia del dia"


def test_la_ganancia_del_dia_nunca_frena(tmp_path):
    """Solo la caida importa: subir no puede activar el tope."""
    _, _, engine, _ = _con_equity(tmp_path, 10000.0, 12000.0, tope=5.0)
    assert send(engine, SENAL_SIMPLE)["status"] == "aceptada"


def test_las_respuestas_propias_no_re_disparan_comandos(tmp_path):
    """El handler escucha el chat entero y nuestras respuestas se mandan con
    la misma cuenta: sin guarda, una respuesta podria re-entrar en bucle."""
    _, _, _, control = armar(tmp_path)
    respuesta = cmd(control, "/estado")
    assert respuesta.startswith("[")
    assert cmd(control, respuesta) is None, "una respuesta propia no debe procesarse"


# --------------------------------------------------------------------------
# El cableado
# --------------------------------------------------------------------------
# Estos tests existen por un error concreto: el control se escribio, se probo
# unidad por unidad, y NUNCA se conecto al arranque. Los 27 tests de arriba
# pasaban porque instancian la clase a mano. Ninguno miraba si `run` la usa.


def test_el_arranque_conecta_el_control():
    """La pieza tiene que estar cableada, no solo existir."""
    import inspect

    from tct import cli

    fuente = inspect.getsource(cli._run_async)
    assert "ControlTelegram" in fuente, "el control no se instancia al arrancar"
    assert "escuchar_comandos" in fuente, "el control no se engancha a Telegram"


def test_el_lector_expone_su_cliente_para_el_control():
    """El control se engancha al MISMO cliente: dos sesiones corrompen el .session."""
    from tct.telegram.reader import TelegramReader

    assert hasattr(TelegramReader, "client")
    lector = TelegramReader(object(), None)
    assert lector.client is None, "sin start() todavia no hay cliente"


def test_sin_control_la_instancia_real_no_arranca():
    """Con dinero real, quedarse sin forma de frenarlo desde el telefono es
    motivo suficiente para no arrancar."""
    import inspect

    from tct import cli

    fuente = inspect.getsource(cli._run_async)
    assert "settings.is_live" in fuente
    # El aborto tiene que estar dentro del bloque que maneja el fallo del control.
    tramo = fuente[fuente.index("escuchar_comandos"):]
    assert "return" in tramo.split("encabezado")[0], "no aborta si falla el control en real"
