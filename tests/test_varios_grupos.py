"""Varios grupos de Telegram en un mismo bot (17/10).

La demo de FxPro pasa a copiar tres grupos a la vez: David (el mismo canal que
la real), Sebastian y XAUUSD TRADING ZONE, los tres en oro. Hasta hoy las
posiciones no sabian de que grupo venian, y eso rompia tres cosas:

- Un "cierren todo" o un "muevan el SL a BE" de un grupo tocaba las posiciones
  de los otros dos (la gestion buscaba solo por simbolo).
- Una respuesta al mensaje 1111 de un grupo podia caer en la posicion que abrio
  el mensaje 1111 de otro: los numeros de mensaje se repiten entre grupos.
- Habia un solo lote para todo el bot, y el pidio David a 0.03 y los otros dos
  a 0.04 (LOT_PER_CHAT).

Y lo que NO tiene que cambiar: con un solo grupo (la real), todo igual.
"""

from __future__ import annotations

import pytest

from tct.brokers.paper import PaperBroker
from tct.config import ConfigError, load_settings
from tct.engine import Engine
from tct.grupos import clave_de_grupo
from tct.signals.models import EventType
from tct.signals.parser import parse_signal
from tct.store import OpenPosition, State, Store
from tests.test_engine import build_settings, send

DAVID, SEBASTIAN, ZONA = -1004363872187, -1003831574671, -1001666520346
FUENTES = [str(DAVID), str(SEBASTIAN), str(ZONA)]

SENAL = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"
CERRAR_TODO = "Cierren todas las posiciones"


def armar(tmp_path, **cambios) -> Engine:
    settings = build_settings(tmp_path, telegram_source_chats=FUENTES,
                              max_positions_per_symbol=10, **cambios)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return Engine(settings, store, PaperBroker())


def de(engine, chat):
    return [p for p in engine.store.open_positions() if p.grupo == clave_de_grupo(chat)]


# --------------------------------------------------------------------------
# La clave del grupo
# --------------------------------------------------------------------------


@pytest.mark.parametrize("valor", [-1001666520346, "-1001666520346", " -1001666520346 ",
                                   1666520346, "1666520346"])
def test_las_formas_de_un_canal_son_la_misma_clave(valor):
    # En vivo Telethon da -100...; el historial del repaso, el id de la entidad;
    # el .env, lo que mostro `tct chats`.
    assert clave_de_grupo(valor) == "1666520346"


def test_un_canal_con_id_chico_y_un_grupo_comun():
    assert clave_de_grupo(-1000000001234) == "1234"
    assert clave_de_grupo(-12345) == "12345"
    assert clave_de_grupo("@Canal_X") == "@canal_x"
    assert clave_de_grupo(None) is None
    assert clave_de_grupo("  ") is None


# --------------------------------------------------------------------------
# Cada posicion recuerda su grupo
# --------------------------------------------------------------------------


def test_la_posicion_recuerda_de_que_grupo_vino(tmp_path):
    engine = armar(tmp_path)

    send(engine, SENAL, chat_id=SEBASTIAN, message_id=10)

    [posicion] = engine.store.open_positions()
    assert posicion.grupo == "3831574671"


def test_el_grupo_sobrevive_a_un_reinicio_y_un_estado_viejo_carga_sin_grupo(tmp_path):
    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=ZONA, message_id=10)

    otra = Store(engine.settings.events_path, engine.settings.paper_trades_path,
                 engine.settings.state_path)
    assert otra.open_positions()[0].grupo == "1666520346"

    vieja = engine.store.state.to_dict()
    for p in vieja["open_positions"]:
        del p["grupo"]
    assert State.from_dict(vieja).open_positions[0].grupo is None


# --------------------------------------------------------------------------
# La gestion de un grupo no toca a los otros
# --------------------------------------------------------------------------


def test_cerrar_todo_de_un_grupo_cierra_solo_las_suyas(tmp_path):
    evento = parse_signal(CERRAR_TODO)
    assert evento.event_type is EventType.CLOSE and evento.symbol is None

    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL.replace("2345", "2346"), chat_id=SEBASTIAN, message_id=20)
    send(engine, SENAL.replace("2345", "2347"), chat_id=ZONA, message_id=30)

    resultado = send(engine, CERRAR_TODO, chat_id=SEBASTIAN, message_id=21)

    assert resultado["status"] == "cerrada"
    assert de(engine, SEBASTIAN) == []
    assert len(de(engine, DAVID)) == 1 and len(de(engine, ZONA)) == 1


