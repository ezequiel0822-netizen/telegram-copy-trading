"""Mover el take profit: solo el del TP1, y que quede registrado.

EL PEDIDO
---------
Si el canal manda "mover TP a X": se mueve el TP de la posicion que persigue
el TP1, y las del TP2 y el TP3 se quedan donde estaban. Y todo queda
registrado -cual se movio y cual no, y por que- para revisarlo en el informe.

Con FxPro en POSITIONS_PER_SIGNAL=1 hay una sola posicion por senal y es la
del TP1. Con MetaQuotes en 3, se mueve una de las tres.

LO QUE MAS IMPORTA DE ESTOS TESTS
---------------------------------
Que un RELATO no mueva nada. Medido contra el parser: "TP1 4450" a secas y
"nuestro TP1 era 4436" tambien traen un TP con precio. Si cualquier TP con
precio moviera posiciones, una cronica del canal te llevaria el objetivo a un
precio viejo. Por eso hace falta un verbo explicito.

Y de paso quedo cubierto un bug que se encontro al hacer esto:
`tickets_operados` leia solo la PRIMERA orden de cada senal, asi que con tres
posiciones el informe con resultados perdia la del TP2 y la del TP3.
"""

from __future__ import annotations

import json

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.informe import clasificar_desenlace, resumir, tickets_operados
from tct.signals.models import EventType
from tct.signals.parser import parse_signal, pide_mover_tp
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings, send

ORO = 4438.0
SENAL = "XAUUSD BUY\nEntry 4438\nSL 4420\nTP1 4442\nTP2 4444\nTP3 4446"


def armar(tmp_path, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5}})
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), fake))
    return store, engine, fake, settings


def eventos(settings, kind=None):
    filas = [
        json.loads(linea)
        for linea in settings.events_path.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]
    return [f for f in filas if kind is None or f.get("kind") == kind]


def tp_en_el_broker(fake):
    return sorted(p.tp for p in fake.posiciones_abiertas())


# --------------------------------------------------------------------------
# El parser: solo un pedido explicito
# --------------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    "MOVER TP A 4450",
    "MOVER TP1 A 4450",
    "Mover TP 1 a 4450",
    "Movemos el TP a 4450",
    "Cambiar TP a 4450",
    "Move TP to 4450",
])
def test_un_pedido_explicito_es_mover_tp(texto):
    ev = parse_signal(texto)

    assert ev is not None and ev.event_type is EventType.MOVE_TP
    assert ev.take_profits == [4450.0]


@pytest.mark.parametrize("texto", [
    "TP1 4450",                           # sin verbo
    "nuestro TP1 era 4436",               # relato
    "el precio sube hasta el TP 4450",    # describe al precio
    "Update: TP1 4436 hit",               # resultado
    "Movimos el TP a 4450",               # pasado: cronica
])
def test_sin_pedido_explicito_no_es_mover_tp(texto):
    ev = parse_signal(texto)

    assert ev is None or ev.event_type is not EventType.MOVE_TP


def test_mover_el_stop_no_se_confunde_con_mover_el_tp():
    """"TP se mantiene en 4440" dice que el TP se QUEDA."""
    texto = "Mover SL a 4432, TP se mantiene en 4440"

    assert parse_signal(texto).event_type is EventType.MOVE_SL
    assert pide_mover_tp(texto) is False


# --------------------------------------------------------------------------
# El motor: solo la posicion del TP1
# --------------------------------------------------------------------------

def test_con_tres_posiciones_solo_se_mueve_la_del_tp1(tmp_path):
    """La cuenta de MetaQuotes."""
    _, engine, fake, _ = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER TP A 4450", message_id=2)

    assert tp_en_el_broker(fake) == [4444.0, 4446.0, 4450.0]


def test_con_una_sola_posicion_se_mueve(tmp_path):
    """La cuenta de FxPro: POSITIONS_PER_SIGNAL=1."""
    _, engine, fake, _ = armar(tmp_path, positions_per_signal=1)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER TP A 4450", message_id=2)

    assert tp_en_el_broker(fake) == [4450.0]


def test_el_estado_sabe_que_tp_persigue_cada_una(tmp_path):
    store, engine, _, _ = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER TP A 4450", message_id=2)

    por_indice = {p.tp_indice: p.tp_objetivo for p in store.open_positions()}
    assert por_indice == {1: 4450.0, 2: 4444.0, 3: 4446.0}


def test_mover_el_tp_no_toca_el_stop(tmp_path):
    """MT5 manda stop y TP en el mismo pedido: un 0 en el stop lo borraria."""
    _, engine, fake, _ = armar(tmp_path, positions_per_signal=1)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER TP A 4450", message_id=2)

    assert [p.sl for p in fake.posiciones_abiertas()] == [4420.0]


