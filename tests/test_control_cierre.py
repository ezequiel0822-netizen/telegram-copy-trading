"""La confirmacion de /cerrar, con DOS instancias escuchando el mismo chat.

Es la unica parte del sistema donde una persona, escribiendo un comando que
cree inofensivo, puede cerrar las posiciones de la cuenta REAL. Y es tambien la
mas facil de probar mal: con una sola instancia todo parece correcto.

En produccion hay dos procesos (demo y real, porque MT5 admite una cuenta por
proceso) y los dos leen los MISMOS Mensajes Guardados. Todo mensaje llega a las
dos instancias. Estos tests reproducen eso: cada mensaje se le pasa a las dos,
en orden, como hace Telegram.
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.paper import PaperBroker
from tct.config import LIVE
from tct.engine import Engine
from tct.store import Store
from tct.telegram.control import VENTANA_CONFIRMACION_SEG, ControlTelegram
from tests.test_engine import build_settings, send

SENAL = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"


def _instancia(tmp_path, nombre, *, live=False, broker=None):
    carpeta = tmp_path / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    settings = build_settings(
        carpeta,
        instance_name=nombre,
        trading_mode=LIVE if live else "PAPER_ONLY",
        allow_live_trading=live,
        events_path=carpeta / "events.jsonl",
        paper_trades_path=carpeta / "paper.jsonl",
        state_path=carpeta / "state.json",
    )
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, broker or PaperBroker())
    return settings, store, engine, ControlTelegram(settings, store, engine)


@pytest.fixture
def dos_instancias(tmp_path):
    """Una demo y una real, cada una con su posicion abierta."""
    _, store_demo, engine_demo, demo = _instancia(tmp_path, "demo")
    _, store_real, engine_real, real = _instancia(tmp_path, "real", live=True)
    send(engine_demo, SENAL, message_id=1)
    send(engine_real, SENAL, message_id=1)
    assert len(store_demo.open_positions()) == 1
    assert len(store_real.open_positions()) == 1
    return demo, real, store_demo, store_real


def a_las_dos(demo, real, texto):
    """Reparte un mensaje a las dos instancias, como hace Telegram."""
    return (
        asyncio.run(demo.manejar(texto)),
        asyncio.run(real.manejar(texto)),
    )


# --------------------------------------------------------------------------
# El peor bug del sistema: cerrar la cuenta real creyendo cerrar la demo
# --------------------------------------------------------------------------


def test_un_cerrar_dirigido_a_la_demo_no_deja_armada_a_la_real(dos_instancias):
    """La secuencia que uno tipea naturalmente: pedis cerrar, dudas, aclaras
    que era solo la demo, confirmas.

    Antes: el "/cerrar" a secas armaba a las DOS. El "/cerrar demo" siguiente
    no desarmaba a la real (el reset se salteaba justo para 'cerrar') y ademas
    no le contestaba nada, asi que quedaba armada EN SILENCIO. El "SI", que no
    tiene destinatario, disparaba a las dos y cerraba la cuenta real.
    """
    demo, real, store_demo, store_real = dos_instancias

    a_las_dos(demo, real, "/cerrar")        # arma a las dos
    a_las_dos(demo, real, "/cerrar demo")   # "no, solo la demo"
    a_las_dos(demo, real, "SI")

    assert store_demo.open_positions() == [], "la demo tenia que cerrarse"
    assert len(store_real.open_positions()) == 1, (
        "SE CERRO LA CUENTA REAL con un comando dirigido a la demo"
    )


def test_la_real_no_queda_armada_en_silencio(dos_instancias):
    """El sintoma que hacia invisible al bug: la real no contestaba nada, asi
    que no habia forma de darse cuenta de que seguia esperando el SI."""
    demo, real, _, _ = dos_instancias

    a_las_dos(demo, real, "/cerrar")
    a_las_dos(demo, real, "/cerrar demo")

    assert real._confirmacion is None, "la real quedo esperando un SI que no pidio"


def test_dirigir_el_cerrar_a_la_real_no_toca_la_demo(dos_instancias):
    """El caso simetrico, para que el arreglo no se pase de largo."""
    demo, real, store_demo, store_real = dos_instancias

    a_las_dos(demo, real, "/cerrar real")
    a_las_dos(demo, real, "SI")

    assert store_real.open_positions() == [], "la real tenia que cerrarse"
    assert len(store_demo.open_positions()) == 1, "se cerro la demo sin que se lo pidieran"


def test_cerrar_sin_destinatario_si_cierra_las_dos(dos_instancias):
    """Lo que NO hay que romper arreglando lo de arriba: sin destinatario, el
    comando es para todos, y eso sigue siendo lo correcto."""
    demo, real, store_demo, store_real = dos_instancias

    a_las_dos(demo, real, "/cerrar todo")
    a_las_dos(demo, real, "SI")

    assert store_demo.open_positions() == []
    assert store_real.open_positions() == []


# --------------------------------------------------------------------------
# La confirmacion caduca
# --------------------------------------------------------------------------


def test_la_confirmacion_caduca(tmp_path):
    """Un bool sin vencimiento es una bomba: te arrepentis, no contestas, y dos
    horas despues un 'si' sobre otro tema cierra la cuenta."""
    _, store, engine, control = _instancia(tmp_path, "demo")
    send(engine, SENAL)
    asyncio.run(control.manejar("/cerrar todo"))

    control._confirmacion["momento"] -= VENTANA_CONFIRMACION_SEG + 1
    respuesta = asyncio.run(control.manejar("SI"))

    assert len(store.open_positions()) == 1, "cerro con una confirmacion vencida"
    assert "vencio" in respuesta, "no aviso que estaba vencida; el silencio confunde"


def test_dentro_de_la_ventana_sigue_cerrando(tmp_path):
    _, store, engine, control = _instancia(tmp_path, "demo")
    send(engine, SENAL)
    asyncio.run(control.manejar("/cerrar todo"))

    control._confirmacion["momento"] -= VENTANA_CONFIRMACION_SEG - 5
    asyncio.run(control.manejar("SI"))

    assert store.open_positions() == []


# --------------------------------------------------------------------------
# "Cualquier otra cosa lo cancela" tiene que ser cierto
# --------------------------------------------------------------------------


@pytest.mark.parametrize("respuesta_del_usuario", ["no", "NO", "mejor no", "esperá", "?"])
def test_cualquier_otra_cosa_cancela_de_verdad(tmp_path, respuesta_del_usuario):
    """El bot promete 'cualquier otra cosa lo cancela'. Antes era mentira: solo
    se miraba si el texto era afirmativo, y todo lo demas se ignoraba en
    silencio dejando la confirmacion armada."""
    _, store, engine, control = _instancia(tmp_path, "demo")
    send(engine, SENAL)
    asyncio.run(control.manejar("/cerrar todo"))

    respuesta = asyncio.run(control.manejar(respuesta_del_usuario))

    assert control._confirmacion is None, "un 'no' dejo la confirmacion armada"
    assert respuesta is not None and "CANCELADO" in respuesta
    assert len(store.open_positions()) == 1

    # Y el SI posterior ya no puede cerrar nada.
    asyncio.run(control.manejar("SI"))
    assert len(store.open_positions()) == 1


def test_nuestras_propias_respuestas_no_cancelan_la_confirmacion(tmp_path):
    """El bot escribe en el mismo chat que escucha: su propio pedido de
    confirmacion vuelve a entrar. Si eso contara como 'cualquier otra cosa',
    la confirmacion se cancelaria sola antes de que la persona conteste."""
    _, _, engine, control = _instancia(tmp_path, "demo")
    send(engine, SENAL)
    pedido = asyncio.run(control.manejar("/cerrar todo"))

    asyncio.run(control.manejar(pedido))

    assert control._confirmacion is not None, "el bot se cancelo a si mismo"


# --------------------------------------------------------------------------
# Los dos silencios peligrosos
#
# Simetricos y los dos caros: quedarse armado sin avisar termina cerrando algo
# que no querias, y cancelar sin avisar te deja creyendo que cerraste.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("basura", ["/", "/   ", "/\t"])
def test_una_barra_pelada_no_deja_la_confirmacion_armada(tmp_path, basura):
    """`partes[0]` sobre un "/" solo reventaba con IndexError ANTES de
    desarmar. En produccion el listener se traga la excepcion: la persona no
    recibia respuesta, la confirmacion quedaba viva, y el SI siguiente cerraba.
    Un agujero justo en la propiedad que este modulo garantiza."""
    _, store, engine, control = _instancia(tmp_path, "demo")
    send(engine, SENAL)
    asyncio.run(control.manejar("/cerrar todo"))

    asyncio.run(control.manejar(basura))  # no puede reventar

    assert control._confirmacion is None, "quedo armada tras un comando roto"
    asyncio.run(control.manejar("SI"))
    assert len(store.open_positions()) == 1, "el SI cerro despues de un '/'"


@pytest.mark.parametrize("intermedio", ["/posiciones", "/estado", "/ayuda", "/loquesea", "/"])
def test_cancelar_por_otro_comando_se_avisa(tmp_path, intermedio):
    """Pedis /cerrar todo, mandas un /posiciones para chequear, contestas SI, y
    no pasa nada sin un solo mensaje. Te vas creyendo que cerraste."""
    _, store, engine, control = _instancia(tmp_path, "demo")
    send(engine, SENAL)
    asyncio.run(control.manejar("/cerrar todo"))

    respuesta = asyncio.run(control.manejar(intermedio))

    assert respuesta is not None, "cancelo el cierre sin decir nada"
    assert "CANCELADO" in respuesta.upper()
    assert len(store.open_positions()) == 1


def test_repetir_cerrar_no_dice_cancelado(tmp_path):
    """Lo que no hay que romper: un /cerrar nuevo se rearma y su propio mensaje
    ya dice como quedo la cosa. Un 'CANCELADO' ahi seria confuso."""
    _, _, engine, control = _instancia(tmp_path, "demo")
    send(engine, SENAL)
    asyncio.run(control.manejar("/cerrar todo"))

    respuesta = asyncio.run(control.manejar("/cerrar todo"))

    assert "CANCELADO" not in respuesta.upper()
    assert control._confirmacion is not None, "se desarmo cuando tenia que rearmarse"


def test_la_instancia_que_no_era_destinataria_avisa_que_desarmo(tmp_path):
    """Cuando la real desarma por un comando dirigido a la demo, decirlo es lo
    que permite notar que algo raro estaba pasando. El silencio ahi fue
    exactamente lo que hizo invisible al peor bug del proyecto."""
    demo, real, _, _ = dos_instancias_de(tmp_path)

    a_las_dos(demo, real, "/cerrar")
    _, respuesta_real = a_las_dos(demo, real, "/pausa demo")

    assert respuesta_real is not None and "CANCELADO" in respuesta_real.upper()


def dos_instancias_de(tmp_path):
    """Igual que la fixture, pero invocable desde un test que ya usa tmp_path."""
    _, store_demo, engine_demo, demo = _instancia(tmp_path, "demo")
    _, store_real, engine_real, real = _instancia(tmp_path, "real", live=True)
    send(engine_demo, SENAL, message_id=1)
    send(engine_real, SENAL, message_id=1)
    return demo, real, store_demo, store_real


# --------------------------------------------------------------------------
# Un cierre que falla a mitad
# --------------------------------------------------------------------------


class BrokerQueExplota(PaperBroker):
    def __init__(self):
        super().__init__()
        self.cerradas = 0

    async def close_position(self, **kwargs):
        self.cerradas += 1
        if self.cerradas > 1:
            raise RuntimeError("se corto la conexion con MT5")
        return await super().close_position(**kwargs)


def test_un_cierre_que_falla_a_mitad_contesta_igual(tmp_path):
    """La rama del SI no pasaba por ningun try/except: si el broker se cortaba,
    la persona se quedaba sin respuesta mientras las posiciones quedaban a
    medio cerrar. Sin respuesta y sin saberlo es la peor combinacion."""
    _, store, engine, control = _instancia(tmp_path, "demo", broker=BrokerQueExplota())
    send(engine, SENAL, message_id=1)
    send(engine, "EURUSD BUY\nEntry 1.08\nSL 1.07\nTP 1.09", message_id=2)
    assert len(store.open_positions()) == 2

    asyncio.run(control.manejar("/cerrar todo"))
    respuesta = asyncio.run(control.manejar("SI"))

    assert respuesta is not None, "se quedo mudo con posiciones a medio cerrar"
    assert "/posiciones" in respuesta, "no dice como revisar que quedo abierto"


def test_lo_que_alcanzo_a_cerrarse_queda_persistido(tmp_path):
    """Sin esto, un reinicio resucitaba en el estado posiciones que en MT5 ya
    estaban cerradas, y el bot las seguia contando contra MAX_OPEN_TRADES."""
    settings, store, engine, control = _instancia(
        tmp_path, "demo", broker=BrokerQueExplota()
    )
    send(engine, SENAL, message_id=1)
    send(engine, "EURUSD BUY\nEntry 1.08\nSL 1.07\nTP 1.09", message_id=2)

    asyncio.run(control.manejar("/cerrar todo"))
    asyncio.run(control.manejar("SI"))

    # Se relee del disco, como haria un reinicio.
    de_nuevo = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    assert len(de_nuevo.open_positions()) == 1, (
        "el cierre que si funciono no se persistio: al reiniciar reaparece"
    )
