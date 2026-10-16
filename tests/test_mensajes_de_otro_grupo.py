"""`tct mensajes`: ver como escribe un grupo, y que entiende el bot, sin copiar a mano.

16/10: para decidir si vale la pena ensenarle al bot a leer 7 grupos que no
entendia, habia que mirar sus mensajes. Solo lee, con la sesion del repaso, y
marca las senales que vienen como imagen (el bot solo lee texto).
"""

from __future__ import annotations

import argparse

from tct import cli
from tct.telegram import reader
from tests.test_engine import build_settings

GRUPOS = [
    {"chat": "-1001", "titulo": "Gold Signals 98% Sure", "error": None, "mensajes": [
        {"fecha": "2026-10-15T09:00:00+00:00", "adjunto": "none", "editado": False,
         "texto": "XAUUSD SELL 4175\nSL 4185\nTP 4170"},
        {"fecha": "2026-10-15T09:05:00+00:00", "adjunto": "photo", "editado": False,
         "texto": ""},
        {"fecha": "2026-10-15T09:30:00+00:00", "adjunto": "none", "editado": True,
         "texto": "Buenos dias familia"},
    ]},
    {"chat": "-1002", "titulo": None, "error": "No user has \"x\" as username",
     "mensajes": []},
]


def correr(monkeypatch, tmp_path, chat="-1001,-1002"):
    settings = build_settings(tmp_path)
    pedidos = {}

    async def ultimos_falso(ajustes, chats, cantidad):
        pedidos.update(chats=chats, cantidad=cantidad)
        return GRUPOS

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr(reader, "ultimos_mensajes", ultimos_falso)
    monkeypatch.chdir(tmp_path)
    codigo = cli.cmd_mensajes(argparse.Namespace(env_file=".env.segunda", verbose=False,
                                                 chat=chat, cantidad=40))
    return codigo, pedidos


def test_muestra_cada_mensaje_y_lo_que_entiende_el_bot(monkeypatch, tmp_path, capsys):
    codigo, pedidos = correr(monkeypatch, tmp_path)

    salida = capsys.readouterr().out
    assert codigo == 0
    assert pedidos == {"chats": ["-1001", "-1002"], "cantidad": 40}
    assert "| XAUUSD SELL 4175" in salida
    assert "apertura XAUUSD SELL entrada 4175  SL 4185  TP 4170" in salida
    assert "[imagen]" in salida and "(sin texto)" in salida
    assert "-> el bot: no es una senal" in salida
    assert "1 que el bot lee como apertura, 0 de gestion, 1 solo imagen" in salida
    assert "No se pudo leer este grupo" in salida


def test_todo_queda_en_un_archivo(monkeypatch, tmp_path):
    correr(monkeypatch, tmp_path)

    guardados = list(tmp_path.glob("mensajes_*.txt"))
    assert len(guardados) == 1
    assert "XAUUSD SELL 4175" in guardados[0].read_text(encoding="utf-8")


def test_sin_chat_explica_que_falta(monkeypatch, tmp_path, capsys):
    codigo, _ = correr(monkeypatch, tmp_path, chat=None)

    assert codigo == 1
    assert "Falta --chat" in capsys.readouterr().out


def test_el_comando_existe():
    args = cli.build_parser().parse_args(
        ["mensajes", "--env-file", ".env.segunda", "--chat=-1001,-1002", "--cantidad", "60"])

    assert (args.chat, args.cantidad) == ("-1001,-1002", 60)
