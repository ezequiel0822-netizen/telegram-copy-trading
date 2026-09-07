"""La IA local no puede deshacer lo que el parser descarto a proposito.

`parse_signal` devuelve None en dos situaciones que no tienen nada que ver:

    a) "esto no es un mensaje de trading"   -> no lo entendi
    b) "esto es una cronica o un recap"     -> lo entendi y lo descarte

El caso (b) es una DECISION, y de las caras: _NARRATIVA_RE y _RESULTADO_RE
existen porque "pudimos cerrar otra operacion" se ejecutaba como una orden de
cerrar TODO, y un recap abria operaciones. Son dos de los catorce bugs.

Con los dos casos devolviendo el mismo None, el motor no podia separarlos y le
mandaba tambien las cronicas a la IA, un modelo de 3B que las lee como
aperturas. La capa de IA rodeaba por atras una guarda puesta a proposito.
"""

from __future__ import annotations

import asyncio

from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.signals.parser import es_descarte_deliberado, parse_signal
from tct.store import Store
from tests.test_engine import build_settings, send

# Mensajes REALES del canal, del 2026-09-06.
RECAP_1 = ("Así que, chicos, aquí están nuestros resultados de la primera "
           "operación. Lo considero un buen comienzo")
RECAP_2 = ("➡️ Así que, chicos, nuestra segunda operación del día ya está "
           "completa. Entramos en el punto más favorable")
CRONICA = "Hoy es un dia magico. Pudimos cerrar otra operacion"
CHARLA = "Chicos, ya estoy en línea y listo para operar EMPEZAREMOS EN 20 MINUTOS"


class IAEspia:
    """Cuenta cuantas veces la llamaron. No interpreta nada."""

    def __init__(self):
        self.consultada: list[str] = []

    async def interpretar(self, texto, _metadata):
        self.consultada.append(texto)
        return None


def armar(tmp_path):
    settings = build_settings(tmp_path, enable_ollama=True)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    ia = IAEspia()
    return store, Engine(settings, store, PaperBroker(), ollama=ia), ia


# --------------------------------------------------------------------------
# La regla, sola
# --------------------------------------------------------------------------


def test_un_recap_con_palabra_de_resultado_es_descarte_deliberado():
    assert es_descarte_deliberado(RECAP_1)   # "nuestros RESULTADOS"
    assert es_descarte_deliberado(CRONICA)   # "PUDIMOS cerrar"


def test_hay_recaps_que_los_regex_NO_atajan():
    """RECAP_2 no lleva ninguna palabra de resultado ni de cronica: dice
    "nuestra segunda operacion del dia ya esta completa". El parser lo
    descarta por otro motivo -no hay lado ni gestion- y esta bien que la IA lo
    mire.

    Se deja escrito para que nadie ensanche los regex tratando de atajarlo:
    ensancharlos es como nacieron las trampas de la seccion 5. Ese caso lo
    resuelve la otra guarda, la de interpretaciones inutilizables."""
    assert not es_descarte_deliberado(RECAP_2)


def test_la_charla_suelta_no_es_un_descarte_deliberado():
    """No lleva ninguna palabra de resultado ni de cronica: el parser
    simplemente no vio nada. Ahi la IA SI puede aportar."""
    assert not es_descarte_deliberado(CHARLA)


def test_una_senal_normal_tampoco():
    assert not es_descarte_deliberado("XAUUSD BUY 4386 SL 4380 TP 4390")


# --------------------------------------------------------------------------
# El efecto: a quien se le pregunta y a quien no
# --------------------------------------------------------------------------


def test_a_la_ia_no_se_le_pasan_los_recaps(tmp_path):
    """El caso medido: seis notificaciones de 'la IA interpreto esto' en un
    dia, todas por recaps que el parser ya habia descartado bien."""
    _, engine, ia = armar(tmp_path)

    send(engine, RECAP_1, message_id=1)
    send(engine, CRONICA, message_id=2)

    assert ia.consultada == [], (
        "la IA opino sobre mensajes que el parser habia descartado a proposito"
    )


