"""`tct repaso --chat`: medir otro grupo antes de conectarlo a un bot (16/10).

Y el telefono mal escrito: el 16/10 se escribio sin el codigo de pais, y
Telethon corto con un error en ingles y treinta lineas de traceback.
"""

from __future__ import annotations

import argparse
import asyncio

import pytest
from telethon.errors import PhoneNumberInvalidError

from tct import cli
from tct.telegram import reader
from tests.test_engine import build_settings


def correr_repaso(monkeypatch, tmp_path, chat):
    settings = build_settings(tmp_path, telegram_source_chats=["-1004363872187"])
    visto = {}

    async def repaso_falso(ajustes, dias, lotes, detalle):
        visto["chats"] = ajustes.telegram_source_chats
        visto["sesion"] = ajustes.telegram_session_name
        return 0

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr(cli, "_repaso_async", repaso_falso)
    codigo = cli.cmd_repaso(argparse.Namespace(
        env_file=".env.segunda", verbose=False, dias=40, lotes="0.03",
        detalle=False, chat=chat))
    return codigo, visto, settings


def test_con_chat_mide_ese_grupo_y_no_el_del_env(monkeypatch, tmp_path):
    codigo, visto, settings = correr_repaso(monkeypatch, tmp_path, "-1001234567890")

    assert codigo == 0
    assert visto["chats"] == ["-1001234567890"]
    assert settings.telegram_source_chats == ["-1004363872187"], "toco el del .env"


def test_sin_chat_sigue_con_el_del_env(monkeypatch, tmp_path):
    _, visto, _ = correr_repaso(monkeypatch, tmp_path, None)

    assert visto["chats"] == ["-1004363872187"]


def test_la_opcion_existe_en_la_linea_de_comandos():
    args = cli.build_parser().parse_args(
        ["repaso", "--env-file", ".env.segunda", "--chat", "-1001234567890"])

    assert args.chat == "-1001234567890"


class ClienteFalso:
    def __init__(self, rechazos):
        self.rechazos = rechazos
        self.intentos = 0
        self.desconectado = False

    async def start(self, phone):
        self.intentos += 1
        if self.intentos <= self.rechazos:
            raise PhoneNumberInvalidError(None)

    async def disconnect(self):
        self.desconectado = True


def test_un_telefono_mal_escrito_se_explica_y_se_vuelve_a_pedir(capsys):
    cliente = ClienteFalso(rechazos=1)

    asyncio.run(reader._entrar(cliente))

    assert cliente.intentos == 2
    assert "codigo de" in capsys.readouterr().out


def test_despues_de_tres_intentos_corta_con_un_mensaje_claro(capsys):
    cliente = ClienteFalso(rechazos=5)

    with pytest.raises(reader.TelefonoInvalido):
        asyncio.run(reader._entrar(cliente))

    assert cliente.intentos == 3
    assert cliente.desconectado


def correr_chats(monkeypatch, tmp_path, repaso):
    settings = build_settings(tmp_path, telegram_session_name="tct_fxpro")
    visto = {}

    async def chats_falso(ajustes, limit):
        visto["sesion"] = ajustes.telegram_session_name
        return [{"id": -1001234567890, "type": "grupo", "title": "Otro grupo"}]

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr("tct.telegram.reader.list_available_chats", chats_falso)
    codigo = cli.cmd_chats(argparse.Namespace(env_file=".env.segunda", verbose=False,
                                              limit=60, repaso=repaso))
    return codigo, visto


def test_chats_con_repaso_entra_con_la_sesion_del_repaso(monkeypatch, tmp_path):
    """La otra cuenta de Telegram, la que esta en los grupos a medir: un solo
    login sirve para listar los grupos y para el repaso."""
    codigo, visto = correr_chats(monkeypatch, tmp_path, True)

    assert codigo == 0
    assert visto["sesion"] == "tct_fxpro_repaso"


def test_chats_sin_repaso_sigue_con_la_sesion_del_bot(monkeypatch, tmp_path):
    _, visto = correr_chats(monkeypatch, tmp_path, False)

    assert visto["sesion"] == "tct_fxpro"