def test_cerrar_desde_un_grupo_sin_posiciones_no_toca_las_de_otro(tmp_path):
    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)

    resultado = send(engine, "Close XAUUSD now", chat_id=ZONA, message_id=11)

    assert resultado["status"] == "rechazada"
    assert any("No hay posiciones" in r for r in resultado["reasons"])
    assert len(de(engine, DAVID)) == 1


def test_el_breakeven_de_un_grupo_no_mueve_el_stop_de_otro(tmp_path):
    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=ZONA, message_id=30)

    resultado = send(engine, "TP1 hit, move SL to BE", chat_id=ZONA, message_id=31)

    assert resultado["status"] == "sl_movido"
    assert de(engine, ZONA)[0].stop_loss == 2345.0
    assert de(engine, DAVID)[0].stop_loss == 2335.0


def test_una_respuesta_con_el_mismo_numero_de_mensaje_no_cruza_de_grupo(tmp_path):
    # El mensaje 1111 existe en los dos grupos: cada uno numera los suyos.
    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=1111)
    send(engine, SENAL.replace("2345", "2346"), chat_id=SEBASTIAN, message_id=1111)

    send(engine, "Close XAUUSD now", chat_id=SEBASTIAN, message_id=1112,
         reply_to_message_id=1111)

    assert de(engine, SEBASTIAN) == []
    assert len(de(engine, DAVID)) == 1


def test_la_correccion_del_sl_por_edicion_queda_en_su_grupo(tmp_path):
    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=500)
    send(engine, SENAL, chat_id=SEBASTIAN, message_id=500)

    resultado = send(engine, SENAL.replace("SL 2335", "SL 2338"), chat_id=SEBASTIAN,
                     message_id=500, is_edit=True)

    assert resultado["status"] == "sl_corregido"
    assert de(engine, SEBASTIAN)[0].stop_loss == 2338.0
    assert de(engine, DAVID)[0].stop_loss == 2335.0


def test_una_posicion_de_antes_del_cambio_la_gestiona_cualquier_grupo(tmp_path):
    # Las posiciones guardadas antes del 17/10 no tienen grupo: se manejan como
    # siempre, para que no queden sin breakeven al actualizar.
    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    engine.store.open_positions()[0].grupo = None

    send(engine, "TP1 hit, move SL to BE", chat_id=ZONA, message_id=31)

    assert engine.store.open_positions()[0].stop_loss == 2345.0


# --------------------------------------------------------------------------
# Los topes que miran otras posiciones, dentro del grupo
# --------------------------------------------------------------------------


def test_el_tope_por_simbolo_se_cuenta_por_grupo(tmp_path):
    engine = armar(tmp_path)
    engine = Engine(build_settings(tmp_path, telegram_source_chats=FUENTES,
                                   max_positions_per_symbol=1),
                    engine.store, PaperBroker())
    assert send(engine, SENAL, chat_id=DAVID, message_id=10)["status"] == "aceptada"

    otro = send(engine, SENAL.replace("2345", "2346"), chat_id=ZONA, message_id=30)
    mismo = send(engine, SENAL.replace("2345", "2347"), chat_id=DAVID, message_id=11)

    assert otro["status"] == "aceptada"
    assert mismo["status"] == "rechazada"
    assert any("MAX_POSITIONS_PER_SYMBOL" in r for r in mismo["reasons"])


def test_la_misma_senal_en_dos_grupos_se_abre_en_los_dos(tmp_path):
    engine = armar(tmp_path)

    a = send(engine, SENAL, chat_id=DAVID, message_id=10)
    b = send(engine, SENAL, chat_id=ZONA, message_id=10)
    repetida = send(engine, SENAL, chat_id=ZONA, message_id=11)

    assert a["status"] == "aceptada" and b["status"] == "aceptada"
    assert repetida["status"] == "rechazada"
    assert any("misma senal" in r for r in repetida["reasons"])


