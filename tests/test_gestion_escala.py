"""El contraste con el precio real, aplicado a los eventos de GESTION.

Hasta ahora solo se validaban las aperturas. Un "MOVER SL A 4444" no se
comparaba contra nada: si el parser leia mal el numero, el stop se movia igual.

Y MT5 no alcanza como red. Rechaza los stops del lado equivocado del mercado,
que es la mitad de los desastres; pero un stop del lado correcto y
absurdamente lejos lo ACEPTA sin chistar, y ahi la posicion queda sin
proteccion real sin que nadie se entere.

El chequeo es de ESCALA, no de cercania, y esa distincion es el punto. Un stop
se pone lejos del mercado por definicion: medirlo con la tolerancia de una
entrada rechazaria stops sanos todos los dias. Lo que ningun stop legitimo
hace es valer el doble o la mitad que el instrumento que protege.
"""

from __future__ import annotations

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.risk import FACTOR_ESCALA_STOP, stop_fuera_de_escala
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings, send

ORO = 4438.0
SENAL_ORO = "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4460"
SENAL_EUR = "EURUSD BUY\nEntry 1.0855\nSL 1.0820\nTP 1.0900"


class Aviso:
    def __init__(self):
        self.mensajes = []

    def enabled(self):
        return True

    async def send(self, texto):
        self.mensajes.append(texto)


def armar(tmp_path, simbolos=None, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5(simbolos or {"XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5}})
    aviso = Aviso()
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), fake), aviso)
    return store, engine, fake, aviso


# --------------------------------------------------------------------------
# La regla, sola
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stop, mercado, deberia_rechazar", [
    (4420.0, 4438.0, False),   # un stop normal de oro
    (4200.0, 4438.0, False),   # un stop ancho, 5.4% abajo: legitimo
    (4900.0, 4438.0, False),   # del lado equivocado, pero de ESTE instrumento
    (444.0, 4438.0, True),     # un digito comido
    (44380.0, 4438.0, True),   # un digito de mas
    (4430.0, 1.0855, True),    # el numero del oro aplicado a EURUSD
    (1.08, 4438.0, True),      # al reves
    (0.0, 4438.0, True),       # invalido
    (4420.0, None, False),     # sin precio no se opina
])
def test_la_regla_de_escala(stop, mercado, deberia_rechazar):
    motivo = stop_fuera_de_escala(stop, mercado)
    assert (motivo is not None) is deberia_rechazar, motivo


def test_es_un_chequeo_de_escala_y_no_de_cercania(tmp_path):
    """El limite es un factor enorme a proposito. Si alguien lo confunde con la
    tolerancia de una entrada (0.5%) y lo ajusta, rechaza stops sanos."""
    assert FACTOR_ESCALA_STOP >= 2.0, (
        "el factor se aprieto tanto que ya rechaza stops legitimos"
    )
    assert stop_fuera_de_escala(ORO * 0.9, ORO) is None, "un stop 10% abajo es normal"


# --------------------------------------------------------------------------
# El caso que motiva todo: un MOVE_SL sin simbolo va a TODAS las posiciones
# --------------------------------------------------------------------------


def test_un_move_sl_sin_simbolo_no_aplica_el_numero_del_oro_a_eurusd(tmp_path):
    """Es el caso concreto que quedaba abierto en el documento. El canal manda
    "MOVER SL A 4430" pensando en el oro; sin simbolo, el bot lo aplica a todo
    lo abierto. Para EURUSD, que cotiza 1.08, ese stop no significa nada."""
    store, engine, fake, aviso = armar(tmp_path, {
        "XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5},
        "EURUSD": {"bid": 1.0850, "ask": 1.0860},
    })
    send(engine, SENAL_ORO, message_id=1)
    send(engine, SENAL_EUR, message_id=2)

    resultado = send(engine, "Move SL to 4430", message_id=3)

    porsimbolo = {p.symbol: p for p in store.open_positions()}
    assert porsimbolo["XAUUSD"].stop_loss == 4430.0, "el oro si tenia que moverse"
    assert porsimbolo["EURUSD"].stop_loss == 1.0820, (
        "a EURUSD le pusieron un stop de 4430 con el par en 1.08"
    )
    assert resultado["status"] == "sl_movido_parcial"
    assert any("EURUSD" in d for d in resultado["descartadas"])


