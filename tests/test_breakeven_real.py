"""El breakeven va al precio al que el broker LLENO, no al que dijo el mensaje.

POR QUE EXISTE ESTE ARCHIVO
---------------------------
Una orden a mercado entra al precio de AHORA. El numero que el canal escribe en
la senal es el precio que EL vio cuando la mando, y para cuando la orden llega
al broker ya no es el mismo: medido sobre 12 operaciones reales, la diferencia
fue de 0.02% a 0.07%. En oro, decimas de punto.

Esa diferencia no importa para nada... salvo para el breakeven, que es
exactamente la operacion de "poner el stop donde entre". Moverlo al numero del
mensaje en vez de al precio de llenado deja el stop del lado equivocado de la
entrada real, siempre por la distancia del spread. Las tres operaciones que el
canal cerro "en breakeven" en la primera semana:

    SELL 4467, lleno en 4467.745, stop a 4467.0  ->  +0.57
    BUY  4387, lleno en 4387.315, stop a 4387.0  ->  -0.42
    SELL 4334, lleno en 4333.025, stop a 4334.0  ->  -1.08

Dos de tres perdieron. No era slippage: era el stop mal puesto, siempre igual.

Y hay un segundo caso, que es como habla este canal en particular: no dice
"mover a BE", dice "MOVER SL A 4467" escribiendo el numero de la entrada. Eso
llega al parser como un stop explicito, no como un breakeven, asi que hay que
reconocerlo por el numero.
"""

from __future__ import annotations

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings, send

# El fake cotiza con medio punto de spread a cada lado, asi que una compra a
# mercado entra en 4438.5 aunque el mensaje diga 4438.
ORO = 4438.0
ASK = ORO + 0.5
BID = ORO - 0.5
SENAL = "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4460"


class Aviso:
    def __init__(self):
        self.mensajes = []

    def enabled(self):
        return True

    async def send(self, texto):
        self.mensajes.append(texto)


def armar(tmp_path, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": BID, "ask": ASK}})
    aviso = Aviso()
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), fake), aviso)
    return store, engine, fake, aviso


# --------------------------------------------------------------------------
# El precio real se guarda
# --------------------------------------------------------------------------

def test_la_posicion_guarda_el_precio_al_que_lleno(tmp_path):
    """Sin esto no hay forma de saber donde esta la posicion de verdad."""
    store, engine, _, _ = armar(tmp_path)

    send(engine, SENAL, message_id=1)

    posicion = store.open_positions()[0]
    assert posicion.entry == 4438.0, "la entrada del mensaje se guarda igual"
    assert posicion.entry_real == ASK, "y el precio al que el broker lleno, aparte"


def test_el_precio_real_sobrevive_a_un_reinicio(tmp_path):
    """Se guarda en el estado, que es lo que se relee al arrancar. Si se
    perdiera, el primer breakeven despues de un reinicio volveria a quedar mal
    puesto y nadie lo notaria."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL, message_id=1)

    settings = engine.settings
    otro = Store(settings.events_path, settings.paper_trades_path, settings.state_path)

    assert otro.open_positions()[0].entry_real == ASK


# --------------------------------------------------------------------------
# "Move SL to BE": el caso con palabra
# --------------------------------------------------------------------------

def test_el_breakeven_va_al_precio_real_y_no_al_del_mensaje(tmp_path):
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL, message_id=1)

    send(engine, "Move SL to BE", message_id=2)

    assert store.open_positions()[0].stop_loss == ASK, (
        "el stop quedo en el numero del mensaje: eso es una perdida del tamano "
        "del spread, disfrazada de breakeven"
    )


def test_sin_precio_real_cae_en_la_entrada_del_mensaje(tmp_path):
    """Paper trading y posiciones viejas no tienen `entry_real`. Ahi el
    comportamiento tiene que seguir siendo el de antes, no romperse."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    store.open_positions()[0].entry_real = None

    send(engine, "Move SL to BE", message_id=2)

    assert store.open_positions()[0].stop_loss == 4438.0


# --------------------------------------------------------------------------
# "MOVER SL A 4438": el caso como lo escribe ESTE canal
# --------------------------------------------------------------------------

def test_mover_el_sl_al_numero_de_la_entrada_es_un_breakeven(tmp_path):
    """El canal no dice "BE": escribe el numero de la entrada. Tratarlo al pie
    de la letra es la causa de las dos perdidas del encabezado."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER SL A 4438", message_id=2)

    assert store.open_positions()[0].stop_loss == ASK


def test_el_aviso_lo_llama_breakeven_aunque_viniera_como_numero(tmp_path):
    """Lo unico que la persona ve desde el telefono es el aviso. "SL movido a
    4438" y "SL movido a breakeven" describen lo mismo; el segundo se entiende."""
    store, engine, _, aviso = armar(tmp_path)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER SL A 4438", message_id=2)

    assert "breakeven" in aviso.mensajes[-1]


def test_un_stop_a_otro_numero_se_respeta_al_pie_de_la_letra(tmp_path):
    """La contracara, y es la que hace que el cambio sea seguro: si el canal
    pide un stop que NO es la entrada, se pone ese y no otro. Es un stop que
    alguien eligio a proposito, y pisarlo seria mucho peor que el problema que
    este arreglo resuelve."""
    store, engine, _, _ = armar(tmp_path)
    send(engine, SENAL, message_id=1)

    send(engine, "MOVER SL A 4430", message_id=2)

    assert store.open_positions()[0].stop_loss == 4430.0


def test_se_puede_apagar_y_vuelve_el_comportamiento_viejo(tmp_path):
    """Toda proteccion que toca plata tiene que poder apagarse desde el .env,
    sin editar codigo."""
    store, engine, _, _ = armar(tmp_path, breakeven_uses_real_entry=False)
    send(engine, SENAL, message_id=1)

    send(engine, "Move SL to BE", message_id=2)

    assert store.open_positions()[0].stop_loss == 4438.0