def test_el_tope_de_abiertas_sigue_siendo_de_todo_el_bot(tmp_path):
    engine = armar(tmp_path, max_open_trades=2)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=SEBASTIAN, message_id=20)

    tercera = send(engine, SENAL, chat_id=ZONA, message_id=30)

    assert tercera["status"] == "rechazada"
    assert any("MAX_OPEN_TRADES" in r for r in tercera["reasons"])


# --------------------------------------------------------------------------
# Un lote por grupo
# --------------------------------------------------------------------------


def test_cada_grupo_abre_con_su_lote(tmp_path):
    engine = armar(tmp_path, default_lot=0.04,
                   lot_per_chat={"4363872187": 0.03})

    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=SEBASTIAN, message_id=20)

    assert de(engine, DAVID)[0].lot == 0.03
    assert de(engine, SEBASTIAN)[0].lot == 0.04
    lotes = {t["lot"] for t in engine.store.read_paper_trades()}
    assert lotes == {0.03, 0.04}


def escribir_env(tmp_path, **valores) -> str:
    base = {"TRADING_MODE": "PAPER_ONLY", "DEFAULT_LOT": "0.04", "MAX_LOT": "0.05",
            "TELEGRAM_SOURCE_CHATS": ",".join(FUENTES),
            "DATA_DIR": str(tmp_path / "data")}
    base.update(valores)
    ruta = tmp_path / ".env.prueba"
    ruta.write_text("".join(f"{k}={v}\n" for k, v in base.items()), encoding="utf-8")
    return str(ruta)


def test_lot_per_chat_se_lee_del_env(tmp_path, monkeypatch):
    for clave in ("LOT_PER_CHAT", "DEFAULT_LOT", "MAX_LOT", "TELEGRAM_SOURCE_CHATS"):
        monkeypatch.delenv(clave, raising=False)
    ruta = escribir_env(tmp_path, LOT_PER_CHAT=f"{DAVID}:0.03, {ZONA}:0.05")

    settings = load_settings(ruta)

    assert settings.lot_per_chat == {"4363872187": 0.03, "1666520346": 0.05}
    assert settings.lote_para(DAVID) == 0.03
    assert settings.lote_para(1666520346) == 0.05      # el id del historial
    assert settings.lote_para(SEBASTIAN) == 0.04       # sin lote propio: DEFAULT_LOT
    assert settings.lote_para(None) == 0.04
    assert "lote de -1004363872187: 0.03" in settings.describe()
    assert "lote de -1003831574671: 0.04 (DEFAULT_LOT)" in settings.describe()


def test_sin_lot_per_chat_todo_igual(tmp_path, monkeypatch):
    monkeypatch.delenv("LOT_PER_CHAT", raising=False)
    settings = load_settings(escribir_env(tmp_path))

    assert settings.lot_per_chat == {}
    assert settings.lote_para(DAVID) == settings.default_lot
    assert "lote de" not in settings.describe()


@pytest.mark.parametrize("valor, dice", [
    ("-1009999999999:0.03", "no esta en TELEGRAM_SOURCE_CHATS"),
    ("@canal:0.03", "NUMERO del grupo"),
    (f"{DAVID}:0.10", "no puede superar MAX_LOT"),
    (f"{DAVID}:0", "mayor que cero"),
    (f"{DAVID}:nan", "mayor que cero"),
    (f"{DAVID}:mucho", "tiene que ser un numero"),
    (f"{DAVID}", "<numero del grupo>:<lote>"),
    (f"{DAVID}:0.03,{DAVID}:0.04", "aparece dos veces"),
])
def test_lot_per_chat_raro_no_deja_arrancar(tmp_path, monkeypatch, valor, dice):
    monkeypatch.delenv("LOT_PER_CHAT", raising=False)
    with pytest.raises(ConfigError, match=dice.replace("<", r"\<").replace(">", r"\>")):
        load_settings(escribir_env(tmp_path, LOT_PER_CHAT=valor))


# --------------------------------------------------------------------------
# Lo que no cambia
# --------------------------------------------------------------------------


def test_un_mensaje_sin_chat_gestiona_todo_como_antes(tmp_path):
    # `tct simular` y los tests mandan mensajes sin chat: ahi no hay grupo.
    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=ZONA, message_id=30)

    send(engine, "TP1 hit, move SL to BE", chat_id=None, message_id=40)

    assert all(p.stop_loss == 2345.0 for p in engine.store.open_positions())