def test_se_avisa_cual_quedo_sin_tocar(tmp_path):
    """Mover algunas y callarse las otras seria peor que no mover ninguna: la
    persona creeria que quedaron todas protegidas."""
    _, engine, _, aviso = armar(tmp_path, {
        "XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5},
        "EURUSD": {"bid": 1.0850, "ask": 1.0860},
    })
    send(engine, SENAL_ORO, message_id=1)
    send(engine, SENAL_EUR, message_id=2)

    send(engine, "Move SL to 4430", message_id=3)

    ultimo = aviso.mensajes[-1]
    assert "NO se pudo mover" in ultimo
    assert "EURUSD" in ultimo
    assert "siguen con el stop anterior" in ultimo


def test_no_se_le_manda_nada_al_broker_por_la_posicion_descartada(tmp_path):
    """El descarte tiene que pasar ANTES de la orden, no despues."""
    _, engine, fake, _ = armar(tmp_path, {
        "XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5},
        "EURUSD": {"bid": 1.0850, "ask": 1.0860},
    })
    send(engine, SENAL_ORO, message_id=1)
    send(engine, SENAL_EUR, message_id=2)

    send(engine, "Move SL to 4430", message_id=3)

    sltp = [r for r in fake.enviados if r.get("action") == FakeMT5.TRADE_ACTION_SLTP]
    assert len(sltp) == 1, "se le mando al broker un stop que ya se sabia absurdo"


# --------------------------------------------------------------------------
# Un numero mal leido en una sola posicion
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mensaje, stop_leido", [
    ("MOVER SL A 444", 444.0),      # digito comido
    ("Move SL to 44380", 44380.0),  # digito de mas
])
def test_un_stop_con_la_escala_cambiada_no_se_aplica(tmp_path, mensaje, stop_leido):
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)

    resultado = send(engine, mensaje, message_id=2)

    assert store.open_positions()[0].stop_loss == 4420.0, (
        f"se movio el stop del oro a {stop_leido} con el oro en {ORO}"
    )
    assert resultado["status"] == "sl_movido_parcial"


def test_un_stop_ancho_pero_sano_si_se_aplica(tmp_path):
    """Lo que NO hay que romper. Un stop 5% abajo es un stop de swing, no un
    error: si esto lo rechaza, el filtro es inservible."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)

    resultado = send(engine, "Move SL to 4200", message_id=2)

    assert store.open_positions()[0].stop_loss == 4200.0
    assert resultado["status"] == "sl_movido"


def test_sin_precio_de_mercado_no_se_inventa_un_descarte(tmp_path):
    """Misma politica que en todo el resto: sin dato, esta capa no opina."""
    store, engine, _, _ = armar(tmp_path, {"XAUUSD": {"bid": 0.0, "ask": 0.0}})
    send(engine, SENAL_ORO, message_id=1)

    resultado = send(engine, "MOVER SL A 444", message_id=2)

    assert resultado["status"] == "sl_movido", "sin cotizacion se bloqueo igual"
    assert store.open_positions()[0].stop_loss == 444.0


def test_el_breakeven_tambien_se_verifica(tmp_path):
    """El breakeven usa la entrada guardada, que puede ser vieja o mal leida.
    No hay motivo para confiar mas en ella que en un numero del mensaje."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)
    # Se ensucia la entrada registrada, como si hubiera entrado mal leida.
    store.open_positions()[0].entry = 444.0

    resultado = send(engine, "Move SL to BE", message_id=2)

    assert store.open_positions()[0].stop_loss == 4420.0
    assert resultado["status"] == "sl_movido_parcial"


