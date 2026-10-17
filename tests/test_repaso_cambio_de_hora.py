"""`tct repaso` y el cambio de hora del servidor de MT5 (16/10).

FxPro y Bullwaves van en UTC+3 en verano y UTC+2 en invierno, y cambian con
Europa (el 25/10/2026). El repaso media el desfase UNA vez y lo usaba para los
40 dias: si cruzaban el cambio, o si se corria despues sobre fechas de antes,
parte de los mensajes se median contra el precio de una hora antes o despues.
Salian entradas tardias que no eran, y stops o TP que no fueron.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tct.repaso import (HoraDelServidor, PreciosDeMT5, a_ms, desfase_del_servidor,
                        en_verano)
from tests.test_engine import build_settings

H = 3_600_000

# Los cambios de hora de Europa, escritos a mano y no con el codigo que se
# prueba: el ultimo domingo de marzo y el de octubre, a la 01:00 UTC.
CAMBIOS_DE_EUROPA = [a_ms(datetime(*fecha, 1, tzinfo=timezone.utc)) for fecha in [
    (2024, 3, 31), (2024, 10, 27), (2025, 3, 30), (2025, 10, 26), (2026, 3, 29),
    (2026, 10, 25), (2027, 3, 28), (2027, 10, 31), (2028, 3, 26), (2028, 10, 29),
    (2029, 3, 25), (2029, 10, 28), (2030, 3, 31), (2030, 10, 27)]]


def desfase_de_atenas(t_ms: int) -> int:
    """Lo que adelanta un servidor como el de FxPro: UTC+2, y UTC+3 en verano.
    Vale de 2024 a 2030 (el comando entero se prueba con la fecha de hoy)."""
    cambios_pasados = sum(1 for c in CAMBIOS_DE_EUROPA if c <= t_ms)
    return (3 if cambios_pasados % 2 else 2) * H


def utc(*fecha) -> int:
    return a_ms(datetime(*fecha, tzinfo=timezone.utc))


class ServidorDeMT5:
    """Guarda los precios en UTC de verdad y los entrega como MT5: con la hora
    del SERVIDOR contada como si fuera UTC. Anota cada pedido de ticks."""

    DEAL_ENTRY_IN, COPY_TICKS_ALL, TIMEFRAME_M1 = 0, -1, 1

    def __init__(self, ticks=(), velas=(), operaciones=None, desfase=desfase_de_atenas):
        self.desfase = desfase
        self.operaciones = operaciones or {}  # ticket -> ts del registro del bot
        self.pedidos: list[tuple[int, int]] = []
        # Por hora del servidor, para no recorrer todo en cada pedido.
        self._ticks: dict[int, list] = {}
        for t, bid, ask in ticks:
            s = t + desfase(t)
            self._ticks.setdefault(s // H, []).append((s, bid, ask))
        self._velas: dict[int, list] = {}
        for t, *ohlc in velas:
            s = t + desfase(t)
            self._velas.setdefault(s // H, []).append((s, *ohlc))

    def _entre(self, indice, desde, hasta):
        s0, s1 = a_ms(desde), a_ms(hasta)
        return [x for hora in range(s0 // H, s1 // H + 1) for x in indice.get(hora, [])
                if s0 <= x[0] <= s1]

    def copy_ticks_range(self, _simbolo, desde, hasta, _flags):
        self.pedidos.append((a_ms(desde), a_ms(hasta)))
        return [{"time_msc": s, "bid": b, "ask": a}
                for s, b, a in self._entre(self._ticks, desde, hasta)]

    def copy_rates_range(self, _simbolo, _marco, desde, hasta):
        return [{"time": s // 1000, "open": o, "high": h, "low": lo, "close": c, "spread": 20}
                for s, o, h, lo, c in self._entre(self._velas, desde, hasta)]

    def history_deals_get(self, position=None, **_k):
        ts = self.operaciones.get(position)
        if ts is None:
            return []
        t = a_ms(ts)
        return [SimpleNamespace(entry=0, time=(t + self.desfase(t)) // 1000 + 1)]

    def symbol_info_tick(self, _name):
        return None

    # Lo que pide el broker de MT5 para encontrar el simbolo, en el comando entero.
    def symbols_get(self):
        return [SimpleNamespace(name="XAUUSD!")]

    def symbol_info(self, name):
        if name not in ("XAUUSD", "XAUUSD!"):
            return None
        return SimpleNamespace(name=name, visible=True, point=0.01, trade_contract_size=100.0)

    def symbol_select(self, *_a):
        return True

    def account_info(self):
        return SimpleNamespace(balance=500.0)

    def order_send(self, _request):
        raise AssertionError("el repaso mando una orden")


def una_hora_de_ticks(desde_ms: int, precio: float) -> list[tuple[int, float, float]]:
    return [(desde_ms + i * 60_000, precio - 0.1, precio + 0.1) for i in range(60)]


def operacion(ticket: int, ts_ms: int) -> dict:
    """Un "aceptada" del registro del bot, como lo lee el repaso."""
    return {"kind": "aceptada", "ts": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            .isoformat(), "signal": {"symbol": "XAUUSD"}, "order": {"ticket": ticket}}


def servidor_con(*operaciones_del_bot, desfase=desfase_de_atenas):
    return ServidorDeMT5(operaciones={o["order"]["ticket"]: o["ts"] for o in operaciones_del_bot},
                         desfase=desfase)


# --------------------------------------------------------------------------
# Las fechas del cambio de hora
# --------------------------------------------------------------------------


def test_europa_cambia_el_ultimo_domingo_de_marzo_y_de_octubre_a_la_una_utc():
    assert en_verano(utc(2026, 10, 25, 0, 59, 59), "europa")
    assert not en_verano(utc(2026, 10, 25, 1), "europa")
    assert not en_verano(utc(2026, 3, 29, 0, 59, 59), "europa")
    assert en_verano(utc(2026, 3, 29, 1), "europa")


def test_eeuu_cambia_con_nueva_york():
    """El 2do domingo de marzo y el 1ro de noviembre, a las 2 de alla."""
    assert not en_verano(utc(2026, 3, 8, 6, 59, 59), "eeuu")
    assert en_verano(utc(2026, 3, 8, 7), "eeuu")
    assert en_verano(utc(2026, 11, 1, 5, 59, 59), "eeuu")
    assert not en_verano(utc(2026, 11, 1, 6), "eeuu")
    # La semana entre los dos cambios de otono: Europa ya cambio, EE.UU. no.
    semana = utc(2026, 10, 28, 12)
    assert en_verano(semana, "eeuu") and not en_verano(semana, "europa")


def test_hora_por_hora_tres_anios_igual_que_un_servidor_de_atenas():
    hora = HoraDelServidor.medida(3 * H, utc(2026, 10, 14, 9), "europa")

    distintas = [t for t in range(utc(2025, 1, 1), utc(2028, 1, 1), H)
                 if hora.desfase_ms(t) != desfase_de_atenas(t)]

    assert distintas == []


def test_fijo_no_cambia_nunca():
    hora = HoraDelServidor.medida(3 * H, utc(2026, 10, 14, 9), "fijo")

    assert {hora.desfase_ms(t) for t in range(utc(2026, 1, 1), utc(2027, 1, 1), H)} == {3 * H}


# --------------------------------------------------------------------------
# Los precios, segun la fecha
# --------------------------------------------------------------------------


def test_todo_en_verano_da_lo_mismo_que_antes():
    """Septiembre y octubre antes del 25/10: un solo desfase, como siempre."""
    viernes = utc(2026, 9, 18, 10)
    mt5 = ServidorDeMT5(ticks=una_hora_de_ticks(viernes, 4400.0))
    hora = HoraDelServidor.medida(3 * H, utc(2026, 10, 14, 9), "europa")

    nuevos = PreciosDeMT5(mt5, "XAUUSD!", hora).ticks(viernes, viernes + H - 1)
    pedido = mt5.pedidos[-1]
    de_antes = PreciosDeMT5(mt5, "XAUUSD!", HoraDelServidor(3 * H)).ticks(viernes, viernes + H - 1)

    assert pedido == (viernes + 3 * H, viernes + 4 * H)
    assert nuevos == de_antes == una_hora_de_ticks(viernes, 4400.0)
    assert hora.describir(utc(2026, 9, 6), utc(2026, 10, 16)) == "UTC+3 en todo el repaso"


def test_una_ventana_que_cruza_el_25_10():
    viernes, martes = utc(2026, 10, 23, 10), utc(2026, 10, 27, 10)
    mt5 = ServidorDeMT5(ticks=una_hora_de_ticks(viernes, 4400.0)
                        + una_hora_de_ticks(martes, 4300.0))
    hora = HoraDelServidor.medida(3 * H, utc(2026, 10, 14, 9), "europa")
    precios = PreciosDeMT5(mt5, "XAUUSD!", hora)

    assert precios.ticks(viernes, viernes + H - 1) == una_hora_de_ticks(viernes, 4400.0)
    assert mt5.pedidos[-1][0] == viernes + 3 * H
    assert precios.ticks(martes, martes + H - 1) == una_hora_de_ticks(martes, 4300.0)
    assert mt5.pedidos[-1][0] == martes + 2 * H
    assert (hora.describir(utc(2026, 9, 20), utc(2026, 10, 30))
            == "UTC+3 hasta 25/10, UTC+2 desde 25/10")

    # Con un solo desfase (lo de antes), el martes se leia una hora corrido.
    de_antes = PreciosDeMT5(mt5, "XAUUSD!", HoraDelServidor(3 * H)).ticks(martes, martes + H - 1)
    assert de_antes != una_hora_de_ticks(martes, 4300.0)


def test_las_velas_de_un_minuto_tambien_usan_el_desfase_de_su_fecha():
    """Sin ticks en el historial, se arman con velas de 1 minuto."""
    viernes, martes = utc(2026, 10, 23, 10), utc(2026, 10, 27, 10)
    velas = [(t, 4400.0, 4401.0, 4399.0, 4400.5) for t in (viernes, martes)]
    precios = PreciosDeMT5(ServidorDeMT5(velas=velas), "XAUUSD!",
                           HoraDelServidor.medida(3 * H, utc(2026, 10, 14, 9), "europa"))

    assert precios.ticks(viernes, viernes + H - 1)[0][0] == viernes
    assert precios.ticks(martes, martes + H - 1)[0][0] == martes
    assert precios.horas_con_velas == 2


def test_eeuu_cambia_una_semana_despues():
    hora = HoraDelServidor.medida(3 * H, utc(2026, 10, 14, 9), "eeuu")

    assert hora.desfase_ms(utc(2026, 10, 28, 12)) == 3 * H
    assert hora.desfase_ms(utc(2026, 11, 2, 12)) == 2 * H
    assert (hora.describir(utc(2026, 10, 1), utc(2026, 11, 5))
            == "UTC+3 hasta 01/11, UTC+2 desde 01/11")


def test_una_ventana_larga_dice_cada_tramo_con_el_anio():
    hora = HoraDelServidor.medida(3 * H, utc(2026, 10, 14, 9), "europa")

    assert hora.describir(utc(2025, 10, 1), utc(2026, 10, 16)) == (
        "UTC+3 hasta 26/10/2025, UTC+2 del 26/10/2025 al 29/03/2026, UTC+3 desde 29/03/2026")


# --------------------------------------------------------------------------
# La medicion
# --------------------------------------------------------------------------


def test_medido_en_invierno_para_mensajes_de_verano():
    """El repaso corrido en noviembre con la ultima operacion del bot del
    28/10 (UTC+2): los mensajes de septiembre son de UTC+3."""
    mt5 = servidor_con(operacion(77, utc(2026, 10, 28, 10)))

    hora, como, supuesto = desfase_del_servidor(
        mt5, "XAUUSD!", [operacion(77, utc(2026, 10, 28, 10))], utc(2026, 11, 3) / 1000)

    assert como == "UTC+2 el 28/10 (medido con una operacion del bot)"
    assert "Se supone que cambia con el horario de verano de Europa" in supuesto
    assert "--horario fijo" in supuesto
    assert hora.desfase_ms(utc(2026, 9, 18, 10)) == 3 * H
    assert hora.desfase_ms(utc(2026, 11, 2, 10)) == 2 * H
    assert (hora.describir(utc(2026, 9, 24), utc(2026, 11, 3))
            == "UTC+3 hasta 25/10, UTC+2 desde 25/10")


def test_otra_operacion_del_otro_lado_del_cambio_lo_confirma():
    eventos = [operacion(70, utc(2026, 10, 20, 10)), operacion(77, utc(2026, 10, 28, 10))]

    hora, como, supuesto = desfase_del_servidor(servidor_con(*eventos), "XAUUSD!", eventos,
                                                utc(2026, 11, 3) / 1000)

    assert como.startswith("UTC+2 el 28/10")
    assert supuesto == ("Otra operacion, del 20/10, dio UTC+3: "
                        "cambia con el horario de verano de Europa")
    assert hora.desfase_ms(utc(2026, 10, 20, 10)) == 3 * H


def test_un_servidor_que_no_cambia_de_hora_se_nota_y_no_se_corrige():
    eventos = [operacion(70, utc(2026, 10, 20, 10)), operacion(77, utc(2026, 10, 28, 10))]
    mt5 = servidor_con(*eventos, desfase=lambda _t: 0)

    hora, como, supuesto = desfase_del_servidor(mt5, "XAUUSD!", eventos, utc(2026, 11, 3) / 1000)

    assert como.startswith("UTC+0 el 28/10")
    assert "tambien dio UTC+0: este servidor no cambia de hora" in supuesto
    assert hora.regla == "fijo"
    assert hora.desfase_ms(utc(2026, 9, 18, 10)) == 0


def test_utc_0_en_verano_no_es_un_servidor_que_cambie_con_europa():
    """El contexto dice en un lugar que Bullwaves va en UTC+0. Medido hoy (en
    verano) sin otra operacion de invierno: no se inventa un UTC-1."""
    eventos = [operacion(77, utc(2026, 10, 14, 10))]
    mt5 = servidor_con(*eventos, desfase=lambda _t: 0)

    hora, _como, supuesto = desfase_del_servidor(mt5, "XAUUSD!", eventos, utc(2026, 11, 3) / 1000)

    assert hora.regla == "fijo"
    assert hora.desfase_ms(utc(2026, 11, 2, 10)) == 0
    assert supuesto.startswith("UTC+0 en verano no es la hora de un servidor que cambie con Europa")


def test_utc_3_en_invierno_tampoco():
    eventos = [operacion(77, utc(2026, 11, 2, 10))]
    mt5 = servidor_con(*eventos, desfase=lambda _t: 3 * H)

    hora, _como, supuesto = desfase_del_servidor(mt5, "XAUUSD!", eventos, utc(2026, 11, 3) / 1000)

    assert hora.desfase_ms(utc(2026, 9, 18, 10)) == 3 * H
    assert "UTC+3 en invierno no es la hora" in supuesto


def test_con_horario_fijo_se_usa_lo_medido_para_todo():
    """Para un broker que no cambia de hora: `--horario fijo`."""
    eventos = [operacion(77, utc(2026, 10, 28, 10))]

    hora, _como, supuesto = desfase_del_servidor(servidor_con(*eventos), "XAUUSD!", eventos,
                                                 utc(2026, 11, 3) / 1000, "fijo")

    assert supuesto == "Sin cambio de horario (--horario fijo)"
    assert hora.desfase_ms(utc(2026, 9, 18, 10)) == 2 * H
    assert hora.describir(utc(2026, 9, 24), utc(2026, 11, 3)) == "UTC+2 en todo el repaso"


def test_medido_con_el_ultimo_precio_tambien_se_corrige():
    """Sin operaciones del bot: el ultimo tick, que es de hoy."""
    ahora = utc(2026, 11, 3, 10)
    mt5 = ServidorDeMT5()
    mt5.symbol_info_tick = lambda _n: SimpleNamespace(time=(ahora + 2 * H) // 1000)

    hora, como, _ = desfase_del_servidor(mt5, "XAUUSD!", [], ahora / 1000)

    assert como == "UTC+2 (medido con el ultimo precio)"
    assert hora.desfase_ms(utc(2026, 10, 1, 10)) == 3 * H


# --------------------------------------------------------------------------
# El comando entero, a caballo del cambio de 2025
# --------------------------------------------------------------------------


def precios_alrededor_de(dia_ms: int) -> list[tuple[int, float, float]]:
    """A las 10:00 UTC el oro esta en 4100 y sube a 4110; una hora antes
    estaba en 4150. Una senal de las 10:00 leida con una hora de error queda
    lejos del precio y no se abre."""
    ticks = []
    for i in range(0, 4 * 3600, 10):
        t = dia_ms + 8 * H + i * 1000
        if t < dia_ms + 10 * H:
            medio = 4150.0
        else:
            medio = min(4100.0 + (t - dia_ms - 10 * H) / 180_000, 4110.0)
        ticks.append((t, round(medio - 0.1, 2), round(medio + 0.1, 2)))
    return ticks


def correr_el_comando(tmp_path, monkeypatch, horario):
    from tct import cli
    from tct.brokers.mt5_native import MT5NativeBroker

    viernes, martes = utc(2025, 10, 24), utc(2025, 10, 28)
    settings = build_settings(tmp_path, default_lot=0.05, max_spread_from_entry_pct=0.05,
                              allowed_symbols={"XAUUSD"})
    # La ultima operacion del bot, del martes: se mide en invierno (UTC+2).
    ts_del_bot = datetime.fromtimestamp((martes + 12 * H) / 1000, tz=timezone.utc).isoformat()
    settings.events_path.parent.mkdir(parents=True, exist_ok=True)
    settings.events_path.write_text(json.dumps({"ts": ts_del_bot, "kind": "aceptada",
                                                "signal": {"symbol": "XAUUSD"},
                                                "order": {"ticket": 77}}) + "\n", encoding="utf-8")
    terminal = ServidorDeMT5(ticks=precios_alrededor_de(viernes) + precios_alrededor_de(martes),
                             operaciones={77: ts_del_bot})

    async def conectar(self):
        self._mt5, self._ready, self._symbol_cache = terminal, True, {}
        return True

    async def desconectar(self):
        pass

    async def historia(_settings, _dias):
        return [("XAUUSD BUY 4100\nSL 4090\nTP 4105",
                 {"message_id": i, "chat_id": 1, "is_edit": False,
                  "date": datetime.fromtimestamp((dia + 10 * H + 30_000) / 1000, tz=timezone.utc)
                  .isoformat()})
                for i, dia in enumerate([viernes, martes])]

    monkeypatch.setattr(MT5NativeBroker, "connect", conectar)
    monkeypatch.setattr(MT5NativeBroker, "disconnect", desconectar)
    monkeypatch.setattr("tct.telegram.reader.fetch_history", historia)
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr("tct.repaso.time.sleep", lambda _s: None)
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(env_file=".env.real", verbose=False, dias=400, lotes="0.05",
                              detalle=False)
    if horario:
        args.horario = horario
    return cli.cmd_repaso(args)


def test_el_comando_usa_el_desfase_de_cada_fecha_y_lo_dice(tmp_path, monkeypatch, capsys):
    codigo = correr_el_comando(tmp_path, monkeypatch, None)

    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "Hora del servidor de MT5: UTC+2 el 28/10 (medido con una operacion del bot)." in salida
    assert "Se supone que cambia con el horario de verano de Europa" in salida
    assert ("En las fechas de estos mensajes: UTC+3 hasta 26/10/2025, "
            "UTC+2 del 26/10/2025 al 29/03/2026") in salida
    assert "2 senales operadas, 0 que el bot no habria abierto" in salida
    assert "Ganadas      : 2 de 2" in salida


def test_con_un_solo_desfase_la_senal_de_antes_del_cambio_salia_mal(tmp_path, monkeypatch, capsys):
    """Lo de antes, con `--horario fijo`: la del viernes se media contra el
    precio de una hora antes y el filtro de entrada tardia la rechazaba."""
    codigo = correr_el_comando(tmp_path, monkeypatch, "fijo")

    salida = capsys.readouterr().out
    assert codigo == 0, salida
    assert "En las fechas de estos mensajes: UTC+2 en todo el repaso." in salida
    assert "1 senales operadas, 1 que el bot no habria abierto" in salida


def test_la_opcion_existe_en_la_linea_de_comandos():
    from tct import cli

    assert cli.build_parser().parse_args(["repaso"]).horario == "europa"
    assert cli.build_parser().parse_args(["repaso", "--horario", "fijo"]).horario == "fijo"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["repaso", "--horario", "marte"])


def test_varios_grupos_usan_el_mismo_horario(monkeypatch, tmp_path):
    from tct import cli

    settings = build_settings(tmp_path)
    vistos = []

    async def repaso_falso(ajustes, dias, lotes, detalle, resumen=None, horario="europa"):
        vistos.append(horario)
        return 0

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr(cli, "_repaso_async", repaso_falso)
    monkeypatch.chdir(tmp_path)
    cli.cmd_repaso(argparse.Namespace(env_file=".env.segunda", verbose=False, dias=40,
                                      lotes="0.03", detalle=False, chat="-1001,-1002",
                                      horario="eeuu"))

    assert vistos == ["eeuu", "eeuu"]
