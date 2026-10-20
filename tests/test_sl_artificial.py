"""SL artificial y una posicion por cada TP (19/10).

Lo pidio para la demo de FxPro, para evaluarlo: "un stop loss al 90% de los
pips que faltan para el primer TP", o sea casi 1 a 1, y "que abra
simultaneamente todos [los TP]" a 0.02 cada uno. Antes de cambiar el bot se
mide con el repaso (`--sl-artificial 90 --posiciones todas`).

Lo que no se puede perder:
- La distancia se mide desde el precio al que se entra de verdad (el ask de un
  BUY, el bid de un SELL), no desde el numero del mensaje.
- Nunca arriesga mas que el SL del canal: si ese queda mas cerca, va ese.
- Una gestion del canal que ALEJA el stop no se aplica (un breakeven si).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tct.brokers.paper import PaperBroker
from tct.config import POSICIONES_TODAS, ConfigError, _Env, _posiciones_por_senal, _sl_artificial
from tct.engine import Engine
from tct.store import Store
from tests.test_engine import build_settings, send


class BrokerConCotizacion(PaperBroker):
    def __init__(self, bid: float | None, ask: float | None) -> None:
        super().__init__()
        self.cot = (bid, ask) if bid is not None and ask is not None else None
        self.pedidas = 0

    async def market_price(self, symbol: str) -> float | None:
        return (self.cot[0] + self.cot[1]) / 2 if self.cot else None

    async def quote(self, symbol: str):
        self.pedidas += 1
        return self.cot


def armar(tmp_path, bid=4419.9, ask=4420.1, pct=90.0, **overrides):
    overrides.setdefault("allowed_symbols", {"XAUUSD"})
    settings = build_settings(tmp_path, artificial_sl_pct=pct, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return Engine(settings, store, BrokerConCotizacion(bid, ask))


def sls(engine):
    return [p["stop_loss"] for p in engine.broker._positions.values()]


def hace(minutos: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat()


COMPRA = "XAUUSD BUY\nEntry 4420\nSL 4400\nTP 4425\nTP 4430\nTP 4435"
VENTA = "XAUUSD SELL\nEntry 4414\nSL 4430\nTP 4410\nTP 4406"


# --- el calculo ----------------------------------------------------------------

def test_compra_el_sl_va_al_90_por_ciento_de_lo_que_falta_desde_el_ask(tmp_path):
    engine = armar(tmp_path)

    resultado = send(engine, COMPRA)

    assert resultado["status"] == "aceptada"
    # Del ask 4420.1 al TP1 4425 faltan 4.9: el SL va 4.41 abajo.
    assert sls(engine) == [pytest.approx(4415.69)]
    [pos] = engine.store.open_positions()
    assert pos.stop_loss == pytest.approx(4415.69)


def test_venta_desde_el_bid(tmp_path):
    engine = armar(tmp_path, bid=4413.0, ask=4413.2)

    send(engine, VENTA)

    # Del bid 4413 al TP1 4410 faltan 3: el SL va 2.7 arriba.
    assert sls(engine) == [pytest.approx(4415.7)]


def test_queda_registrado_de_donde_salio(tmp_path):
    engine = armar(tmp_path)

    send(engine, COMPRA)

    [ev] = [e for e in engine.store.read_events() if e["kind"] == "sl_artificial"]
    datos = ev
    assert datos["sl_del_canal"] == 4400 and datos["sl"] == pytest.approx(4415.69)
    assert datos["referencia"] == pytest.approx(4420.1) and datos["tp1"] == 4425


def test_si_el_del_canal_queda_mas_cerca_va_el_del_canal(tmp_path):
    engine = armar(tmp_path)

    send(engine, COMPRA.replace("SL 4400", "SL 4418"))

    assert sls(engine) == [4418]


def test_apagado_es_el_sl_del_canal(tmp_path):
    engine = armar(tmp_path, pct=0.0)

    send(engine, COMPRA)

    assert sls(engine) == [4400]
    assert engine.broker.pedidas == 0
    assert not [e for e in engine.store.read_events() if e["kind"] == "sl_artificial"]


def test_si_el_precio_ya_llego_al_tp1_no_abre(tmp_path):
    # Sin el filtro de entrada tarde, para ver este motivo solo.
    engine = armar(tmp_path, bid=4425.0, ask=4425.2, max_spread_from_entry_pct=0)

    resultado = send(engine, COMPRA)

    assert resultado["status"] == "rechazada"
    assert any("ya llego al TP1" in r for r in resultado["reasons"])
    assert sls(engine) == []


def test_si_el_sl_quedaria_dentro_del_spread_no_abre(tmp_path):
    # Spread de 1 punto y el TP1 a 0.5 del ask: el SL iria por encima del bid.
    engine = armar(tmp_path, bid=4419.0, ask=4420.0, max_spread_from_entry_pct=0)

    resultado = send(engine, COMPRA.replace("TP 4425", "TP 4420.5"))

    assert resultado["status"] == "rechazada"
    assert any("lado equivocado del precio" in r for r in resultado["reasons"])


def test_sin_cotizacion_mide_desde_la_entrada_del_mensaje(tmp_path):
    engine = armar(tmp_path, bid=None, ask=None)

    send(engine, COMPRA)

    # Desde 4420 al TP1 4425: 5 puntos, SL 4.5 abajo.
    assert sls(engine) == [pytest.approx(4415.5)]


def test_una_pendiente_mide_desde_el_precio_de_la_orden(tmp_path):
    engine = armar(tmp_path, max_pending_distance_pct=0)

    send(engine, "XAUUSD BUY LIMIT 4410\nSL 4390\nTP 4420")

    assert sls(engine) == [pytest.approx(4401.0)]
    assert engine.broker.pedidas == 0


# --- todas las posiciones ----------------------------------------------------------

def test_una_posicion_por_cada_tp_todas_con_el_mismo_sl(tmp_path):
    engine = armar(tmp_path, positions_per_signal=POSICIONES_TODAS, max_open_trades=20)

    resultado = send(engine, COMPRA)

    assert resultado["status"] == "aceptada"
    tps = sorted(p["take_profit"] for p in engine.broker._positions.values())
    assert tps == [4425, 4430, 4435]
    assert sls(engine) == [pytest.approx(4415.69)] * 3


def test_todas_no_abre_mas_que_los_tp_que_trae(tmp_path):
    engine = armar(tmp_path, bid=4413.0, ask=4413.2,
                   positions_per_signal=POSICIONES_TODAS, max_open_trades=20)

    send(engine, VENTA)

    assert len(engine.broker._positions) == 2


# --- la gestion no lo aleja -----------------------------------------------------------

def test_un_mover_sl_que_lo_aleja_no_se_aplica(tmp_path):
    engine = armar(tmp_path)
    send(engine, COMPRA, message_id=1)

    send(engine, "MOVER SL A 4400", message_id=2)

    assert sls(engine) == [pytest.approx(4415.69)]


def test_un_mover_sl_que_lo_acerca_si(tmp_path):
    engine = armar(tmp_path)
    send(engine, COMPRA, message_id=1)

    send(engine, "MOVER SL A 4418", message_id=2)

    assert sls(engine) == [4418]


def test_sin_sl_artificial_el_mover_sl_se_obedece_como_siempre(tmp_path):
    engine = armar(tmp_path, pct=0.0)
    send(engine, COMPRA, message_id=1)

    send(engine, "MOVER SL A 4395", message_id=2)

    assert sls(engine) == [4395]


def test_una_correccion_del_canal_que_lo_aleja_no_se_aplica(tmp_path):
    engine = armar(tmp_path)
    send(engine, COMPRA, message_id=100, date=hace(0))

    send(engine, COMPRA.replace("SL 4400", "SL 4405"), message_id=100, is_edit=True,
         date=hace(1))

    assert sls(engine) == [pytest.approx(4415.69)]


def test_una_correccion_del_canal_que_lo_acerca_si(tmp_path):
    engine = armar(tmp_path)
    send(engine, COMPRA, message_id=100, date=hace(0))

    send(engine, COMPRA.replace("SL 4400", "SL 4417"), message_id=100, is_edit=True,
         date=hace(1))

    assert sls(engine) == [4417]


# --- la configuracion ------------------------------------------------------------------

def test_arranque_dice_que_sl_usa(tmp_path):
    assert "artificial, al 90%" in build_settings(tmp_path, artificial_sl_pct=90.0).describe()
    assert "el del canal" in build_settings(tmp_path).describe()


def test_todas_al_arrancar(tmp_path):
    texto = build_settings(tmp_path, positions_per_signal=POSICIONES_TODAS,
                           default_lot=0.02).describe()
    assert "una posicion por cada TP de la senal, de 0.02 cada una" in texto


@pytest.mark.parametrize("valor, esperado", [("", 0.0), ("90", 90.0), ("90,5", 90.5), ("0", 0.0)])
def test_lee_el_porcentaje(valor, esperado):
    assert _sl_artificial(_Env({"ARTIFICIAL_SL_PCT": valor})) == esperado


@pytest.mark.parametrize("valor", ["-90", "nan", "600", "inf"])
def test_un_porcentaje_raro_no_arranca(valor):
    with pytest.raises(ConfigError):
        _sl_artificial(_Env({"ARTIFICIAL_SL_PCT": valor}))


@pytest.mark.parametrize("valor, esperado", [("todas", POSICIONES_TODAS), ("TODOS", POSICIONES_TODAS),
                                             ("3", 3), ("", 1), ("0", 1)])
def test_posiciones_por_senal(valor, esperado):
    assert _posiciones_por_senal(_Env({"POSITIONS_PER_SIGNAL": valor})) == esperado


def test_tct_cambiar_acepta_los_valores_nuevos(tmp_path):
    from tct.archivo_env import _problema_con

    ruta = tmp_path / ".env"
    assert _problema_con("POSITIONS_PER_SIGNAL", "todas", ruta) is None
    assert _problema_con("ARTIFICIAL_SL_PCT", "90", ruta) is None
    assert _problema_con("ARTIFICIAL_SL_PCT", "-5", ruta) is not None
    assert _problema_con("ARTIFICIAL_SL_PCT", "noventa", ruta) is not None
    assert _problema_con("POSITIONS_PER_SIGNAL", "muchas", ruta) is not None


# --- con el broker de MetaTrader de verdad (terminal falsa) ----------------------------

def test_con_mt5_mide_desde_el_ask_y_redondea_a_los_decimales_del_simbolo(tmp_path):
    from tct.brokers.mt5_native import MT5NativeBroker
    from tests.fake_mt5 import FakeMT5, enchufar

    class ConDecimales(FakeMT5):
        def _info(self, name):
            info = super()._info(name)
            if info is not None:
                info.digits = 2
            return info

    terminal = ConDecimales()  # XAUUSD bid 4438.0, ask 4438.5
    settings = build_settings(tmp_path, artificial_sl_pct=90.0, allowed_symbols={"XAUUSD"})
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, enchufar(MT5NativeBroker(settings), terminal))

    resultado = send(engine, "XAUUSD BUY\nEntry 4438\nSL 4420\nTP 4443.3")

    assert resultado["status"] == "aceptada"
    [orden] = [r for r in terminal.enviados if "sl" in r]
    # Del ask 4438.5 al TP1 4443.3 faltan 4.8: 4.32 abajo, 4434.18 con 2 decimales.
    assert orden["sl"] == 4434.18
    # Y la posicion guarda ese, el que quedo en MetaTrader.
    [pos] = engine.store.open_positions()
    assert pos.stop_loss == 4434.18


# --- lo que encontro la revision (19/10) ------------------------------------------------

def test_la_misma_senal_repetida_no_abre_otra_vez(tmp_path):
    # La posicion tiene el SL artificial; la repetida trae el del canal.
    engine = armar(tmp_path, max_positions_per_symbol=10)
    send(engine, COMPRA, message_id=1)

    resultado = send(engine, COMPRA, message_id=2)

    assert resultado["status"] == "rechazada"
    assert any("misma senal" in r for r in resultado["reasons"])
    assert len(engine.broker._positions) == 1


def test_el_sl_del_canal_queda_en_la_posicion_y_en_el_registro(tmp_path):
    engine = armar(tmp_path)
    send(engine, COMPRA)

    [pos] = engine.store.open_positions()
    assert pos.sl_del_canal == 4400
    [ev] = [e for e in engine.store.read_events() if e["kind"] == "aceptada"]
    assert ev["sl_del_canal"] == 4400 and ev["signal"]["stop_loss"] == pytest.approx(4415.69)


class BrokerQueRecotiza(BrokerConCotizacion):
    """La primera orden vuelve con 'otro precio' y el precio sube 2 puntos."""

    def __init__(self):
        super().__init__(4419.9, 4420.1)
        self.mandados = []

    async def open_order(self, **kw):
        self.mandados.append(kw["stop_loss"])
        if len(self.mandados) == 1:
            self.cot = (4421.9, 4422.1)
            from tct.brokers.base import OrderResult
            return OrderResult(False, "open", "recotizacion", symbol=kw["symbol"],
                               raw={"retcode": 10004, "recotizacion": True})
        return await super().open_order(**kw)


def test_con_recotizacion_el_sl_se_vuelve_a_medir_desde_el_precio_nuevo(tmp_path):
    settings = build_settings(tmp_path, artificial_sl_pct=90.0, allowed_symbols={"XAUUSD"})
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    broker = BrokerQueRecotiza()
    engine = Engine(settings, store, broker)

    resultado = send(engine, COMPRA)

    assert resultado["status"] == "aceptada"
    # 1ra: del ask 4420.1 (SL 4415.69). 2da: del ask 4422.1 al TP1 4425 faltan
    # 2.9, SL 2.61 abajo: 4419.49. Y la posicion guarda el que se mando.
    assert broker.mandados == [pytest.approx(4415.69), pytest.approx(4419.49)]
    [pos] = engine.store.open_positions()
    assert pos.stop_loss == pytest.approx(4419.49)


def test_las_que_no_entran_por_max_open_trades_se_avisan(tmp_path, caplog):
    import logging

    engine = armar(tmp_path, positions_per_signal=POSICIONES_TODAS, max_open_trades=2)
    with caplog.at_level(logging.WARNING, logger="tct"):
        resultado = send(engine, COMPRA)

    assert resultado["status"] == "aceptada"
    assert len(engine.broker._positions) == 2
    [ev] = [e for e in engine.store.read_events() if e["kind"] == "aceptada"]
    assert ev["sin_lugar"] == [{"tp_indice": 3, "tp": 4435}]
    assert "entraron 2 de 3" in caplog.text and "TP3: no hay lugar" in caplog.text


def test_el_tp1_es_el_mas_cercano_aunque_vengan_desordenados(tmp_path):
    engine = armar(tmp_path)

    send(engine, "XAUUSD BUY\nEntry 4420\nSL 4400\nTP 4435\nTP 4430\nTP 4425")

    assert sls(engine) == [pytest.approx(4415.69)]


def test_el_aviso_dice_que_el_sl_es_artificial(tmp_path, caplog):
    import logging

    engine = armar(tmp_path)
    with caplog.at_level(logging.INFO, logger="tct"):
        send(engine, COMPRA)

    assert "(artificial, al 90% de la distancia al TP1; el canal decia 4400)" in caplog.text


def test_un_stop_viejo_en_la_cola_que_lo_alejaria_no_se_reintenta(tmp_path):
    import asyncio

    engine = armar(tmp_path)
    send(engine, COMPRA)
    [pos] = engine.store.open_positions()
    engine._sl_pendientes[pos.trade_id] = 4410.0  # mas lejos que 4415.69

    asyncio.run(engine._reintentar_stops())

    assert sls(engine) == [pytest.approx(4415.69)] and not engine._sl_pendientes


def test_estado_dice_como_opera(tmp_path):
    from tests.test_control import armar as armar_control, cmd

    _, _, _, control = armar_control(tmp_path)
    respuesta = cmd(control, "/estado")
    assert "Por senal : 1 posicion" in respuesta and "SL        : el del canal" in respuesta


def test_el_informe_mide_evaluar_stop_contra_el_del_canal(tmp_path):
    from tct.informe import tickets_operados

    engine = armar(tmp_path)
    send(engine, COMPRA)

    [fila] = tickets_operados(engine.store.read_events())
    assert fila["stop_loss"] == 4400 and fila["sl_puesto"] == pytest.approx(4415.69)


# --- la segunda revision (19/10) --------------------------------------------------------

class BrokerQueRecotizaUnaVez(BrokerConCotizacion):
    """La primera orden vuelve con 'otro precio' y el precio sube a `nuevo`."""

    def __init__(self, nuevo=(4421.9, 4422.1)):
        super().__init__(4419.9, 4420.1)
        self.nuevo = nuevo
        self.mandados = []

    async def open_order(self, **kw):
        self.mandados.append((kw["take_profit"], kw["stop_loss"]))
        if len(self.mandados) == 1:
            self.cot = self.nuevo
            from tct.brokers.base import OrderResult
            return OrderResult(False, "open", "recotizacion", symbol=kw["symbol"],
                               raw={"retcode": 10004, "recotizacion": True})
        return await super().open_order(**kw)


def motor_con(tmp_path, broker, **overrides):
    overrides.setdefault("allowed_symbols", {"XAUUSD"})
    settings = build_settings(tmp_path, artificial_sl_pct=90.0, **overrides)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    return Engine(settings, store, broker)


def test_con_recotizacion_todas_las_de_la_senal_llevan_el_sl_nuevo(tmp_path):
    broker = BrokerQueRecotizaUnaVez()
    engine = motor_con(tmp_path, broker, positions_per_signal=POSICIONES_TODAS,
                       max_open_trades=20)

    send(engine, COMPRA)

    # La del TP1 se recotizo y se volvio a medir; las del TP2 y TP3 salen con ese.
    assert [sl for _tp, sl in broker.mandados] == [
        pytest.approx(4415.69)] + [pytest.approx(4419.49)] * 3
    assert sls(engine) == [pytest.approx(4419.49)] * 3
    [ev] = [e for e in engine.store.read_events() if e["kind"] == "aceptada"]
    assert ev["signal"]["stop_loss"] == pytest.approx(4419.49)
    assert [a["sl"] for a in ev["aperturas"]] == [pytest.approx(4419.49)] * 3


def test_si_la_recotizacion_llega_al_tp1_no_manda_las_demas(tmp_path):
    broker = BrokerQueRecotizaUnaVez(nuevo=(4425.5, 4425.7))
    engine = motor_con(tmp_path, broker, positions_per_signal=POSICIONES_TODAS,
                       max_open_trades=20, max_spread_from_entry_pct=0)

    resultado = send(engine, COMPRA)

    assert resultado["status"] == "apertura_fallida"
    assert len(broker.mandados) == 1 and sls(engine) == []


def test_una_correccion_por_edicion_y_la_senal_corregida_repetida_no_abre(tmp_path):
    # Sin SL artificial: la cuenta real.
    engine = armar(tmp_path, pct=0.0, max_positions_per_symbol=10)
    send(engine, COMPRA, message_id=100, date=hace(0))
    corregida = COMPRA.replace("SL 4400", "SL 4417")
    send(engine, corregida, message_id=100, is_edit=True, date=hace(1))

    resultado = send(engine, corregida, message_id=101)

    assert resultado["status"] == "rechazada"
    assert len(engine.broker._positions) == 1


def test_un_breakeven_en_la_cola_sobrevive_a_una_correccion_mas_lejos(tmp_path):
    engine = armar(tmp_path, pct=0.0)
    send(engine, COMPRA, message_id=100, date=hace(0))
    [pos] = engine.store.open_positions()
    engine._sl_pendientes[pos.trade_id] = 4420.0  # el breakeven, rechazado por distancia

    send(engine, COMPRA.replace("SL 4400", "SL 4405"), message_id=100, is_edit=True,
         date=hace(1))

    assert sls(engine) == [4405]
    assert engine._sl_pendientes == {pos.trade_id: 4420.0}


def test_una_correccion_que_alejaria_el_sl_artificial_queda_registrada(tmp_path):
    engine = armar(tmp_path)
    send(engine, COMPRA, message_id=100, date=hace(0))

    send(engine, COMPRA.replace("SL 4400", "SL 4405"), message_id=100, is_edit=True,
         date=hace(1))

    [ev] = [e for e in engine.store.read_events() if e["kind"] == "sl_correccion_ignorada"]
    assert ev["no_aplicadas"][0]["sl"] == 4405 and "aleja" in ev["no_aplicadas"][0]["motivo"]


def test_sin_sl_del_canal_la_repetida_tampoco_abre(tmp_path, caplog):
    import logging

    sin_sl = "XAUUSD BUY\nEntry 4420\nTP 4425\nTP 4430"
    engine = armar(tmp_path, require_stop_loss=False, max_positions_per_symbol=10)
    with caplog.at_level(logging.INFO, logger="tct"):
        primera = send(engine, sin_sl, message_id=1)
    assert primera["status"] == "aceptada"
    assert sls(engine) == [pytest.approx(4415.69)]
    assert "el canal no mando SL" in caplog.text

    assert send(engine, sin_sl, message_id=2)["status"] == "rechazada"


def test_la_posicion_de_antes_sin_el_campo_se_compara_como_siempre(tmp_path):
    from tct.store import OpenPosition

    vieja = OpenPosition.from_dict({
        "trade_id": "x", "symbol": "XAUUSD", "side": "BUY", "lot": 0.01, "entry": 4420,
        "stop_loss": 4400, "take_profits": [4425], "opened_at": "2026-10-01T00:00:00+00:00"})
    assert vieja.sl_del_canal is None and vieja.sl_artificial is False
