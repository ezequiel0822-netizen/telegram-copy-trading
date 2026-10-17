"""Lo que encontro la revision del cambio de varios grupos (17/10).

Cuatro revisores atacaron el cambio antes de subirlo. Lo que encontraron:

- Un bot de UN grupo al que se le cambia el canal con posiciones abiertas: las
  posiciones del canal viejo quedaban sin nadie que las gestione, y una senal
  igual del canal nuevo se abria dos veces. Antes del cambio las gestionaba el
  canal nuevo; tiene que seguir siendo asi.
- Una orden que MetaTrader confirma tarde no se marcaba como "ya opero": si el
  canal editaba la senal para corregir el SL, se abria una SEGUNDA posicion.
  Pasaba desde antes de este cambio.
- Con varios grupos: la posicion adoptada al arrancar no recuperaba su grupo, la
  orden confirmada tarde podia quedarse con el ticket de OTRO grupo, y una
  respuesta podia caer en una posicion sin grupo de otro chat con el mismo
  numero de mensaje.
"""

from __future__ import annotations

import asyncio

import pytest

from tct import archivo_env, cli
from tct.brokers.mt5_native import MAGIA, MT5NativeBroker
from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_auditoria_ejecucion import SENAL as SENAL_MT5
from tests.test_auditoria_ejecucion import Terminal
from tests.test_engine import build_settings, send

DAVID, SEBASTIAN, ZONA = -1004363872187, -1003831574671, -1001666520346
FUENTES = [str(DAVID), str(SEBASTIAN), str(ZONA)]
SENAL = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"
CERRAR_TODO = "Cierren todas las posiciones"


@pytest.fixture(autouse=True)
def _sin_variables_de_la_maquina(monkeypatch):
    # Las variables de entorno pisan al .env: un MAX_LOT en la consola de quien
    # corre los tests cambiaria lo que se prueba (igual que en test_cambiar_env).
    for nombre in archivo_env.VARIABLES_DEL_ENV:
        monkeypatch.delenv(nombre, raising=False)


def con_paper(tmp_path, fuentes, **cambios) -> Engine:
    settings = build_settings(tmp_path, telegram_source_chats=fuentes,
                              max_positions_per_symbol=10, **cambios)
    return Engine(settings, Store(settings.events_path, settings.paper_trades_path,
                                  settings.state_path), PaperBroker())


def reiniciar(engine: Engine, fuentes, broker=None) -> Engine:
    import dataclasses

    settings = dataclasses.replace(engine.settings, telegram_source_chats=fuentes)
    nuevo = Engine(settings, Store(settings.events_path, settings.paper_trades_path,
                                   settings.state_path), broker or PaperBroker())
    asyncio.run(nuevo.reconciliar_al_arrancar())
    return nuevo


def con_terminal(tmp_path, fuentes, **cambios):
    cambios.setdefault("max_spread_from_entry_pct", 0.05)
    settings = build_settings(tmp_path, telegram_source_chats=fuentes,
                              max_positions_per_symbol=10, max_open_trades=10, **cambios)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    terminal = Terminal()
    return Engine(settings, store, enchufar(MT5NativeBroker(settings), terminal)), terminal


def entra_tarde(terminal: Terminal, volumen: float, sl: float = 4424.0) -> None:
    """La orden que MetaTrader no confirmo aparece en la cuenta."""
    FakeMT5.order_send(terminal, {
        "action": terminal.TRADE_ACTION_DEAL, "symbol": "XAUUSD", "volume": volumen,
        "type": terminal.ORDER_TYPE_BUY, "price": 4432.5, "magic": MAGIA,
        "sl": sl, "tp": 4436.0,
    })


# --------------------------------------------------------------------------
# Un solo grupo: el cambio de canal se comporta como antes
# --------------------------------------------------------------------------


def test_cambiar_el_canal_con_posiciones_abiertas_las_deja_al_canal_nuevo(tmp_path):
    engine = con_paper(tmp_path, [str(DAVID)])
    send(engine, SENAL, chat_id=DAVID, message_id=10)

    nuevo = reiniciar(engine, [str(ZONA)])

    assert nuevo.store.open_positions()[0].grupo is None
    repetida = send(nuevo, SENAL, chat_id=ZONA, message_id=10)
    assert repetida["status"] == "rechazada", "la misma senal se abria dos veces"
    send(nuevo, CERRAR_TODO, chat_id=ZONA, message_id=11)
    assert nuevo.store.open_positions() == [], "quedaba sin nadie que la gestione"


