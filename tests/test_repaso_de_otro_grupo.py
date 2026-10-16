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


def test_varios_grupos_separados_por_coma(monkeypatch, tmp_path):
    _, visto, _ = correr_repaso(monkeypatch, tmp_path, "-1001, @senalesoro")

    assert visto["chats"] == ["-1001", "@senalesoro"]


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
