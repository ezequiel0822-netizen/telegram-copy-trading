"""El repaso de un grupo al que la cuenta se unio hace poco (17/10).

El repaso de Academia de Trading Genesis dijo "No llego ningun mensaje de ese
rango" y nada mas. La cuenta del repaso no podia abrir el canal por numero: un
canal recien unido no esta en el cache de la sesion hasta que se recorren los
chats de la cuenta (lo que hace `tct chats`), o la cuenta no estaba unida. El
motivo quedaba solo en el log, no en la salida ni en el archivo.
"""

from __future__ import annotations

import asyncio
import types

from tct.telegram import reader


class Cliente:
    """Un TelegramClient que encuentra el canal solo despues de get_dialogs."""

    def __init__(self, *_a, conoce_despues_de_dialogos=True, **_k):
        self.dialogos = False
        self.conoce = conoce_despues_de_dialogos
        self.pedidos = []

    async def get_entity(self, candidato):
        self.pedidos.append(candidato)
        if self.dialogos and self.conoce:
            return types.SimpleNamespace(id=1666520346, title="Canal")
        raise ValueError(f"Could not find the input entity for PeerChannel({candidato})")

    async def get_dialogs(self):
        self.dialogos = True

    def iter_messages(self, _entidad, limit=None):
        async def nada():
            return
            yield  # noqa: B901 - generador async vacio
        return nada()

    async def disconnect(self):
        pass


def test_un_canal_recien_unido_se_abre_despues_de_recorrer_los_chats():
    cliente = Cliente()

    entidad = asyncio.run(reader._abrir_el_chat(cliente, "-1001666520346"))

    assert entidad.title == "Canal"
    assert cliente.pedidos == [-1001666520346, -1001666520346]


def test_si_igual_no_se_puede_devuelve_el_motivo():
    cliente = Cliente(conoce_despues_de_dialogos=False)

    resultado = asyncio.run(reader._abrir_el_chat(cliente, "-1003729772063"))

    assert isinstance(resultado, Exception)


def test_el_repaso_dice_por_que_no_llego_nada(monkeypatch, capsys):
    import telethon

    monkeypatch.setattr(telethon, "TelegramClient",
                        lambda *a, **k: Cliente(conoce_despues_de_dialogos=False))

    async def entrar(_cliente, intentos=3):
        return None
    monkeypatch.setattr(reader, "_entrar", entrar)
    settings = types.SimpleNamespace(telegram_session_name="s", telegram_api_id=1,
                                     telegram_api_hash="h",
                                     telegram_source_chats=["-1003729772063"])

    mensajes = asyncio.run(reader.fetch_history(settings, 40))

    assert mensajes == []
    salida = capsys.readouterr().out
    assert "No se pudo abrir el grupo -1003729772063" in salida
    assert "tct chats --repaso" in salida
