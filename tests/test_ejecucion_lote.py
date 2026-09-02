"""El volumen que SALE al broker, y que el estado no coincida con MT5.

Todo esto corre contra `tests/fake_mt5.py`, no contra el broker de papel. Es
deliberado: el broker de papel acepta cualquier volumen, nunca lo ajusta y
nunca rechaza, asi que el codigo que decide cuanto se manda y que se registra
despues no lo ejercitaba ningun test.
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.engine import Engine
from tct.store import Store
from tests.fake_mt5 import FakeMT5, enchufar
from tests.test_engine import build_settings, send

SENAL = "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4460"


def armar(tmp_path, simbolos=None, **overrides):
    settings = build_settings(tmp_path, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5(simbolos or {"XAUUSD": {"bid": 4438.0, "ask": 4438.5}})
    broker = enchufar(MT5NativeBroker(settings), fake)
    return settings, store, Engine(settings, store, broker), fake


# --------------------------------------------------------------------------
# MAX_LOT es un techo, no una sugerencia
# --------------------------------------------------------------------------


def test_no_se_abre_si_el_lote_minimo_del_instrumento_supera_max_lot(tmp_path):
    """`_normalize_volume` SUBE el lote hasta el minimo del instrumento. Con
    DEFAULT_LOT=0.01, MAX_LOT=0.01 y un indice cuyo volume_min es 0.1, se
    mandaba una posicion diez veces mas grande que el techo configurado, y
    risk.py no lo veia porque compara default_lot contra max_lot, nunca el
    volumen que se envia."""
    _, store, engine, fake = armar(
        tmp_path,
        {"XAUUSD": {"bid": 4438.0, "ask": 4438.5, "volume_min": 0.1}},
        default_lot=0.01, max_lot=0.01,
    )

    resultado = send(engine, SENAL)

    assert fake.volumenes_enviados() == [], "se mando una orden por encima de MAX_LOT"
    assert resultado["status"] == "apertura_fallida"
    assert store.open_positions() == [], "quedo una posicion que el broker nunca abrio"


def test_el_motivo_dice_que_numero_poner(tmp_path):
    """El usuario no programa: 'volumen invalido' no le sirve de nada."""
    _, _, engine, _ = armar(
        tmp_path,
        {"XAUUSD": {"bid": 4438.0, "ask": 4438.5, "volume_min": 0.1}},
        default_lot=0.01, max_lot=0.01,
    )

    motivo = send(engine, SENAL)["reason"]

    assert "MAX_LOT" in motivo
    assert "0.1" in motivo, "no dice a cuanto habria que subirlo"
    assert ".env" in motivo


def test_un_lote_minimo_por_debajo_del_techo_si_opera(tmp_path):
    """Lo que no hay que romper: el ajuste al minimo del broker es normal y
    tiene que seguir funcionando mientras entre en el techo."""
    _, store, engine, fake = armar(
        tmp_path,
        {"XAUUSD": {"bid": 4438.0, "ask": 4438.5, "volume_min": 0.05}},
        default_lot=0.01, max_lot=0.10,
    )

    assert send(engine, SENAL)["status"] == "aceptada"
    assert fake.volumenes_enviados() == [0.05]
    assert len(store.open_positions()) == 1


def test_el_estado_guarda_el_lote_que_acepto_el_broker(tmp_path):
    """Guardar el lote PEDIDO deja al estado, a los avisos y a la matematica de
    los cierres parciales trabajando sobre un numero que en MT5 no existe."""
    _, store, engine, _ = armar(
        tmp_path,
        {"XAUUSD": {"bid": 4438.0, "ask": 4438.5, "volume_min": 0.05}},
        default_lot=0.01, max_lot=0.10,
    )

    send(engine, SENAL)

    assert store.open_positions()[0].lot == 0.05, (
        "el estado dice 0.01 y en el broker hay 0.05 abiertos"
    )


def test_cerrar_nunca_se_bloquea_por_max_lot(tmp_path):
    """Negarse a CERRAR por el techo seria mucho peor que abrir de mas: la
    posicion ya existe y hay que poder sacarla."""
    _, store, engine, fake = armar(
        tmp_path,
        {"XAUUSD": {"bid": 4438.0, "ask": 4438.5, "volume_min": 0.05}},
        default_lot=0.01, max_lot=0.10,
    )
    send(engine, SENAL, message_id=1)
    assert len(fake.posiciones_abiertas()) == 1

    send(engine, "Close XAUUSD now", message_id=2)

    assert fake.posiciones_abiertas() == [], "no pudo cerrar una posicion abierta"
    assert store.open_positions() == []


# --------------------------------------------------------------------------
# Llenado parcial: el broker ejecuta MENOS de lo que se le pidio
# --------------------------------------------------------------------------


def test_el_estado_guarda_el_volumen_llenado_no_el_pedido(tmp_path):
    """MT5 devuelve en `result.volume` el volumen CONFIRMADO, que no tiene por
    que ser el solicitado. El broker informaba el pedido, y como el motor ahora
    construye el estado con ese numero, el bot creia tener abierto el doble de
    lo que hay."""
    _, store, engine, fake = armar(tmp_path, default_lot=0.10, max_lot=0.10)
    fake.llenado = 0.5  # el broker llena la mitad

    send(engine, SENAL)

    assert fake.posiciones_abiertas()[0].volume == pytest.approx(0.05)
    assert store.open_positions()[0].lot == pytest.approx(0.05), (
        "el estado dice 0.10 y en MT5 hay 0.05"
    )


def test_tras_un_llenado_parcial_el_estado_sigue_coincidiendo_con_mt5(tmp_path):
    """La consecuencia encadenada: si el lote guardado esta inflado, la fraccion
    que queda tras un cierre parcial tambien lo esta.

    Se afirma el INVARIANTE (lo que dice el estado es lo que hay en MT5) y no
    numeros fijos: el volumen real depende del paso del instrumento y del
    redondeo de `_normalize_volume`, que puede dejar 0.02 donde uno esperaria
    0.025. Clavar el numero probaria el redondeo, no la coherencia."""
    _, store, engine, fake = armar(tmp_path, default_lot=0.10, max_lot=0.10)
    fake.llenado = 0.5
    send(engine, SENAL, message_id=1)
    lote_original = store.open_positions()[0].lot

    send(engine, "Close half XAUUSD", message_id=2)

    en_mt5 = fake.posiciones_abiertas()[0].volume
    restante = store.open_positions()[0].remaining_fraction
    assert restante == pytest.approx(en_mt5 / lote_original), (
        f"el estado dice que queda {restante:.0%} y en MT5 hay "
        f"{en_mt5} de {lote_original}"
    )


# --------------------------------------------------------------------------
# Cierre parcial sobre el lote minimo
# --------------------------------------------------------------------------


def test_un_parcial_que_termino_cerrando_todo_no_deja_media_posicion_fantasma(tmp_path):
    """Con DEFAULT_LOT=0.01 un 'close 50%' pide 0.005, el broker lo sube a su
    lote minimo y cierra el 100%. Confiando en la fraccion pedida, el estado
    creia conservar media posicion que en MT5 ya no existe: bloqueaba el
    simbolo por la regla de 'ya hay una posicion abierta' y ocupaba cupo de
    MAX_OPEN_TRADES para siempre."""
    _, store, engine, fake = armar(tmp_path, default_lot=0.01, max_lot=0.01)
    send(engine, SENAL, message_id=1)

    send(engine, "Close half XAUUSD", message_id=2)

    assert fake.volumenes_enviados()[-1] == 0.01, "el broker cerro el 100%"
    assert fake.posiciones_abiertas() == [], "en MT5 no queda nada"
    assert store.open_positions() == [], (
        "el estado cree que le queda media posicion que en MT5 ya no existe"
    )


def test_el_simbolo_queda_libre_despues_de_ese_cierre(tmp_path):
    """La consecuencia practica de la fantasma: la proxima senal del mismo
    instrumento se rechazaba para siempre."""
    _, _, engine, _ = armar(tmp_path, default_lot=0.01, max_lot=0.01)
    send(engine, SENAL, message_id=1)
    send(engine, "Close half XAUUSD", message_id=2)

    resultado = send(engine, SENAL, message_id=3)

    assert resultado["status"] == "aceptada", (
        "el simbolo quedo bloqueado por una posicion que no existe"
    )


def test_un_parcial_con_lote_grande_si_deja_la_mitad(tmp_path):
    """Lo que no hay que romper: con lote suficiente, medio es medio."""
    _, store, engine, fake = armar(
        tmp_path,
        {"XAUUSD": {"bid": 4438.0, "ask": 4438.5, "volume_min": 0.01}},
        default_lot=0.10, max_lot=0.10,
    )
    send(engine, SENAL, message_id=1)

    send(engine, "Close half XAUUSD", message_id=2)

    assert len(store.open_positions()) == 1
    assert store.open_positions()[0].remaining_fraction == pytest.approx(0.5)
    assert fake.posiciones_abiertas()[0].volume == pytest.approx(0.05)


# --------------------------------------------------------------------------
# Un parcial RECHAZADO no puede tocar el estado
# --------------------------------------------------------------------------


def test_un_parcial_rechazado_no_descuenta_nada(tmp_path):
    """`_handle_partial_close` no miraba `order.ok`: descontaba igual. Es la
    'operacion huerfana' de la seccion 6 del CONTEXTO_MAESTRO, en el unico
    handler que se habia quedado sin revisar."""
    _, store, engine, fake = armar(tmp_path, default_lot=0.10, max_lot=0.10)
    send(engine, SENAL, message_id=1)

    fake.rechazar_con = 10019  # sin dinero
    resultado = send(engine, "Close half XAUUSD", message_id=2)

    assert store.open_positions()[0].remaining_fraction == pytest.approx(1.0), (
        "descontó la mitad de una posicion que el broker no toco"
    )
    assert resultado["status"] != "cierre_parcial", "informo un cierre que no ocurrio"


def test_un_99_por_ciento_rechazado_no_borra_la_posicion(tmp_path):
    """El caso que perdia la operacion del todo: un solo 'close 99%' rechazado
    bajaba el restante debajo del umbral y borraba del estado una posicion que
    sigue viva en MT5. Nadie la volveria a encontrar."""
    _, store, engine, fake = armar(tmp_path, default_lot=0.10, max_lot=0.10)
    send(engine, SENAL, message_id=1)

    fake.rechazar_con = 10019
    send(engine, "Close 99% XAUUSD", message_id=2)

    assert len(store.open_positions()) == 1, (
        "se borro del estado una operacion que sigue abierta en MT5"
    )
    assert len(fake.posiciones_abiertas()) == 1


def test_tras_un_parcial_fallido_se_puede_reintentar(tmp_path):
    _, store, engine, fake = armar(tmp_path, default_lot=0.10, max_lot=0.10)
    send(engine, SENAL, message_id=1)
    fake.rechazar_con = 10019
    send(engine, "Close half XAUUSD", message_id=2)

    fake.rechazar_con = None
    send(engine, "Close half XAUUSD", message_id=3)

    assert store.open_positions()[0].remaining_fraction == pytest.approx(0.5)


def test_el_aviso_de_un_parcial_fallido_dice_que_sigue_abierto(tmp_path):
    avisos = []

    class Aviso:
        def enabled(self):
            return True

        async def send(self, texto):
            avisos.append(texto)

    settings = build_settings(tmp_path, default_lot=0.10, max_lot=0.10)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": 4438.0, "ask": 4438.5}})
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), fake), Aviso())

    send(engine, SENAL, message_id=1)
    fake.rechazar_con = 10019
    send(engine, "Close half XAUUSD", message_id=2)

    assert any("NO se pudo" in a for a in avisos), avisos


# --------------------------------------------------------------------------
# La posicion que el usuario cerro a mano en MetaTrader
#
# El escenario mas probable de todos, porque la propia guia se lo pide: "revisa
# las posiciones en MetaTrader y cerralas a mano si no las queres". Desde ese
# momento el bot tenia una posicion que no podia cerrar nunca.
# --------------------------------------------------------------------------


def test_una_posicion_cerrada_a_mano_se_saca_del_estado(tmp_path):
    """"Posicion inexistente" se trataba como un rechazo, o sea como "no pude
    cerrarla, sigue abierta". Es al reves: es la unica informacion capaz de
    resolver una fantasma."""
    _, store, engine, fake = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    fake._posiciones.clear()  # el usuario la cerro en MetaTrader

    resultado = send(engine, "Close XAUUSD now", message_id=2)

    assert store.open_positions() == [], "quedo una fantasma imposible de limpiar"
    assert resultado["status"] == "cerrada"
    assert resultado["ausentes"] == ["XAUUSD"]


def test_y_el_simbolo_queda_libre_para_la_proxima_senal(tmp_path):
    """La consecuencia real: sin esto, cada senal de oro se rechazaba con 'ya
    hay una posicion abierta' para siempre."""
    _, _, engine, fake = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    fake._posiciones.clear()
    send(engine, "Close XAUUSD now", message_id=2)

    assert send(engine, SENAL, message_id=3)["status"] == "aceptada"