def test_un_breakeven_sin_entrada_no_se_saltea_en_silencio(tmp_path):
    """`evaluate_management` solo rechaza si NINGUNA posicion tiene entrada. Con
    una mezcla, las que no la tienen se salteaban sin decir nada y el aviso
    igual anunciaba exito: te ibas creyendo que quedaron todas en breakeven."""
    store, engine, _, aviso = armar(tmp_path, {
        "XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5},
        "EURUSD": {"bid": 1.0850, "ask": 1.0860},
    })
    send(engine, SENAL_ORO, message_id=1)
    send(engine, SENAL_EUR, message_id=2)
    for p in store.open_positions():
        if p.symbol == "EURUSD":
            p.entry = None

    resultado = send(engine, "Move SL to BE", message_id=3)

    assert resultado["status"] == "sl_movido_parcial", "informo un exito completo"
    assert any("EURUSD" in d for d in resultado["descartadas"])
    assert "EURUSD" in aviso.mensajes[-1], "no dijo cual quedo sin proteger"


def test_un_move_sl_normal_sigue_funcionando(tmp_path):
    """El caso feliz, que es el 99% de los mensajes."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)

    resultado = send(engine, "Move SL to BE", message_id=2)

    assert resultado["status"] == "sl_movido"
    assert store.open_positions()[0].stop_loss == 4438.0


# --------------------------------------------------------------------------
# "No changes" no es un rechazo: es la prueba de que ya estaba puesto
#
# Caso real del canal (2026-09-05). Llego "MOVER SL A 4467", el bot lo movio
# bien, y despues el canal EDITO ese mensaje dos veces. Las ediciones se
# reprocesan a proposito, asi que el bot pidio el mismo cambio dos veces mas y
# MT5 contesto 10025 (NO_CHANGES). El bot lo conto como fallo y aviso "NO se
# pudo mover el SL de XAUUSD" justo despues de haberlo movido.
# --------------------------------------------------------------------------


TRADE_RETCODE_NO_CHANGES = 10025


def test_sin_cambios_cuenta_como_exito(tmp_path):
    store, engine, fake, _ = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)

    fake.rechazar_con = TRADE_RETCODE_NO_CHANGES
    resultado = send(engine, "Move SL to 4430", message_id=2)

    assert resultado["status"] == "sl_movido", (
        "informo un fallo cuando el stop ya estaba donde se pedia"
    )
    assert store.open_positions()[0].stop_loss == 4430.0


def test_no_se_avisa_un_fallo_que_no_ocurrio(tmp_path):
    """Leer 'NO se pudo mover el SL' cuando el stop SI esta puesto es peor que
    no recibir nada: te deja creyendo que quedaste sin proteccion."""
    _, engine, fake, aviso = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)

    fake.rechazar_con = TRADE_RETCODE_NO_CHANGES
    send(engine, "Move SL to 4430", message_id=2)

    assert not any("NO se pudo mover" in a for a in aviso.mensajes), aviso.mensajes


def test_el_motivo_explica_que_ya_estaba(tmp_path):
    _, engine, fake, _ = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)

    fake.rechazar_con = TRADE_RETCODE_NO_CHANGES
    resultado = send(engine, "Move SL to 4430", message_id=2)

    motivo = " ".join(str(o.get("reason", "")) for o in resultado["orders"])
    assert "ya estaba" in motivo


def test_un_rechazo_de_verdad_sigue_siendo_un_rechazo(tmp_path):
    """Lo que no hay que romper: 10016 (stop invalido) sigue fallando."""
    store, engine, fake, aviso = armar(tmp_path)
    send(engine, SENAL_ORO, message_id=1)

    fake.rechazar_con = 10016
    resultado = send(engine, "Move SL to 4430", message_id=2)

    assert resultado["status"] == "sl_movido_parcial"
    assert store.open_positions()[0].stop_loss == 4420.0
    assert any("NO se pudo mover" in a for a in aviso.mensajes)
