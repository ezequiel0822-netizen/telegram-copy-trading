"""El control contra el precio REAL del instrumento.

Todas las demas validaciones comparan el mensaje contra si mismo: que el SL
este del lado correcto, que el simbolo este en la lista, que la geometria
cierre. Ninguna puede distinguir un precio coherente de un precio correcto,
porque un mensaje mal leido queda internamente perfecto.

Esta es la unica capa que mira afuera, y por eso ataja una clase de errores
que ninguna otra ve: el simbolo equivocado, la escala cambiada, los digitos
comidos y el mensaje viejo.

Los tests entran por `engine.handle_message`, no por `evaluate_open`: lo que
importa verificar no es que la funcion sepa restar, sino que el precio viaje
del broker al riesgo. Esa conexion es exactamente la que le falto al freno por
perdida diaria, que estuvo escrito y desconectado con sus tests en verde.
"""

from __future__ import annotations

import pytest

from tct.brokers.paper import PaperBroker
from tct.engine import Engine
from tct.store import Store
from tests.test_engine import build_settings, send


class BrokerConPrecios(PaperBroker):
    """Broker de papel que ademas anota que cotizaciones le pidieron."""

    def __init__(self, precios: dict[str, float] | None = None) -> None:
        super().__init__()
        self.precios_simulados = dict(precios or {})
        self.consultas: list[str] = []

    async def market_price(self, symbol: str) -> float | None:
        self.consultas.append(symbol)
        return await super().market_price(symbol)


def armar(tmp_path, precios=None, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, BrokerConPrecios(precios))
    return settings, store, engine


# El oro cotizando donde lo tiene el usuario hoy, no donde lo tenia el ano
# pasado. La diferencia entre 4438 y 2345 es justamente el error que se busca.
ORO_HOY = 4438.0


# --------------------------------------------------------------------------
# Lo que ataja
# --------------------------------------------------------------------------


def test_una_entrada_lejos_del_precio_real_se_rechaza(tmp_path):
    """Una senal con precios de otra epoca. La geometria cierra perfecto:
    2335 esta por debajo de 2345 y 2355 por encima. Nada mas que el precio de
    mercado puede notar que el oro ya no vale 2345."""
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    resultado = send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    assert resultado["status"] == "rechazada"
    assert any("precio real" in r for r in resultado["reasons"])


def test_el_simbolo_equivocado_se_caza_por_el_precio(tmp_path):
    """El caso del CONTEXTO MAESTRO: un mensaje que nombra dos instrumentos y
    se ejecuta con el simbolo del otro. Con precios de BTC y simbolo de oro,
    lista blanca y geometria pasan; el precio no."""
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    resultado = send(engine, "XAUUSD BUY\nEntry 65000\nSL 64000\nTP 66000")

    assert resultado["status"] == "rechazada"
    assert any("MAX_SPREAD_FROM_ENTRY_PCT" in r for r in resultado["reasons"])


def test_la_escala_cambiada_se_caza_por_el_precio(tmp_path):
    """'DAX SELL 18.500' leido como 18.5. Los tres numeros escalan juntos, asi
    que la geometria no puede notarlo: SL sigue arriba y TP sigue abajo."""
    _, _, engine = armar(tmp_path, {"US30": 39500.0})

    resultado = send(engine, "US30 SELL\nEntry 39.5\nSL 39.6\nTP 39.4")

    assert resultado["status"] == "rechazada"
    assert any("precio real" in r for r in resultado["reasons"])