def test_un_parcial_sobre_una_posicion_que_ya_no_esta_tambien_reconcilia(tmp_path):
    _, store, engine, fake = armar(tmp_path, default_lot=0.10, max_lot=0.10)
    send(engine, SENAL, message_id=1)
    fake._posiciones.clear()

    send(engine, "Close half XAUUSD", message_id=2)

    assert store.open_positions() == []


def test_un_error_de_consulta_NO_borra_la_posicion(tmp_path):
    """La direccion opuesta, y es la peligrosa. Si MT5 no puede contestar
    (terminal caida), la posicion puede estar perfectamente viva: darla por
    cerrada la dejaria corriendo sola y sin registro. MT5 distingue los dos
    casos, None es error y () es 'no esta', y hay que respetarlo."""
    _, store, engine, fake = armar(tmp_path)
    send(engine, SENAL, message_id=1)
    fake.positions_get = lambda ticket=None: None  # error de consulta

    resultado = send(engine, "Close XAUUSD now", message_id=2)

    assert len(store.open_positions()) == 1, (
        "se borro una posicion que puede estar viva en MT5"
    )
    assert resultado["status"] != "cerrada"


# --------------------------------------------------------------------------
# Mover el SL: el estado ya no mentia, el aviso si
# --------------------------------------------------------------------------


def test_un_move_sl_rechazado_no_se_informa_como_exito(tmp_path):
    """El estado ya conservaba el stop anterior (eso estaba arreglado), pero el
    aviso contaba los rechazos como movidas y decia 'SL movido en 1
    posicion(es)'. Creerte protegido en breakeven cuando el stop sigue donde
    estaba es peor que no recibir el aviso."""
    avisos = []

    class Aviso:
        def enabled(self):
            return True

        async def send(self, texto):
            avisos.append(texto)

    settings = build_settings(tmp_path)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    fake = FakeMT5({"XAUUSD": {"bid": 4438.0, "ask": 4438.5}})
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), fake), Aviso())

    send(engine, SENAL, message_id=1)
    fake.rechazar_con = 10016  # stop invalido
    resultado = send(engine, "Move SL to BE", message_id=2)

    assert resultado["status"] == "sl_movido_parcial"
    assert store.open_positions()[0].stop_loss == 4420.0, "el estado si tiene que aguantar"
    assert not any("SL movido a" in a for a in avisos), (
        f"informo un movimiento que no ocurrio: {avisos}"
    )
    assert any("NO se pudo mover" in a for a in avisos), avisos