def test_sacar_un_grupo_del_env_deja_sus_posiciones_a_los_demas(tmp_path):
    engine = con_paper(tmp_path, FUENTES)
    send(engine, SENAL, chat_id=SEBASTIAN, message_id=10)

    nuevo = reiniciar(engine, [str(DAVID), str(ZONA)])

    assert nuevo.store.open_positions()[0].grupo is None


# --------------------------------------------------------------------------
# La orden que MetaTrader confirma tarde
# --------------------------------------------------------------------------


def test_la_edicion_de_una_senal_confirmada_tarde_corrige_y_no_abre_otra(tmp_path):
    engine, terminal = con_terminal(tmp_path, ["-100"])
    terminal.sin_ejecutar = True
    assert send(engine, SENAL_MT5, message_id=400)["status"] == "apertura_fallida"

    terminal.sin_ejecutar = False
    entra_tarde(terminal, 0.01)
    asyncio.run(engine.revisar_el_broker())
    assert len(engine.store.open_positions()) == 1
    assert engine.store.signals_today() == 1, "una senal que entro cuenta en el cupo"

    resultado = send(engine, SENAL_MT5.replace("SL 4424", "SL 4426"), message_id=400,
                     is_edit=True)

    assert resultado["status"] == "sl_corregido", resultado
    assert len(terminal.posiciones_abiertas()) == 1, "la edicion abrio una segunda"


def test_con_varios_grupos_la_confirmada_tarde_es_la_de_su_lote(tmp_path):
    # David a 0.03 y TRADING ZONE a 0.04, las dos sin confirmar; entra solo la
    # de TRADING ZONE. David se fija primero y no se la tiene que quedar.
    engine, terminal = con_terminal(tmp_path, FUENTES, default_lot=0.04,
                                    lot_per_chat={"4363872187": 0.03})
    terminal.sin_ejecutar = True
    send(engine, SENAL_MT5, chat_id=DAVID, message_id=1)
    send(engine, SENAL_MT5, chat_id=ZONA, message_id=2)

    terminal.sin_ejecutar = False
    entra_tarde(terminal, 0.04)
    asyncio.run(engine.revisar_el_broker())

    [posicion] = engine.store.open_positions()
    assert (posicion.grupo, posicion.signal_message_id) == ("1666520346", 2)


def test_con_dos_grupos_del_mismo_lote_no_se_adivina_de_cual_es(tmp_path):
    engine, terminal = con_terminal(tmp_path, FUENTES, default_lot=0.04)
    terminal.sin_ejecutar = True
    send(engine, SENAL_MT5, chat_id=SEBASTIAN, message_id=1)
    send(engine, SENAL_MT5, chat_id=ZONA, message_id=2)

    terminal.sin_ejecutar = False
    entra_tarde(terminal, 0.04)
    asyncio.run(engine.revisar_el_broker())

    [posicion] = engine.store.open_positions()
    assert posicion.grupo is None


# --------------------------------------------------------------------------
# Varios grupos: la adoptada al arrancar y las respuestas
# --------------------------------------------------------------------------


def test_la_adoptada_al_arrancar_recupera_su_grupo_del_registro(tmp_path):
    engine, terminal = con_terminal(tmp_path, FUENTES)
    assert send(engine, SENAL_MT5, chat_id=DAVID, message_id=10)["status"] == "aceptada"
    engine.settings.state_path.unlink()          # se perdio el estado

    broker = enchufar(MT5NativeBroker(engine.settings), terminal)
    nuevo = reiniciar(engine, FUENTES, broker=broker)

    [adoptada] = nuevo.store.open_positions()
    assert (adoptada.grupo, adoptada.signal_message_id) == ("4363872187", 10)
    send(nuevo, CERRAR_TODO, chat_id=SEBASTIAN, message_id=21)
    assert len(terminal.posiciones_abiertas()) == 1, "el cierren todo de otro grupo la cerro"


def test_con_un_solo_grupo_la_adoptada_queda_como_antes(tmp_path):
    engine, terminal = con_terminal(tmp_path, ["-100"])
    send(engine, SENAL_MT5, message_id=10)
    engine.settings.state_path.unlink()

    nuevo = reiniciar(engine, ["-100"], broker=enchufar(MT5NativeBroker(engine.settings),
                                                         terminal))

    [adoptada] = nuevo.store.open_positions()
    assert (adoptada.grupo, adoptada.signal_message_id) == (None, None)