def test_un_relato_no_mueve_ningun_tp(tmp_path):
    """El test que justifica el diseno entero."""
    _, engine, fake, _ = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)

    send(engine, "nuestro TP1 era 4436", message_id=2)
    send(engine, "TP1 4450", message_id=3)

    assert tp_en_el_broker(fake) == [4442.0, 4444.0, 4446.0]


def test_un_tp_del_lado_equivocado_no_se_manda(tmp_path):
    """En un BUY el TP va arriba del precio. 4430 con el oro en 4438 cerraria
    la operacion al instante, o MT5 lo rechazaria."""
    _, engine, fake, settings = armar(tmp_path, positions_per_signal=1)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER TP A 4430", message_id=2)

    assert tp_en_el_broker(fake) == [4442.0]
    registro = eventos(settings, "mover_tp")[-1]
    assert "lado equivocado" in registro["no_movidas"][0]["motivo"]


def test_una_posicion_vieja_sin_el_dato_no_se_toca(tmp_path):
    """Abierta antes de esta version: no se sabe que TP perseguia, y adivinar
    podria mover la del TP3."""
    store, engine, fake, settings = armar(tmp_path, positions_per_signal=1)
    send(engine, SENAL, message_id=1)
    for p in store.open_positions():
        p.tp_indice = None

    send(engine, "MOVER TP A 4450", message_id=2)

    assert tp_en_el_broker(fake) == [4442.0]
    registro = eventos(settings, "mover_tp")[-1]
    assert "no se sabe" in registro["no_movidas"][0]["motivo"]


def test_el_tp_nuevo_sobrevive_a_un_reinicio(tmp_path):
    _, engine, _, settings = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)
    send(engine, "MOVER TP A 4450", message_id=2)

    otro = Store(settings.events_path, settings.paper_trades_path, settings.state_path)

    por_indice = {p.tp_indice: p.tp_objetivo for p in otro.open_positions()}
    assert por_indice[1] == 4450.0


# --------------------------------------------------------------------------
# El registro: cual se movio y cual no
# --------------------------------------------------------------------------

def test_queda_registrado_cual_se_movio_y_cual_no(tmp_path):
    _, engine, _, settings = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER TP A 4450", message_id=2)

    registro = eventos(settings, "mover_tp")[-1]
    assert len(registro["movidas"]) == 1
    movida = registro["movidas"][0]
    assert (movida["tp_indice"], movida["tp_anterior"], movida["tp_nuevo"]) == (1, 4442.0, 4450.0)
    motivos = [n["motivo"] for n in registro["no_movidas"]]
    assert any("TP2" in m for m in motivos)
    assert any("TP3" in m for m in motivos)


def test_el_informe_ve_las_tres_posiciones_de_una_senal(tmp_path):
    """El bug de paso: antes solo aparecia la primera."""
    _, engine, _, settings = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)

    operadas = tickets_operados(eventos(settings))

    assert sorted(o["tp_indice"] for o in operadas) == [1, 2, 3]
    assert len({o["ticket"] for o in operadas}) == 3


def test_un_evento_de_estos_dias_con_orders_se_lee_entero():
    """Las senales operadas antes de este cambio tienen `orders` y no
    `aperturas`. Son los datos de los primeros dias con tres TP."""
    evento = {
        "kind": "aceptada", "ts": "2026-09-14T12:13:00+00:00",
        "order": {"ticket": 1},
        "orders": [{"ticket": 1}, {"ticket": 2}, {"ticket": 3}],
        "signal": {"symbol": "XAUUSD", "side": "BUY", "entry": 4295.0,
                   "take_profits": [4299.0, 4301.0, 4303.0]},
    }

    operadas = tickets_operados([evento])

    assert [(o["ticket"], o["tp_indice"]) for o in operadas] == [(1, 1), (2, 2), (3, 3)]


def test_el_informe_marca_el_tp_movido(tmp_path):
    _, engine, _, settings = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)
    send(engine, "MOVER TP A 4450", message_id=2)

    operadas = tickets_operados(eventos(settings))

    assert {o["tp_indice"]: o["tp_movido_a"] for o in operadas} == {1: 4450.0, 2: None, 3: None}


def test_el_resumen_cuenta_movidos_y_no_movidos(tmp_path):
    _, engine, _, settings = armar(tmp_path, positions_per_signal=3)
    send(engine, SENAL, message_id=1)
    send(engine, "MOVER TP A 4450", message_id=2)

    r = resumir(eventos(settings))

    assert r["tp_movidos"] == 1
    assert sum(veces for _, veces in r["tp_no_movidos"]) == 2


def test_un_cierre_en_el_tp_movido_se_dice_asi():
    operada = {"entry": 4438.0, "take_profits": [4442.0, 4444.0, 4446.0],
               "tp_indice": 1, "tp_movido_a": 4450.0}

    assert clasificar_desenlace(operada, {"motivo": "tp", "precio": 4450.0}) == "TP1 movido"