def test_con_un_solo_grupo_la_gestion_es_la_de_siempre(tmp_path):
    settings = build_settings(tmp_path, telegram_source_chats=[str(DAVID)],
                              max_positions_per_symbol=10)
    engine = Engine(settings, Store(settings.events_path, settings.paper_trades_path,
                                    settings.state_path), PaperBroker())
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL.replace("2345", "2346"), chat_id=DAVID, message_id=11)

    resultado = send(engine, CERRAR_TODO, chat_id=DAVID, message_id=12)

    assert resultado["status"] == "cerrada"
    assert engine.store.open_positions() == []


def test_find_positions_sin_grupo_devuelve_todas():
    store = Store.__new__(Store)
    store.state = State(open_positions=[
        OpenPosition("a", "XAUUSD", "BUY", 0.01, 1.0, None, [], "t", grupo="1"),
        OpenPosition("b", "XAUUSD", "BUY", 0.01, 1.0, None, [], "t", grupo="2"),
        OpenPosition("c", "XAUUSD", "BUY", 0.01, 1.0, None, [], "t"),
    ])

    assert [p.trade_id for p in store.find_positions("XAUUSD")] == ["a", "b", "c"]
    assert [p.trade_id for p in store.find_positions(grupo="1")] == ["a", "c"]


# --------------------------------------------------------------------------
# El informe dice cuanto lleva cada grupo
# --------------------------------------------------------------------------


def test_el_informe_separa_el_resultado_por_grupo(tmp_path, capsys):
    from tct import cli
    from tct.informe import resumir_por_grupo, tickets_operados

    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL, chat_id=ZONA, message_id=30)
    operadas = tickets_operados(engine.store.read_events())
    assert {o["grupo"] for o in operadas} == {"4363872187", "1666520346"}

    filas = [
        {**operadas[0], "resultado": "TP1", "profit": 12.0, "neto": 12.0},
        {**operadas[1], "resultado": "stop loss", "profit": -40.0, "neto": -40.0},
    ]
    [(mejor, r1), (peor, r2)] = resumir_por_grupo(filas)
    assert (mejor, r1["neto_total"]) == ("4363872187", 12.0)
    assert (peor, r2["neto_total"]) == ("1666520346", -40.0)

    cli._resultado_por_grupo(engine.settings, filas)
    salida = capsys.readouterr().out
    assert "POR GRUPO" in salida
    assert salida.index(str(DAVID)) < salida.index(str(ZONA))


def test_con_un_solo_grupo_el_informe_no_agrega_nada(tmp_path, capsys):
    from tct import cli
    from tct.informe import tickets_operados

    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    filas = [{**o, "resultado": "TP1", "profit": 1.0, "neto": 1.0}
             for o in tickets_operados(engine.store.read_events())]

    cli._resultado_por_grupo(engine.settings, filas)

    assert capsys.readouterr().out == ""


def test_al_arrancar_las_posiciones_de_antes_recuperan_su_grupo(tmp_path):
    # Al actualizar, las posiciones abiertas no tienen grupo y las tocaria
    # cualquier grupo. El evento "aceptada" dice de que chat vinieron.
    import asyncio

    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    send(engine, SENAL.replace("2345", "2346"), chat_id=ZONA, message_id=30)
    for posicion in engine.store.open_positions():
        posicion.grupo = None
    engine.store.save_state()

    reiniciado = Engine(engine.settings, Store(engine.settings.events_path,
                                               engine.settings.paper_trades_path,
                                               engine.settings.state_path), PaperBroker())
    asyncio.run(reiniciado.reconciliar_al_arrancar())

    assert {p.grupo for p in reiniciado.store.open_positions()} == {"4363872187", "1666520346"}
    send(reiniciado, CERRAR_TODO, chat_id=SEBASTIAN, message_id=21)
    assert len(reiniciado.store.open_positions()) == 2


def test_una_posicion_sin_evento_queda_sin_grupo(tmp_path):
    import asyncio

    engine = armar(tmp_path)
    send(engine, SENAL, chat_id=DAVID, message_id=10)
    posicion = engine.store.open_positions()[0]
    posicion.grupo, posicion.signal_message_id = None, 999   # no coincide con el evento

    asyncio.run(engine.reconciliar_al_arrancar())

    assert engine.store.open_positions()[0].grupo is None
