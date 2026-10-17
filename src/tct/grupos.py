"""El mismo grupo de Telegram tiene varios nombres, y el bot los tiene que juntar.

Un canal se ve como `-1001666520346` en vivo (Telethon da el id "marcado") y
como `1666520346` en el historial que lee el repaso (el id de la entidad). En el
`.env` el usuario lo escribe como lo mostro `tct chats`: `-1001666520346`. Para
saber de que grupo vino una posicion, y a que grupo le toca un lote, los tres
tienen que ser la misma clave.

Desde el 17/10 un bot puede copiar varios grupos a la vez (la demo de FxPro:
David, Sebastian y XAUUSD TRADING ZONE). Cada posicion recuerda su grupo y la
gestion de un grupo no toca las posiciones de otro.
"""

from __future__ import annotations

from typing import Any


def clave_de_grupo(valor: Any) -> str | None:
    """La forma comparable de un id de chat: solo los digitos del canal.

    `-1001666520346`, `1666520346`, `"-1001666520346 "` y el int de Telethon dan
    `"1666520346"`.
    Un `@nombre` queda en minusculas: no se puede comparar con un id, pero
    tampoco se confunde con uno. None si no hay chat (tests, `tct simular`).
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        numero = int(texto)
    except ValueError:
        return texto.lower()
    # Las reglas de Telethon para "marcar" un id: un canal es
    # -(10**12 + id), un grupo comun es -id, un usuario es id.
    if numero <= -10**12:
        return str(-numero - 10**12)
    return str(abs(numero))