def test_varios_grupos_se_miden_cada_uno_por_separado(monkeypatch, tmp_path, capsys):
    """Juntos en un motor, el 'cerrar' de un grupo tocaria las posiciones de
    otro. Eran 16 grupos para comparar (16/10)."""
    settings = build_settings(tmp_path, telegram_source_chats=["-1004363872187"])
    medidos = []

    async def repaso_falso(ajustes, dias, lotes, detalle, resumen=None):
        medidos.append(list(ajustes.telegram_source_chats))
        chat = ajustes.telegram_source_chats[0]
        if chat == "-1003":
            return 1  # un grupo sin mensajes no corta los demas
        bueno = chat == "-1001"
        resumen.update(
            titulo=f"Grupo {chat}", mensajes=300, operadas=60, no_abiertas=5,
            cerradas=60, ganadas=45 if bueno else 30, perdidas=15 if bueno else 30,
            breakeven=0, pct_ganadas=75.0 if bueno else 50.0, pct_equilibrio=60.0,
            peor_racha=3 if bueno else 7,
            por_lote=[{"lote": 0.03, "total": 120.0 if bueno else -90.0, "peor_caida": 40.0}])
        return 0

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr(cli, "_repaso_async", repaso_falso)
    monkeypatch.chdir(tmp_path)
    codigo = cli.cmd_repaso(argparse.Namespace(
        env_file=".env.segunda", verbose=False, dias=40, lotes="0.03",
        detalle=False, chat="-1002,-1001,-1003"))

    salida = capsys.readouterr().out
    assert codigo == 0
    assert medidos == [["-1002"], ["-1001"], ["-1003"]]
    tabla = salida.split("TODOS LOS GRUPOS")[1]
    assert tabla.index("Grupo -1001") < tabla.index("Grupo -1002"), "no ordeno del mejor al peor"
    assert "+15" in tabla and "-10" in tabla      # margen: 75-60 y 50-60
    assert "-1003" in tabla and "no se pudo leer el grupo" in tabla

    # La consola no deja copiar tanto: la tabla queda tambien en un archivo.
    guardada = list(tmp_path.glob("repaso_grupos_*.txt"))
    assert len(guardada) == 1
    assert "Grupo -1001" in guardada[0].read_text(encoding="utf-8")


def test_el_detalle_muestra_el_mensaje_y_lo_que_entendio():
    from tct.signals.parser import parse_signal

    senal = parse_signal("DEAL | GOLD (XAU/USD) BUY XAUUSD 4432 Parameters: TP1: 4436 "
                         "TP2: 4438 TP3: 4440 SL: 4424")

    mensaje, entendio = cli._mensaje_y_lo_que_entendio(senal)

    assert "DEAL | GOLD" in mensaje
    assert "XAUUSD BUY entrada 4432" in entendio
    assert "SL 4424" in entendio and "TP 4436 / 4438 / 4440" in entendio


def test_con_varios_simbolos_cada_posicion_usa_su_contrato():
    """16/10: con .env.segunda (12 simbolos) el umbral salia del contrato de
    AUDUSD, 100.000, y todo contaba como breakeven: 0% ganadas en los 16."""
    from types import SimpleNamespace

    from tct.repaso import resumir

    def fila(simbolo, entrada, resultado, cerrada_ms):
        pos = SimpleNamespace(simbolo=simbolo, lote=0.05, entrada=entrada,
                              resultado=resultado, cerrada={"cerrada_ms": cerrada_ms})
        return {"posicion": pos}

    filas = [fila("XAUUSD", 4400.0, 20.0, 1), fila("XAUUSD", 4400.0, -40.0, 2),
             fila("EURUSD", 1.08, 15.0, 3), fila("XAUUSD", 4400.0, 0.4, 4)]

    r = resumir(filas, lote=0.05, lotes=[0.03], contrato=100000.0,
                contratos={"XAUUSD": 100.0, "EURUSD": 100000.0})

    assert (r["ganadas"], r["perdidas"], r["breakeven"]) == (2, 1, 1)
    assert r["peor_racha"] == 1


def test_todo_el_repaso_queda_en_un_archivo(monkeypatch, tmp_path):
    """El detalle son cientos de lineas: la consola no deja copiarlo (16/10)."""
    settings = build_settings(tmp_path)

    async def repaso_falso(ajustes, dias, lotes, detalle, resumen=None):
        print("        mensaje : XAUUSD BUY 2650 SL 2640 TP 2660 \U0001F680")
        return 0

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr(cli, "_repaso_async", repaso_falso)
    monkeypatch.chdir(tmp_path)
    cli.cmd_repaso(argparse.Namespace(env_file=".env.segunda", verbose=False, dias=40,
                                      lotes="0.03", detalle=True, chat="-1001666520346"))

    guardados = [p for p in tmp_path.glob("repaso_*.txt") if "grupos" not in p.name]
    assert len(guardados) == 1
    assert "XAUUSD BUY 2650" in guardados[0].read_text(encoding="utf-8")