def test_la_respuesta_no_cae_en_una_posicion_sin_grupo_de_otro_chat(tmp_path):
    engine = con_paper(tmp_path, FUENTES)
    send(engine, SENAL, chat_id=DAVID, message_id=1111)
    engine.store.open_positions()[0].grupo = None   # de antes, sin evento
    send(engine, SENAL.replace("2345", "2346"), chat_id=SEBASTIAN, message_id=1111)

    send(engine, "Close XAUUSD now", chat_id=SEBASTIAN, message_id=1112,
         reply_to_message_id=1111)

    [queda] = engine.store.open_positions()
    assert queda.entry == 2345.0, "cerro la de David en vez de la de Sebastian"


def test_con_varios_grupos_se_avisa_de_las_posiciones_sin_grupo(tmp_path):
    engine = con_paper(tmp_path, FUENTES)
    avisos = []

    async def anotar(texto, **_k):
        avisos.append(texto)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    engine.store.open_positions()[0].signal_message_id = None   # sin forma de saber
    engine.store.open_positions()[0].grupo = None
    engine._avisar = anotar

    asyncio.run(engine.reconciliar_al_arrancar())

    assert any("no se sabe de que grupo" in a for a in avisos)


# --------------------------------------------------------------------------
# Gestion que antes solo se probaba de rebote
# --------------------------------------------------------------------------


def test_mover_tp_de_un_grupo_no_queda_ambiguo_por_el_tp1_de_otro(tmp_path):
    engine = con_paper(tmp_path, FUENTES)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=ZONA, message_id=30)

    resultado = send(engine, "MOVER TP A 2360", chat_id=ZONA, message_id=31)

    assert resultado["status"] == "tp_movido", resultado
    tps = {p.grupo: p.tp_objetivo for p in engine.store.open_positions()}
    assert tps == {"1666520346": 2360.0, "4363872187": 2355.0}


def test_el_cierre_parcial_queda_en_su_grupo(tmp_path):
    engine = con_paper(tmp_path, FUENTES)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=ZONA, message_id=30)

    send(engine, "Close 50% XAUUSD", chat_id=ZONA, message_id=31)

    restantes = {p.grupo: p.remaining_fraction for p in engine.store.open_positions()}
    assert restantes == {"1666520346": 0.5, "4363872187": 1.0}


def test_la_posicion_nombrada_es_la_de_su_grupo(tmp_path):
    engine = con_paper(tmp_path, FUENTES)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=ZONA, message_id=30)

    send(engine, 'PARA LA POSICIÓN "BUY 2345", MOVA SU SL A SER EL SL RESULTANTE ES 2345 BE',
         chat_id=ZONA, message_id=31)

    stops = {p.grupo: p.stop_loss for p in engine.store.open_positions()}
    assert stops == {"1666520346": 2345.0, "4363872187": 2335.0}


# --------------------------------------------------------------------------
# El repaso y el informe
# --------------------------------------------------------------------------


def test_el_repaso_mide_todo_a_default_lot(tmp_path):
    settings = build_settings(tmp_path, telegram_source_chats=FUENTES, default_lot=0.04,
                              lot_per_chat={"4363872187": 0.03})

    ajustes = cli._ajustes_del_repaso(settings, tmp_path / "repaso")

    assert ajustes.lot_per_chat == {}
    assert ajustes.lote_para(DAVID) == 0.04
    assert ajustes.state_path == tmp_path / "repaso" / "state.json"


def test_el_informe_con_resultados_muestra_cada_grupo(tmp_path, monkeypatch, capsys):
    from tct.brokers import base

    engine = con_paper(tmp_path, FUENTES)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=ZONA, message_id=30)

    class Historial:
        async def connect(self):
            return True

        async def disconnect(self):
            pass

        async def desenlace_de(self, ticket):
            return {"precio": 2355.0, "profit": 10.0, "neto": 10.0, "tipo": "tp"}

    monkeypatch.setattr(base, "build_broker", lambda _s: Historial())
    asyncio.run(cli._informar_desenlaces(engine.settings, engine.store.read_events()))

    salida = capsys.readouterr().out
    assert "POR GRUPO" in salida
    assert str(DAVID) in salida and str(ZONA) in salida
