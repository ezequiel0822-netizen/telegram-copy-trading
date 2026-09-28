"""Guardas que funcionaban pero que ningun test protegia (auditoria 28/09).

El revisor de calidad rompio 80 guardas de a una y estas dejaban la suite en
verde: cualquiera podia romperse en un cambio futuro sin que nada avisara.
Tambien estan aca los dos avisos que se contradecian o mentian.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tct.brokers.mt5_native import MAGIA, MT5NativeBroker
from tct.engine import Engine
from tct.signals.models import OrderType, Side
from tct.store import Store
from tests.fake_mt5 import FakeMT5, FakeResult, enchufar
from tests.test_auditoria_ejecucion import SENAL, Terminal, armar
from tests.test_engine import AvisosDelLog, build_settings, send

OTRA = "XAUUSD BUY\nEntry 4433\nSL 4425\nTP 4437"


def hace(minutos: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()


def abrir(broker, lot=0.01, order_type=OrderType.MARKET, entry=4432.0):
    return asyncio.run(broker.open_order(
        symbol="XAUUSD", side=Side.BUY, order_type=order_type, lot=lot,
        entry=entry, stop_loss=4424.0, take_profit=4436.0))


# --------------------------------------------------------------------------
# Topes y lotes
# --------------------------------------------------------------------------


def test_el_cupo_diario_frena_la_senal_siguiente(tmp_path):
    engine, store, terminal = armar(tmp_path, max_signals_per_day=2, max_open_trades=10,
                                    max_positions_per_symbol=0)
    send(engine, SENAL, message_id=1)
    send(engine, OTRA, message_id=2)

    tercera = send(engine, SENAL.replace("4432", "4431"), message_id=3)

    assert tercera["status"] == "rechazada"
    assert "Cupo diario" in " ".join(tercera["reasons"])


def test_max_lot_frena_aunque_el_exceso_sea_chico(tmp_path):
    """0.06 con MAX_LOT=0.05: antes solo se probaba un exceso de 10 veces."""
    settings = build_settings(tmp_path, max_lot=0.05, default_lot=0.05)
    terminal = Terminal()
    terminal.simbolos["XAUUSD"]["volume_min"] = 0.06
    broker = enchufar(MT5NativeBroker(settings), terminal)

    resultado = abrir(broker, lot=0.05)

    assert not resultado.ok and "MAX_LOT" in resultado.reason
    assert terminal.aperturas() == []


def test_un_volumen_mayor_al_maximo_del_instrumento_no_sale(tmp_path):
    settings = build_settings(tmp_path, max_lot=5.0)
    terminal = Terminal()
    terminal.simbolos["XAUUSD"]["volume_max"] = 1.0
    broker = enchufar(MT5NativeBroker(settings), terminal)

    resultado = abrir(broker, lot=2.0)

    assert not resultado.ok
    assert terminal.aperturas() == []


# --------------------------------------------------------------------------
# Lo que contesta un servidor de verdad
# --------------------------------------------------------------------------


def test_mover_el_stop_conserva_el_take_profit(tmp_path):
    """Si el pedido de stop mandara tp=0, cada breakeven le borraria el TP a
    la posicion real."""
    engine, store, terminal = armar(tmp_path)
    send(engine, SENAL, message_id=1)

    send(engine, "mover a breakeven", message_id=2)

    posicion = terminal.posiciones_abiertas()[0]
    assert posicion.sl == 4432.5
    assert posicion.tp == 4436.0, "el breakeven le borro el TP"


def test_un_cierre_sin_respuesta_que_no_cerro_no_se_da_por_cerrado(tmp_path):
    engine, store, terminal = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    original = FakeMT5.order_send

    def cierre_perdido(request):
        if "position" in request:
            terminal.enviados.append(dict(request))
            return None  # no llego nunca al servidor
        return original(terminal, request)
    terminal.order_send = cierre_perdido

    resultado = send(engine, "cerrar XAUUSD", message_id=2)

    assert resultado["status"] == "cierre_parcial_fallido"
    assert len(store.open_positions()) == 1
    assert len(terminal.posiciones_abiertas()) == 1


def test_un_10008_a_mercado_es_una_posicion_que_entro(tmp_path):
    """PLACED (10008) en una orden a mercado: aceptada y todavia ejecutandose.
    El fake nunca lo devolvia."""
    settings = build_settings(tmp_path)
    terminal = Terminal()
    broker = enchufar(MT5NativeBroker(settings), terminal)
    original = FakeMT5.order_send

    def colocada(request):
        resultado = original(terminal, request)
        resultado.retcode = 10008
        return resultado
    terminal.order_send = colocada

    resultado = abrir(broker)

    assert resultado.ok, resultado.reason
    assert resultado.ticket == terminal.posiciones_abiertas()[0].ticket


def test_una_recotizacion_en_una_pendiente_no_se_reintenta(tmp_path):
    engine, store, terminal = armar(tmp_path, max_pending_distance_pct=5.0)
    terminal.recotizar = 5

    send(engine, "XAUUSD BUY LIMIT\nEntry 4420\nSL 4412\nTP 4430", message_id=1)

    assert len(terminal.aperturas()) == 1


def test_sin_poder_mirar_antes_una_posicion_propia_vieja_no_es_la_nueva(tmp_path):
    settings = build_settings(tmp_path)
    terminal = Terminal()
    broker = enchufar(MT5NativeBroker(settings), terminal)
    vieja = abrir(broker)
    llamadas = {"n": 0}
    original_positions = Terminal.positions_get

    def falla_la_primera(ticket=None, symbol=None):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return None
        return original_positions(terminal, ticket=ticket, symbol=symbol)
    terminal.positions_get = falla_la_primera
    terminal.sin_ejecutar = True

    resultado = abrir(broker)

    assert not resultado.ok, f"tomo la posicion vieja {vieja.ticket} como la nueva"


def test_el_cierre_manda_el_lado_contrario_de_una_venta(tmp_path):
    engine, store, terminal = armar(tmp_path)
    send(engine, "XAUUSD SELL\nEntry 4431\nSL 4439\nTP 4427", message_id=1)

    send(engine, "cerrar XAUUSD", message_id=2)

    assert terminal.posiciones_abiertas() == []
    assert store.open_positions() == []


# --------------------------------------------------------------------------
# Al conectar
# --------------------------------------------------------------------------


def conectar(tmp_path, monkeypatch, terminal, **overrides):
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO", **overrides)
    monkeypatch.setitem(sys.modules, "MetaTrader5", terminal)
    return asyncio.run(MT5NativeBroker(settings).connect())


def test_con_algo_trading_apagado_no_conecta(tmp_path, monkeypatch):
    terminal = Terminal()
    terminal.terminal_info = lambda: SimpleNamespace(trade_allowed=False)

    assert conectar(tmp_path, monkeypatch, terminal) is False


def test_una_demo_sin_permiso_para_operar_no_conecta(tmp_path, monkeypatch):
    terminal = Terminal()
    original = terminal.account_info

    def sin_permiso():
        cuenta = original()
        datos = {**cuenta._asdict(), "trade_allowed": False}
        cuenta._asdict = lambda: datos
        return cuenta
    terminal.account_info = sin_permiso

    assert conectar(tmp_path, monkeypatch, terminal) is False


# --------------------------------------------------------------------------
# La ventana de 10 minutos, en el borde
# --------------------------------------------------------------------------


def test_una_edicion_de_hace_11_minutos_no_abre(tmp_path):
    engine, store, terminal = armar(tmp_path)

    resultado = send(engine, SENAL, message_id=1, is_edit=True, date=hace(11))

    assert resultado["status"] == "edicion_ignorada"
    assert terminal.posiciones_abiertas() == []


def test_una_edicion_de_hace_9_minutos_si_abre(tmp_path):
    engine, store, terminal = armar(tmp_path)

    resultado = send(engine, SENAL, message_id=1, is_edit=True, date=hace(9))

    assert resultado["status"] == "aceptada"


# --------------------------------------------------------------------------
# Una excepcion a mitad de una apertura
# --------------------------------------------------------------------------


def test_una_excepcion_despues_de_abrir_no_deja_reabrir_con_una_edicion(tmp_path):
    engine, store, terminal = armar(tmp_path, positions_per_signal=2, max_open_trades=5,
                                    max_positions_per_symbol=0)
    original = engine.broker.open_order
    llamadas = {"n": 0}

    async def falla_la_segunda(**kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise RuntimeError("se corto algo")
        return await original(**kwargs)
    engine.broker.open_order = falla_la_segunda
    senal = "XAUUSD BUY\nEntry 4432\nSL 4424\nTP 4436\nTP 4440"

    primera = send(engine, senal, message_id=1, date=hace(0))
    edicion = send(engine, senal, message_id=1, is_edit=True, date=hace(1))

    assert primera["status"] == "aceptada", primera
    assert edicion["status"] != "aceptada", "la edicion volvio a abrir"
    assert len(terminal.posiciones_abiertas()) == 1
    assert store.signals_today() == 1


# --------------------------------------------------------------------------
# Avisos
# --------------------------------------------------------------------------


class IAQueDiceApertura:
    async def interpretar(self, texto, _metadata):
        from tct.signals.models import EventType, SignalEvent
        return SignalEvent(event_type=EventType.OPEN, symbol="XAUUSD", side=Side.BUY,
                           entry=2345.0, stop_loss=2335.0, take_profits=[2355.0],
                           raw_message=texto)


def test_con_la_ia_de_fondo_sale_un_solo_aviso(tmp_path):
    """"oro compren 2345 stop 2335": el parser lo entiende a medias y la IA
    como apertura. Salian dos avisos que se contradecian."""
    settings = build_settings(tmp_path, enable_ollama=True, ollama_auto_execute=False)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    from tct.brokers.paper import PaperBroker
    engine = Engine(settings, store, PaperBroker(), ollama=IAQueDiceApertura())
    avisos = AvisosDelLog()

    send(engine, "oro compren 2345 stop 2335", message_id=1)

    textos = " ".join(avisos.mensajes)
    assert "LA IA LOCAL" in textos.upper()
    assert "no se pudo aplicar sola" not in textos


def test_el_cupo_de_una_version_anterior_no_vuelve_a_cero(tmp_path, monkeypatch):
    """El estado de antes del 27/09 guardaba el dia en UTC."""
    import tct.store as modulo

    monkeypatch.setattr(modulo, "_hoy", lambda: "2026-09-27")
    settings = build_settings(tmp_path)
    settings.state_path.parent.mkdir(parents=True, exist_ok=True)
    hoy_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    settings.state_path.write_text(json.dumps({
        "signals_today": 5, "signals_day": hoy_utc}), encoding="utf-8")

    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)

    assert store.signals_today() == 5


def test_si_falla_el_registro_de_la_segunda_posicion_la_edicion_no_reabre(tmp_path):
    """paper_trades.jsonl bloqueado en Windows (un antivirus, un editor abierto)
    a mitad de una senal de dos posiciones: la primera ya entro."""
    engine, store, terminal = armar(tmp_path, positions_per_signal=2, max_open_trades=5,
                                    max_positions_per_symbol=0)
    original = store.append_paper_trade
    llamadas = {"n": 0}

    def falla_la_segunda(registro):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise PermissionError("archivo bloqueado")
        return original(registro)
    store.append_paper_trade = falla_la_segunda
    senal = "XAUUSD BUY\nEntry 4432\nSL 4424\nTP 4436\nTP 4440"

    send(engine, senal, message_id=1, date=hace(0))
    # Corrige el SL: la regla de "misma senal" no la frena, la marca de que
    # el mensaje ya opero si (y la toma como correccion del SL).
    edicion = send(engine, senal.replace("SL 4424", "SL 4423"), message_id=1,
                   is_edit=True, date=hace(1))

    assert edicion["status"] != "aceptada", "la edicion volvio a abrir"
    assert len(terminal.posiciones_abiertas()) == 1
