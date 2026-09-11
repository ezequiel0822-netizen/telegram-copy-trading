"""Cuanto avisa el bot por Telegram, y que NO se puede perder al callarlo.

POR QUE EXISTE
--------------
El usuario pidio silencio: "que no nos mande nada por telegram, solo que lo
haga y ya". Es razonable -con tres posiciones por senal el volumen se triplico-
pero apagar todo de un plumazo se lleva puestas dos cosas que el no esta
pidiendo perder:

1. EL FRENO POR PERDIDA DIARIA. Cuando salta, TODAS las senales del dia se
   rechazan. Su unica voz es el aviso de "Senal RECHAZADA". Sin el, un dia
   frenado se ve desde el telefono exactamente igual que un dia sin senales.

2. LA APERTURA A MEDIAS. Con POSITIONS_PER_SIGNAL=3, si entran 2 de 3, eso
   viajaba adentro del aviso de "SENAL ACEPTADA" -o sea, del de rutina-. El
   informe tampoco lo muestra. Callarlo deja al usuario creyendo que persigue
   tres objetivos cuando persigue dos, y ensucia justo el dato que motivo abrir
   las tres.

Y una advertencia para quien siga: cuando se escribieron estos tests, NINGUN
test del repo protegia la ENTREGA de un aviso. Los de test_desconexion.py
afirman sobre el TEXTO FUENTE (`inspect.getsource`), no sobre comportamiento.
Se comprobo: parchear `Notifier.enabled()` para devolver False dejaba la suite
entera en verde. Los de aca abajo son los primeros que se ponen en rojo si los
avisos dejan de salir.
"""

from __future__ import annotations

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings, send

ORO = 4438.0
SENAL = "XAUUSD BUY\nEntry 4438\nSL 4420\nTP1 4442\nTP2 4444\nTP3 4446"
SENAL_FUERA = "BTCUSD BUY\nEntry 79600\nSL 79363\nTP 79883"


class Aviso:
    """Un notificador que SI esta habilitado, para poder medir que sale."""

    def __init__(self):
        self.mensajes = []

    def enabled(self):
        return True

    async def send(self, texto):
        self.mensajes.append(texto)


def armar(tmp_path, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": ORO - 0.5, "ask": ORO + 0.5}})
    aviso = Aviso()
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), fake), aviso)
    return store, engine, fake, aviso


# --------------------------------------------------------------------------
# El valor de fabrica no cambia nada
# --------------------------------------------------------------------------

def test_de_fabrica_avisa_todo(tmp_path):
    _, engine, _, aviso = armar(tmp_path)

    send(engine, SENAL, message_id=1)

    assert any("SENAL ACEPTADA" in m for m in aviso.mensajes)


# --------------------------------------------------------------------------
# none: silencio
# --------------------------------------------------------------------------

def test_en_none_no_sale_nada(tmp_path):
    _, engine, _, aviso = armar(tmp_path, telegram_notify_level="none")

    send(engine, SENAL, message_id=1)

    assert aviso.mensajes == []


def test_en_none_tampoco_salen_los_problemas(tmp_path):
    """Es lo que el usuario pidio, y tiene que cumplirse tal cual: 'none' es
    silencio de verdad, no 'casi silencio'."""
    _, engine, _, aviso = armar(
        tmp_path, telegram_notify_level="none", allowed_symbols={"XAUUSD"},
    )

    send(engine, SENAL_FUERA, message_id=1)

    assert aviso.mensajes == []


def test_en_none_igual_opera(tmp_path):
    """Callar los avisos no puede cambiar lo que el bot HACE."""
    store, engine, _, _ = armar(
        tmp_path, telegram_notify_level="none", positions_per_signal=3,
    )

    send(engine, SENAL, message_id=1)

    assert len(store.open_positions()) == 3


# --------------------------------------------------------------------------
# problems: lo que no se puede perder
# --------------------------------------------------------------------------

def test_en_problems_se_calla_la_apertura_normal(tmp_path):
    _, engine, _, aviso = armar(tmp_path, telegram_notify_level="problems")

    send(engine, SENAL, message_id=1)

    assert not any("SENAL ACEPTADA" in m for m in aviso.mensajes)


def test_en_problems_un_rechazo_SI_avisa(tmp_path):
    """El caso que importa: el freno por perdida diaria habla por aca. Si este
    test se pone en rojo, un dia entero frenado pasa desapercibido."""
    _, engine, _, aviso = armar(
        tmp_path, telegram_notify_level="problems", allowed_symbols={"XAUUSD"},
    )

    send(engine, SENAL_FUERA, message_id=1)

    assert any("RECHAZADA" in m for m in aviso.mensajes)