def test_a_la_ia_si_se_le_pasa_lo_que_el_parser_no_entendio(tmp_path):
    """Lo que NO hay que romper: para eso existe esa capa."""
    _, engine, ia = armar(tmp_path)

    send(engine, "oro compren en 4386 pongan stop 4380", message_id=1)

    assert len(ia.consultada) == 1


def test_un_recap_sigue_sin_operar_nada(tmp_path):
    """Lo importante de verdad. Antes tampoco operaba, porque
    OLLAMA_AUTO_EXECUTE esta en false: esto fija que siga sin hacerlo aunque
    alguien encienda esa variable."""
    settings = build_settings(tmp_path, enable_ollama=True, ollama_auto_execute=True)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)

    class IAQueAlucina:
        async def interpretar(self, texto, metadata):
            return parse_signal("XAUUSD BUY 4386\nSL 4380\nTP 4390",
                                message_id=metadata.get("message_id"),
                                chat_id=metadata.get("chat_id"))

    engine = Engine(settings, store, PaperBroker(), ollama=IAQueAlucina())

    send(engine, RECAP_1, message_id=1)

    assert store.open_positions() == [], (
        "un recap termino abriendo una operacion via la IA"
    )


def test_sin_ia_todo_se_comporta_igual(tmp_path):
    """La capa es opcional: apagarla no puede cambiar lo que se opera."""
    settings = build_settings(tmp_path)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker())

    assert send(engine, RECAP_1, message_id=1)["status"] == "ignorado"


# --------------------------------------------------------------------------
# La segunda guarda: una interpretacion que no se puede usar no se avisa
#
# Cubre los recaps que los regex NO atajan. Da igual por que la IA devolvio
# una apertura sin simbolo: no se puede ejecutar, asi que avisarla es ruido.
# --------------------------------------------------------------------------


class IASinSimbolo:
    """Devuelve una apertura sin simbolo ni entrada, como paso de verdad."""

    async def interpretar(self, _texto, metadata):
        from tct.signals.models import EventType, SignalEvent

        return SignalEvent(
            event_type=EventType.OPEN, symbol=None, side=None, entry_low=None,
            raw_message="lo que sea", source="ollama",
            telegram_message_id=metadata.get("message_id"),
            telegram_chat_id=metadata.get("chat_id"),
        )


def test_una_apertura_sin_simbolo_no_genera_aviso(tmp_path):
    """Es literal lo que se vio en el informe: '? entrada=-'. El riesgo la
    rechazaria con 'no se pudo identificar el simbolo', asi que avisarla es
    ruido que ademas parece importante."""
    avisos = []

    class Aviso:
        def enabled(self):
            return True

        async def send(self, texto):
            avisos.append(texto)

    settings = build_settings(tmp_path, enable_ollama=True)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker(), Aviso(), ollama=IASinSimbolo())

    resultado = send(engine, RECAP_2, message_id=1)

    assert resultado["status"] == "ignorado"
    assert avisos == [], f"aviso de una interpretacion inutilizable: {avisos}"


def test_una_interpretacion_completa_si_se_avisa(tmp_path):
    """Lo que NO hay que romper: para eso existe la capa de IA."""
    avisos = []

    class Aviso:
        def enabled(self):
            return True

        async def send(self, texto):
            avisos.append(texto)

    # `parse_signal` deja source="text"; la capa de IA lo marca como "ollama",
    # que es lo que hace que el motor avise en vez de operar.
    from dataclasses import replace

    class IAUtil:
        async def interpretar(self, _texto, metadata):
            base = parse_signal("XAUUSD BUY 4386\nSL 4380\nTP 4390",
                                message_id=metadata.get("message_id"),
                                chat_id=metadata.get("chat_id"))
            return replace(base, source="ollama")

    settings = build_settings(tmp_path, enable_ollama=True)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker(), Aviso(), ollama=IAUtil())

    resultado = send(engine, "oro compren en 4386 pongan stop 4380", message_id=1)

    assert resultado["status"] == "sugerencia_ia"
    assert any("XAUUSD" in a for a in avisos)