def test_el_motivo_dice_los_dos_numeros(tmp_path):
    """El usuario no programa: el rechazo tiene que decir contra que se
    comparo, no solo que fallo."""
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    motivo = " ".join(send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")["reasons"])

    assert "2345" in motivo, "no dice que entrada leyo"
    assert "4438" in motivo, "no dice contra que precio la comparo"
    assert ".env" in motivo, "no dice que hacer si la senal estaba bien"


# --------------------------------------------------------------------------
# Lo que NO puede frenar
# --------------------------------------------------------------------------


def test_una_entrada_pegada_al_precio_real_se_acepta(tmp_path):
    _, _, engine = armar(tmp_path, {"XAUUSD": 4440.0})
    assert send(engine, "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4460")["status"] == "aceptada"


def test_sin_precio_de_mercado_no_se_inventa_un_rechazo(tmp_path):
    """Sin dato no se bloquea por las dudas. Un broker lento no puede dejar al
    bot sin operar: misma politica que el freno por perdida diaria."""
    _, _, engine = armar(tmp_path)  # sin cotizaciones cargadas
    assert send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")["status"] == "aceptada"


def test_si_el_broker_revienta_al_dar_el_precio_se_sigue_operando(tmp_path):
    class BrokerQueRevienta(BrokerConPrecios):
        async def market_price(self, symbol: str) -> float | None:
            raise RuntimeError("timeout del broker")

    settings = build_settings(tmp_path)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, BrokerQueRevienta())

    assert send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")["status"] == "aceptada"


def test_con_el_control_apagado_no_frena_nada(tmp_path):
    """0 apaga el control. La proteccion tiene que ser facil de sacar."""
    _, _, engine = armar(
        tmp_path, {"XAUUSD": ORO_HOY},
        max_spread_from_entry_pct=0.0, max_pending_distance_pct=0.0,
    )
    assert send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")["status"] == "aceptada"


def test_apagado_ni_siquiera_le_pregunta_al_broker(tmp_path):
    """Sin control que alimentar, la consulta es latencia regalada en el
    camino critico de una senal."""
    _, _, engine = armar(
        tmp_path, {"XAUUSD": ORO_HOY},
        max_spread_from_entry_pct=0.0, max_pending_distance_pct=0.0,
    )
    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    assert engine.broker.consultas == []


# --------------------------------------------------------------------------
# Ordenes pendientes: se ponen lejos del mercado A PROPOSITO
# --------------------------------------------------------------------------


def test_una_pendiente_lejos_del_mercado_se_acepta(tmp_path):
    """Un BUY LIMIT a 4400 con el mercado en 4438 esta 0.86% abajo: mucho para
    una orden a mercado, normal para una pendiente. Medirla con la tolerancia
    estricta rechazaria senales buenas todos los dias."""
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    resultado = send(engine, "XAUUSD BUY LIMIT 4400\nSL 4380\nTP 4450")

    assert resultado["status"] == "aceptada"
    assert resultado["signal"]["order_type"] == "LIMIT"


def test_una_pendiente_absurda_igual_se_rechaza(tmp_path):
    """La banda ancha no es barra libre: a 47% del mercado no hay pendiente
    que valga, es un error de lectura."""
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    resultado = send(engine, "XAUUSD BUY LIMIT 2345\nSL 2335\nTP 2355")

    assert resultado["status"] == "rechazada"
    assert any("MAX_PENDING_DISTANCE_PCT" in r for r in resultado["reasons"])


# --------------------------------------------------------------------------
# Rangos de entrada
# --------------------------------------------------------------------------


def test_un_mercado_adentro_del_rango_se_acepta(tmp_path):
    """El grupo declara una banda de precios validos. Si el mercado esta
    adentro, la senal es exactamente lo que el grupo quiso, aunque el punto
    medio del rango quede lejos de la cotizacion."""
    _, _, engine = armar(tmp_path, {"XAUUSD": 4402.0})

    resultado = send(engine, "XAUUSD BUY\nEntry 4400-4480\nSL 4380\nTP 4520")

    assert resultado["status"] == "aceptada", (
        "se midio contra el punto medio (4440) en vez de contra el rango"
    )