def test_en_problems_un_cierre_normal_se_calla(tmp_path):
    _, engine, _, aviso = armar(tmp_path, telegram_notify_level="problems")
    send(engine, SENAL, message_id=1)
    aviso.mensajes.clear()

    send(engine, "Close XAUUSD", message_id=2)

    assert aviso.mensajes == []


def test_en_problems_un_sl_movido_bien_se_calla(tmp_path):
    _, engine, _, aviso = armar(tmp_path, telegram_notify_level="problems")
    send(engine, SENAL, message_id=1)
    aviso.mensajes.clear()

    send(engine, "Move SL to BE", message_id=2)

    assert aviso.mensajes == []


# --------------------------------------------------------------------------
# La apertura a medias: el hueco que encontro la revision
# --------------------------------------------------------------------------

def test_una_apertura_a_medias_avisa_por_su_cuenta(tmp_path):
    """Con 3 objetivos y lugar para 2, entran 2. Eso tiene que avisarse aunque
    los avisos de rutina esten callados: es informacion de que algo no se hizo.

    Antes viajaba adentro del 'SENAL ACEPTADA' -el aviso de rutina- asi que se
    perdia justo cuando mas falta hace.
    """
    _, engine, fake, aviso = armar(
        tmp_path, telegram_notify_level="problems", positions_per_signal=3,
    )
    # El broker acepta las dos primeras y rechaza la tercera. Es como pasa en
    # produccion: los tres pedidos difieren solo en el TP, asi que los rechazos
    # que dependen del objetivo -distancia de stops, requote- caen de a uno.
    fake.rechazar_a_partir_de = 3

    send(engine, SENAL, message_id=1)

    assert any("2 de 3" in m for m in aviso.mensajes), (
        "una apertura parcial quedo invisible: el usuario cree tener tres "
        "posiciones persiguiendo tres objetivos y tiene dos"
    )


def test_una_apertura_completa_no_inventa_un_problema(tmp_path):
    """La contracara: si entraron las tres, no hay nada que avisar."""
    _, engine, _, aviso = armar(
        tmp_path, telegram_notify_level="problems", positions_per_signal=3,
    )

    send(engine, SENAL, message_id=1)

    assert aviso.mensajes == []


# --------------------------------------------------------------------------
# La configuracion
# --------------------------------------------------------------------------

def test_un_nivel_mal_escrito_no_arranca(tmp_path):
    """Un 'ninguno' en vez de 'none' dejaria al usuario creyendo que apago los
    avisos. Falla al arrancar y dice cuales son los valores validos."""
    from tct.config import ConfigError, load_settings

    (tmp_path / ".env").write_text(
        "TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\n"
        "TELEGRAM_SESSION_NAME=s\nTELEGRAM_SOURCE_CHATS=-100\n"
        "TELEGRAM_NOTIFY_LEVEL=ninguno\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc:
        load_settings(tmp_path / ".env")

    assert "none" in str(exc.value), "no dice cuales son los valores validos"


@pytest.mark.parametrize("nivel", ["all", "problems", "none"])
def test_los_tres_niveles_se_aceptan(tmp_path, nivel):
    from tct.config import load_settings

    (tmp_path / ".env").write_text(
        "TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\n"
        "TELEGRAM_SESSION_NAME=s\nTELEGRAM_SOURCE_CHATS=-100\n"
        f"TELEGRAM_NOTIFY_LEVEL={nivel}\n",
        encoding="utf-8",
    )

    assert load_settings(tmp_path / ".env").telegram_notify_level == nivel


def test_el_arranque_no_dice_configuradas_sin_chat_id(tmp_path):
    """Mentia: miraba solo el token, pero `Notifier.enabled()` exige los dos.
    Con el chat_id vacio anunciaba notificaciones y no llegaba ni una, y el
    usuario descartaba la hipotesis correcta cuando algo fallaba en silencio."""
    settings = build_settings(
        tmp_path, telegram_bot_token="123:abc", telegram_notify_chat_id="",
    )

    linea = [l for l in settings.describe().splitlines() if "Notificaciones" in l][0]

    assert "apagadas" in linea
    assert "TELEGRAM_NOTIFY_CHAT_ID" in linea, "no dice QUE falta"


def test_el_arranque_avisa_cuando_estan_silenciadas_a_proposito(tmp_path):
    settings = build_settings(
        tmp_path, telegram_bot_token="123:abc", telegram_notify_chat_id="42",
        telegram_notify_level="none",
    )

    linea = [l for l in settings.describe().splitlines() if "Notificaciones" in l][0]

    assert "TELEGRAM_NOTIFY_LEVEL=none" in linea
