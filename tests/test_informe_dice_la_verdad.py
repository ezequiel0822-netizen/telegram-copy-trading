"""Lo que `tct informe` decia mal, medido con la salida real del usuario.

El 2026-09-17 el usuario corrio `tct informe --horas 300 --con-resultados`
sobre la instancia de MetaQuotes, y la salida confirmo con datos reales los
hallazgos de una auditoria que nadie habia verificado:

    Mensajes de apertura distintos: 20
    (se procesaron 30 veces: ...)
         15  operadas
          3  rechazadas por el riesgo        <- era 1 mensaje, editado 3 veces
          3  el broker no las pudo abrir     <- 1 mensaje de BTC, 3 veces
          3  no se entendieron               <- 1 mensaje
          6  solo las entendio la IA         <- 2 mensajes
                                               suma 30, no 20

    UNA POR UNA: cada edicion en su propia fila, a la misma hora
    DISTANCIA AL PRECIO REAL (23 senales operadas)   <- 23 posiciones, 15 senales
    11:39 ...   <- sin fecha, en un rango de doce dias, y en hora UTC
    mercado=4404.844999999999

Es la herramienta con la que se diagnostica todo lo demas y con la que se va a
decidir si los tres TP rinden: un numero inflado ahi manda a buscar problemas
que no existen.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tct import cli
from tct.informe import (
    clasificar_desenlace,
    hora_local,
    precio,
    resumir,
    resumir_desenlaces,
)
from tct.store import Store

AHORA = datetime(2026, 9, 16, 20, 0, tzinfo=timezone.utc)


def ev(kind, mid, hace=1, simbolo="XAUUSD", **extra):
    e = {
        "ts": (AHORA - timedelta(hours=hace)).isoformat(),
        "kind": kind,
        "signal": {"symbol": simbolo, "side": "BUY", "entry": 4386.0,
                   "telegram_message_id": mid, "telegram_chat_id": -100},
    }
    e.update(extra)
    return e


def la_salida_real():
    """La forma exacta de lo que devolvio el informe del usuario."""
    eventos = [ev("aceptada", mid) for mid in range(1, 16)]
    eventos += [ev("apertura_fallida", 100, simbolo="BTCUSD",
                   order={"reason": "El broker no expone el simbolo BTCUSD"})
                for _ in range(3)]
    eventos += [ev("ia_sugerencia", 200) for _ in range(3)]
    eventos += [ev("ia_sugerencia", 201) for _ in range(3)]
    eventos += [ev("rechazada", 300, reasons=["No se pudo identificar el simbolo",
                                              "Falta stop loss (REQUIRE_STOP_LOSS=true)"])
                for _ in range(3)]
    eventos += [ev("ambiguo", 400) for _ in range(3)]
    return eventos


# --------------------------------------------------------------------------
# 1) Todo se cuenta por MENSAJE
# --------------------------------------------------------------------------


def test_el_desglose_suma_los_mensajes_y_no_los_eventos():
    r = resumir(la_salida_real())

    assert r["mensajes"] == 20
    assert r["vistas"] == 30, "el conteo de ediciones tiene que seguir estando"
    assert sum(r["por_tipo"].values()) == 20, "el desglose sigue sumando eventos"
    assert r["por_tipo"] == {
        "aceptada": 15, "apertura_fallida": 1, "ia_sugerencia": 2,
        "rechazada": 1, "ambiguo": 1,
    }


def test_los_motivos_se_cuentan_una_vez_por_mensaje():
    """Una senal rechazada editada tres veces no son tres rechazos."""
    motivos = dict(resumir(la_salida_real())["motivos"])

    assert motivos["No se pudo identificar el simbolo"] == 1
    assert motivos["el broker rechazo: El broker no expone el simbolo BTCUSD"] == 1


def test_una_por_una_tiene_una_fila_por_mensaje_y_dice_cuantas_ediciones():
    detalle = resumir(la_salida_real())["detalle"]

    assert len(detalle) == 20
    btc = [f for f in detalle if f["symbol"] == "BTCUSD"]
    assert len(btc) == 1
    assert btc[0]["ediciones"] == 3


def test_si_una_edicion_se_opero_el_mensaje_se_opero():
    """Rechazada primero (el tope estaba lleno) y operada en una edicion
    posterior: lo que paso con ese mensaje es que se opero."""
    eventos = [ev("rechazada", 7, reasons=["x"]), ev("aceptada", 7), ev("rechazada", 7, reasons=["x"])]

    r = resumir(eventos)

    assert r["por_tipo"] == {"aceptada": 1}
    assert r["motivos"] == []


def test_la_hora_de_la_fila_es_la_del_mensaje_no_la_de_su_ultima_edicion():
    eventos = [ev("ia_sugerencia", 9, hace=5), ev("ia_sugerencia", 9, hace=1)]

    assert resumir(eventos)["detalle"][0]["ts"] == eventos[0]["ts"]


def test_mismo_id_en_otro_chat_es_otro_mensaje():
    a = ev("aceptada", 1)
    b = ev("aceptada", 1)
    b["signal"]["telegram_chat_id"] = -200

    assert resumir([a, b])["mensajes"] == 2


def test_las_distancias_son_una_por_senal():
    senal = {"telegram_message_id": 5, "telegram_chat_id": -100}
    trades = [
        {"ts": AHORA.isoformat(), "symbol": "XAUUSD", "entry": 4274.0,
         "precio_mercado": 4275.04, "signal": senal}
        for _ in range(3)
    ]

    assert len(resumir([], trades)["distancias"]) == 1


def test_sin_id_las_posiciones_de_una_senal_se_juntan_por_sus_precios():
    trades = [{"symbol": "XAUUSD", "entry": 4274.0, "precio_mercado": 4275.04}
              for _ in range(3)]
    trades.append({"symbol": "XAUUSD", "entry": 4281.0, "precio_mercado": 4281.41})

    assert len(resumir([], trades)["distancias"]) == 2


# --------------------------------------------------------------------------
# 2) Fecha, hora local y precios legibles
# --------------------------------------------------------------------------


MEXICO = timezone(timedelta(hours=-6))


def test_la_hora_es_la_de_la_pc_y_trae_la_fecha():
    assert hora_local("2026-09-16T07:46:03+00:00", MEXICO) == "16/09 01:46"


def test_la_fecha_cambia_si_la_hora_local_cae_en_el_dia_anterior():
    assert hora_local("2026-09-16T03:00:00+00:00", MEXICO) == "15/09 21:00"


def test_una_hora_sin_zona_se_toma_como_utc():
    assert hora_local("2026-09-16T07:46:03", MEXICO) == "16/09 01:46"


def test_sin_hora_no_revienta():
    assert hora_local(None) == "--/-- --:--"


@pytest.mark.parametrize("valor, esperado", [
    (4404.844999999999, "4404.845"),
    (4386.0, "4386"),
    (1.08120, "1.0812"),
    (None, "-"),
])
def test_los_precios_se_leen(valor, esperado):
    assert precio(valor) == esperado


# --------------------------------------------------------------------------
# 3) Que TP toco: si se sabe cual perseguia, no se adivina
# --------------------------------------------------------------------------


def test_con_deslizamiento_una_posicion_del_tp1_sigue_siendo_tp1():
    operada = {"entry": 4432.0, "tp_indice": 1, "take_profits": [4436.0, 4438.0, 4440.0]}
    desenlace = {"motivo": "tp", "precio": 4437.2}

    assert clasificar_desenlace(operada, desenlace) == "TP1"


def test_sin_indice_se_sigue_adivinando_por_el_precio():
    """Los eventos viejos no tienen tp_indice: ahi es lo unico que hay."""
    operada = {"entry": 4467.0, "take_profits": [4463.0, 4461.0, 4459.0]}

    assert clasificar_desenlace(operada, {"motivo": "tp", "precio": 4459.0}) == "TP3"


def test_el_motivo_de_max_positions_per_symbol_se_traduce():
    eventos = [ev("rechazada", 1, reasons=[
        "Ya hay 2 posiciones abiertas en XAUUSD (MAX_POSITIONS_PER_SYMBOL=2)"])]

    texto = resumir(eventos)["motivos"][0][0]

    assert "MAX_POSITIONS_PER_SYMBOL" in texto
    assert "Ya hay 2" not in texto, "salio el motivo crudo"


# --------------------------------------------------------------------------
# 4) El neto es neto
# --------------------------------------------------------------------------


def test_el_resumen_separa_bruto_costos_y_neto():
    filas = [
        {"resultado": "TP1", "profit": 3.50, "comision": -0.07, "swap": -1.80, "fee": 0.0, "neto": 1.63},
        {"resultado": "breakeven", "profit": 0.57, "comision": -0.07, "swap": 0.0, "fee": 0.0, "neto": 0.50},
    ]

    r = resumir_desenlaces(filas)

    assert r["bruto_total"] == pytest.approx(4.07)
    assert r["costos_total"] == pytest.approx(-1.94)
    assert r["neto_total"] == pytest.approx(2.13)
    assert r["profit_total"] == pytest.approx(2.13), "profit_total tiene que ser el neto"
    assert r["costos_desconocidos"] == 0


def test_una_fila_sin_dato_de_costos_se_dice():
    r = resumir_desenlaces([{"resultado": "TP1", "profit": 4.0}])

    assert r["neto_total"] == pytest.approx(4.0)
    assert r["costos_desconocidos"] == 1


class Deal:
    def __init__(self, entry, price=0.0, profit=0.0, commission=0.0, swap=0.0, fee=0.0, reason=5):
        self.entry, self.price, self.profit = entry, price, profit
        self.commission, self.swap, self.fee = commission, swap, fee
        self.reason, self.time = reason, 0


def test_mt5_suma_la_comision_del_deal_de_entrada():
    """La comision se cobra casi siempre al ENTRAR, y el deal de entrada es
    justo el que se filtraba para buscar el cierre."""
    from tct.brokers.mt5_native import MT5NativeBroker
    from tests.test_engine import build_settings

    broker = MT5NativeBroker(build_settings(__import__("pathlib").Path(".")))
    broker._mt5 = SimpleNamespace(
        DEAL_ENTRY_OUT=1, DEAL_REASON_TP=5, DEAL_REASON_SL=4,
        DEAL_REASON_CLIENT=0, DEAL_REASON_EXPERT=3,
        history_deals_get=lambda position=None, **_: [
            Deal(0, price=4432.5, commission=-0.035),
            Deal(1, price=4436.0, profit=3.50, commission=-0.035, swap=-1.80),
        ],
    )

    d = broker._desenlace_sync(1)

    assert d["profit"] == pytest.approx(3.50)
    assert d["comision"] == pytest.approx(-0.07)
    assert d["swap"] == pytest.approx(-1.80)
    assert d["neto"] == pytest.approx(1.63)


# --------------------------------------------------------------------------
# 5) Solo lectura de verdad, y sin tracebacks
# --------------------------------------------------------------------------


def test_un_store_de_solo_lectura_no_toca_un_estado_corrupto(tmp_path):
    estado = tmp_path / "state.json"
    estado.write_text('{"open_positions": [', encoding="utf-8")

    Store(tmp_path / "e.jsonl", tmp_path / "p.jsonl", estado, solo_lectura=True)

    assert estado.exists(), "movio el state.json"
    assert not (tmp_path / "state.corrupt.json").exists()


def test_un_store_de_solo_lectura_no_escribe(tmp_path):
    store = Store(tmp_path / "e.jsonl", tmp_path / "p.jsonl", tmp_path / "s.json", solo_lectura=True)

    with pytest.raises(RuntimeError):
        store.append_event("x", {})
    with pytest.raises(RuntimeError):
        store.save_state()


def _env(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\nTELEGRAM_SESSION_NAME=s\n"
        "TELEGRAM_SOURCE_CHATS=-100\nTRADING_MODE=PAPER_ONLY\n"
        f"EVENTS_PATH={tmp_path / 'events.jsonl'}\n"
        f"PAPER_TRADES_PATH={tmp_path / 'paper.jsonl'}\n"
        f"STATE_PATH={tmp_path / 'state.json'}\n",
        encoding="utf-8",
    )
    return env


def test_tct_informe_no_mueve_un_estado_corrupto(tmp_path):
    """El escenario: bot caido despues de un corte de luz, state.json truncado,
    y lo primero que uno corre para diagnosticar es lo que se dijo inofensivo."""
    env = _env(tmp_path)
    (tmp_path / "events.jsonl").write_text(
        json.dumps(ev("aceptada", 1, hace=0)) + "\n", encoding="utf-8")
    (tmp_path / "state.json").write_text('{"open_positions": [', encoding="utf-8")

    cli.main(["--env-file", str(env), "informe", "--horas", "0"])

    assert (tmp_path / "state.json").exists(), "tct informe movio el state.json"


def test_la_salida_de_la_cli_suma_lo_mismo_que_el_titulo(tmp_path, capsys):
    env = _env(tmp_path)
    (tmp_path / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in la_salida_real()), encoding="utf-8")

    cli.main(["--env-file", str(env), "informe", "--horas", "0"])
    salida = capsys.readouterr().out

    assert "Mensajes de apertura distintos: 20" in salida
    assert "15  operadas" in salida
    assert "1  el broker no las pudo abrir" in salida
    assert "(3 ediciones)" in salida
    filas_btc = [l for l in salida.splitlines() if "BTCUSD   BUY" in l]
    assert len(filas_btc) == 1, "una edicion volvio a tener su propia fila"
    assert "1  rechazadas por el riesgo" in salida
    assert "2  solo las entendio la IA" in salida


class BrokerDeHistorial:
    """Un broker que solo sabe contestar como termino cada ticket."""

    def __init__(self, desenlaces):
        self._desenlaces = desenlaces

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def desenlace_de(self, ticket):
        return self._desenlaces.get(ticket)


def test_con_resultados_no_revienta_con_una_senal_sin_entrada(tmp_path, monkeypatch, capsys):
    """Una senal a mercado sin numero ("BUY NOW") se opera igual. Formatearla
    reventaba la seccion ENTERA con un traceback: no se veia como termino
    ninguna de las otras, ni el resultado."""
    from tests.test_engine import build_settings

    sin_entrada = ev("aceptada", 1, order={"ticket": 11})
    sin_entrada["signal"]["entry"] = None
    sin_entrada["signal"]["take_profits"] = [4436.0]
    con_entrada = ev("aceptada", 2, order={"ticket": 22})
    con_entrada["signal"]["take_profits"] = [4390.0]

    monkeypatch.setattr("tct.brokers.base.build_broker", lambda s: BrokerDeHistorial({
        11: {"motivo": "tp", "precio": 4436.0, "profit": 3.0, "neto": 3.0},
        22: {"motivo": "sl", "precio": 4378.0, "profit": -8.0, "neto": -8.07,
             "comision": -0.07, "swap": 0.0, "fee": 0.0},
    }))

    asyncio.run(cli._informar_desenlaces(build_settings(tmp_path), [sin_entrada, con_entrada]))
    salida = capsys.readouterr().out

    assert "entrada=-" in salida
    assert "Resultado neto" in salida, "se corto antes del resumen"
    assert "-5.07" in salida, "el neto no suma las dos"