def test_un_rango_entero_lejos_del_mercado_se_rechaza(tmp_path):
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    resultado = send(engine, "XAUUSD BUY\nEntry 2300-2350\nSL 2280\nTP 2400")

    assert resultado["status"] == "rechazada"


# --------------------------------------------------------------------------
# El cableado: que el precio viaje del broker al riesgo
# --------------------------------------------------------------------------


def test_el_motor_le_pide_el_precio_al_broker(tmp_path):
    """La conexion que falta cuando una proteccion queda escrita y muerta."""
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    send(engine, "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4460")

    assert engine.broker.consultas == ["XAUUSD"], (
        "el motor no le pidio la cotizacion al broker"
    )


def test_se_pide_con_el_simbolo_canonico(tmp_path):
    """Traducir el nombre es tarea del broker, igual que al mandar la orden.
    Si el control mirara un simbolo y la orden entrara en otro, el chequeo
    estaria validando algo que no es lo que se opera."""
    _, _, engine = armar(tmp_path, {"US30": 39500.0})

    send(engine, "US30 SELL\nEntry 39400\nSL 39600\nTP 39000")

    assert engine.broker.consultas == ["US30"]


def test_el_rechazo_queda_registrado_con_su_motivo_y_el_precio(tmp_path):
    """Es lo que despues permite contestar 'por que no tomo esta senal'."""
    _, store, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    rechazos = [e for e in store.read_events() if e["kind"] == "rechazada"]
    assert len(rechazos) == 1
    assert rechazos[0]["precio_mercado"] == ORO_HOY
    assert any("precio real" in r for r in rechazos[0]["reasons"])


def test_una_senal_rechazada_por_precio_no_deja_paper_trade_ni_posicion(tmp_path):
    _, store, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    send(engine, "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355")

    assert store.read_paper_trades() == []
    assert store.open_positions() == []


def test_el_precio_de_mercado_queda_en_el_paper_trade(tmp_path):
    """Sin esto, el P&L de los paper trades solo se puede calcular contra la
    entrada que dijo el mensaje, que es precisamente el numero en duda."""
    _, store, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})

    send(engine, "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4460")

    trades = store.read_paper_trades()
    assert len(trades) == 1
    assert trades[0]["precio_mercado"] == ORO_HOY


def test_el_aviso_muestra_la_entrada_y_el_mercado_juntos(tmp_path):
    """Para poder comparar de un vistazo desde el telefono."""
    _, _, engine = armar(tmp_path, {"XAUUSD": ORO_HOY})
    from tct.signals.parser import parse_signal

    evento = parse_signal("XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4460", message_id=1, chat_id=-1)
    texto = engine._format_open(evento, 0.01, [4460.0], None, ORO_HOY)

    assert "Entrada : 4438" in texto
    assert "Mercado : 4438" in texto


# --------------------------------------------------------------------------
# La configuracion se ve al arrancar
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, esperado",
    [
        ({}, "a mercado 0.5% / pendientes 3.0%"),
        ({"max_spread_from_entry_pct": 0.0}, "a mercado sin control"),
        ({"max_pending_distance_pct": 0.0}, "pendientes sin control"),
    ],
)
def test_el_arranque_muestra_el_control_contra_el_mercado(tmp_path, overrides, esperado):
    """Un numero en pantalla no prueba que la proteccion exista, pero callarlo
    garantiza que nadie note si falta."""
    settings = build_settings(tmp_path, **overrides)
    assert esperado in settings.describe()


# --------------------------------------------------------------------------
# Calibrar el numero: 'tct simular --con-precios'
#
# Es la unica forma de elegir el limite mirando los mensajes reales del grupo
# en vez de adivinar. Como quien lo lee no programa, lo que este resumen
# aconseja importa tanto como lo que calcula: un numero mal sugerido se copia
# al .env sin que nadie pueda notar que apago la proteccion.
# --------------------------------------------------------------------------


def _resumen(settings, distancias, capsys) -> str:
    from tct.cli import _resumen_de_distancias

    _resumen_de_distancias(settings, distancias)
    return capsys.readouterr().out


def test_la_sugerencia_sale_del_rechazo_mas_chico_no_del_mas_grande(tmp_path, capsys):
    """Con un rechazo dudoso (0.83%) y uno absurdo (47%), el limite que se
    sugiere tiene que dejar entrar el primero y seguir frenando el segundo.
    Sugerir el numero que los deja pasar a los dos es sugerir apagar todo."""
    settings = build_settings(tmp_path)
    salida = _resumen(settings, [
        ("XAUUSD", 0.83, True, "MAX_SPREAD_FROM_ENTRY_PCT"),
        ("XAUUSD", 47.16, True, "MAX_SPREAD_FROM_ENTRY_PCT"),
    ], capsys)

    # 0.83% redondeado hacia arriba con un tick de aire.
    assert "MAX_SPREAD_FROM_ENTRY_PCT=1.0" in salida
    assert "=47" not in salida, "sugirio un limite que apaga la proteccion"


def test_no_sugiere_ningun_numero_si_todos_los_rechazos_son_absurdos(tmp_path, capsys):
    """A 47% del precio real no hay senal buena. Ahi el consejo correcto no es
    un numero, es mirar por que el parser leyo eso."""
    settings = build_settings(tmp_path)
    salida = _resumen(
        settings, [("XAUUSD", 47.16, True, "MAX_SPREAD_FROM_ENTRY_PCT")], capsys
    )

    assert "MAX_SPREAD_FROM_ENTRY_PCT=" not in salida
    assert "parser" in salida


def test_la_sugerencia_nombra_la_llave_de_la_orden_que_se_rechazo(tmp_path, capsys):
    """Una pendiente rechazada se arregla con MAX_PENDING_DISTANCE_PCT.
    Mandar a tocar la otra variable no cambiaria nada y haria pensar que el
    filtro esta roto."""
    settings = build_settings(tmp_path)
    salida = _resumen(
        settings, [("XAUUSD", 3.4, True, "MAX_PENDING_DISTANCE_PCT")], capsys
    )

    assert "MAX_PENDING_DISTANCE_PCT=3.5" in salida


def test_el_resumen_avisa_que_compara_contra_el_precio_de_ahora(tmp_path, capsys):
    """Sin esta aclaracion el numero engana: reproducir mensajes de ayer
    contra precios de hoy da distancias enormes que nunca existieron."""
    settings = build_settings(tmp_path)
    salida = _resumen(
        settings, [("XAUUSD", 0.2, False, "MAX_SPREAD_FROM_ENTRY_PCT")], capsys
    )

    assert "AHORA" in salida


def test_calibrar_no_manda_ninguna_orden(tmp_path, capsys):
    """--con-precios conecta el broker. La promesa de 'simular' sin --ejecutar
    es que no toca nada, y leer cotizaciones no puede convertirse en operar."""
    import asyncio

    from tct.cli import _mostrar_distancia
    from tct.signals.parser import parse_signal

    class BrokerQueSoloLee(BrokerConPrecios):
        async def open_order(self, **kwargs):
            raise AssertionError("simular sin --ejecutar mando una orden")

        async def close_position(self, **kwargs):
            raise AssertionError("simular sin --ejecutar cerro una posicion")

        async def modify_stop_loss(self, **kwargs):
            raise AssertionError("simular sin --ejecutar movio un stop")

    settings = build_settings(tmp_path)
    broker = BrokerQueSoloLee({"XAUUSD": ORO_HOY})
    evento = parse_signal("XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355", message_id=1, chat_id=-1)

    distancias: list = []
    asyncio.run(_mostrar_distancia(broker, settings, evento, distancias))

    assert len(distancias) == 1
    assert distancias[0][2] is True, "no marco el rechazo"
    assert "RECHAZA" in capsys.readouterr().out
