"""Interprete de respaldo con IA local (Ollama).

CUANDO SE USA
-------------
Solo cuando el parser de reglas (`signals/parser.py`) NO entendio un mensaje.
El parser es rapido, gratis y determinista: si el grupo escribe con un formato
reconocible, la IA nunca se entera. Esto es el ultimo recurso para el mensaje
raro, no el camino principal.

POR QUE NO OPERA SOLA
---------------------
Por defecto (`OLLAMA_AUTO_EXECUTE=false`) lo que interpreta la IA se avisa por
Telegram y ahi termina: no abre ninguna operacion. La razon es concreta y no
es prudencia decorativa: las validaciones de `risk.py` verifican que un precio
sea coherente, NO que sea el precio correcto. Si el modelo lee 2345 donde
decia 2355, la senal pasa todos los controles y opera con un numero inventado.
Perderse una senal es barato; operar una equivocada, no.

GUARDA CONTRA ALUCINACIONES
---------------------------
Ademas del schema, todo numero que el modelo devuelve se verifica contra el
texto original: si el precio no aparece literalmente en el mensaje, se
descarta la interpretacion entera. Un modelo puede inventar un numero
plausible, pero no puede hacer que aparezca en un texto que ya existe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from tct.signals.models import EventType, OrderType, SignalEvent, Side

logger = logging.getLogger(__name__)

# Schema que Ollama fuerza sobre la salida del modelo. Con esto la respuesta
# es SIEMPRE un JSON valido con estas claves; lo que no garantiza es que los
# valores sean correctos, de ahi la verificacion posterior.
RESPUESTA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "es_senal": {"type": "boolean"},
        "tipo": {
            "type": "string",
            "enum": ["ABRIR", "CERRAR", "CIERRE_PARCIAL", "MOVER_SL", "NINGUNO"],
        },
        "simbolo": {"type": "string"},
        "direccion": {"type": "string", "enum": ["BUY", "SELL", ""]},
        "entrada": {"type": "string"},
        "stop_loss": {"type": "string"},
        "take_profits": {"type": "array", "items": {"type": "string"}},
        "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
        "razon": {"type": "string"},
    },
    # TODOS los campos van en `required`, incluso los que pueden venir vacios.
    # Ollama convierte este schema en una gramatica, y lo que no es obligatorio
    # el modelo simplemente no lo genera: con solo las 4 claves basicas aca,
    # un modelo de 3B devolvia es_senal/tipo/confianza/razon y omitia entero el
    # simbolo y los precios. Marcarlos obligatorios lo fuerza a completarlos
    # (con "" cuando no sabe, que es lo que pide el prompt).
    "required": [
        "es_senal", "tipo", "simbolo", "direccion",
        "entrada", "stop_loss", "take_profits", "confianza", "razon",
    ],
}

# Los numeros se piden como texto a proposito: los modelos chicos redondean o
# reformatean los flotantes ("1.2650" -> 1.265), y necesitamos la cadena tal
# cual para poder buscarla en el mensaje original.

PROMPT = """Sos un extractor de datos de senales de trading. Tu unica tarea es
leer el mensaje y devolver lo que dice, sin interpretarlo ni completarlo.

REGLAS ESTRICTAS:
- NO inventes ningun numero. Si un dato no esta en el mensaje, deja el campo vacio ("").
- Copia los numeros EXACTAMENTE como aparecen, con sus puntos y comas.
- Si el mensaje no es una senal de trading (charla, saludos, imagenes, promociones),
  responde es_senal=false y tipo="NINGUNO".
- "confianza" es que tan claro esta el mensaje: "alta" si es inequivoco,
  "baja" si estas adivinando.
- En "razon", explica en una linea corta y en castellano que entendiste.

TIPOS:
- ABRIR: pide abrir una operacion nueva.
- CERRAR: pide cerrar una operacion entera.
- CIERRE_PARCIAL: pide cerrar una parte ("close half", "cerrar 50%").
- MOVER_SL: pide mover el stop loss (incluye "a breakeven" / "a BE").
- NINGUNO: no es una senal.

MENSAJE:
---
{mensaje}
---
"""

# Vocabulario minimo para no molestar al modelo con charla. Un mensaje tiene
# que traer al menos un numero Y algo de esto para que valga la pena gastar
# CPU en el.
#
# Los verbos van con sufijo abierto (\w*) a proposito: esta capa existe
# justamente para los mensajes mal escritos, y en un grupo real se lee
# "cierren", "cerramos", "compren", "vendan" mucho mas seguido que el
# infinitivo prolijo. Un \b al final se perderia todas esas formas.
_VOCABULARIO = re.compile(
    r"\b(?:"
    r"BUY|SELL|LONG|SHORT|"
    r"COMPR\w*|VEND\w*|CIERR\w*|CERR\w*|CLOS\w*|ABR\w*|SAL[IG]\w*|"
    r"TPS?|SL|TAKE\s*PROFIT|STOP|TARGET\w*|OBJETIVO\w*|"
    r"ENTR\w*|PRECIO|PRICE|PIPS?|LOTES?|BREAK\s*EVEN|BREAKEVEN|"
    r"GOLD|ORO|PLATA|SILVER|NASDAQ|DAX|BITCOIN|PETROLEO|OIL"
    r")\b",
    re.IGNORECASE,
)

# Un mensaje enorme casi nunca es una senal, y ademas satura el contexto de un
# modelo chico. Se corta antes de gastar tiempo en el.
MAX_CARACTERES = 1200


def vale_la_pena_consultar(mensaje: str) -> bool:
    """Filtro barato previo a molestar al modelo.

    Sin esto, en un grupo activo la IA se despertaria con cada "gracias
    maestro", gastando CPU y llenando de avisos inutiles.

    Esta deliberadamente sesgado a dejar pasar de mas: es un tamiz, no un
    clasificador. Un falso positivo ("a que hora ABRE el mercado? 9am") cuesta
    unos segundos de CPU en una maquina dedicada y termina en el modelo
    diciendo es_senal=false. Un falso negativo pierde una senal para siempre,
    que es justamente lo que esta capa vino a evitar. Quien clasifica de
    verdad es el modelo, y quien protege es la verificacion de numeros.
    """
    if not mensaje or len(mensaje) > MAX_CARACTERES:
        return False
    if not re.search(r"\d", mensaje):
        return False
    if _VOCABULARIO.search(mensaje):
        return True

    # Nombrar un instrumento tambien alcanza, aunque no haya ningun verbo.
    # Se reutiliza el detector del parser de reglas para no mantener dos
    # listas de simbolos que se desincronicen: ahi ya estan los alias (GOLD,
    # NAS, DOW...) y los pares pegados tipo EURUSD, que un \b no agarraria.
    from tct.signals.parser import _extract_symbol

    return _extract_symbol(mensaje.upper()) is not None


class OllamaParser:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout_seconds
        self._aviso_dado = False

    # -- Disponibilidad ----------------------------------------------------

    async def disponible(self) -> tuple[bool, str]:
        """Chequea que Ollama responda y que el modelo este descargado."""
        return await asyncio.to_thread(self._disponible_sync)

    def _disponible_sync(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            return False, (
                f"Ollama no responde en {self.url} ({type(exc).__name__}). "
                "Verifica que este corriendo: ollama serve"
            )

        modelos = [m.get("name", "") for m in datos.get("models", [])]
        if not modelos:
            return False, f"Ollama corre pero no tiene ningun modelo. Instala: ollama pull {self.model}"

        # Ollama lista "qwen2.5:7b"; se acepta tambien que el usuario haya
        # escrito solo "qwen2.5" en el .env.
        base = self.model.split(":")[0]
        if not any(m == self.model or m.split(":")[0] == base for m in modelos):
            return False, (
                f"El modelo '{self.model}' no esta descargado. "
                f"Instalalo con: ollama pull {self.model}\n"
                f"        Modelos presentes: {', '.join(modelos)}"
            )

        return True, f"Ollama listo con '{self.model}'"

    # -- Interpretacion ----------------------------------------------------

    async def interpretar(
        self, mensaje: str, metadata: dict[str, Any] | None = None
    ) -> SignalEvent | None:
        """Intenta entender un mensaje que el parser de reglas no pudo.

        Devuelve None si no vale la pena, si Ollama falla, o si la respuesta
        no supera la verificacion contra el texto original.
        """
        if not vale_la_pena_consultar(mensaje):
            return None

        crudo = await asyncio.to_thread(self._consultar_sync, mensaje)
        if crudo is None:
            return None

        return self._a_evento(crudo, mensaje, metadata or {})

    def _consultar_sync(self, mensaje: str) -> dict[str, Any] | None:
        cuerpo = json.dumps({
            "model": self.model,
            "prompt": PROMPT.format(mensaje=mensaje),
            "stream": False,
            "format": RESPUESTA_SCHEMA,
            # temperature 0 para que la extraccion sea lo mas determinista
            # posible: no queremos creatividad leyendo precios.
            "options": {"temperature": 0},
        }).encode("utf-8")

        peticion = urllib.request.Request(
            f"{self.url}/api/generate",
            data=cuerpo,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(peticion, timeout=self.timeout) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            if not self._aviso_dado:
                logger.warning(
                    "Ollama no pudo responder (%s). El sistema sigue con el parser de reglas.",
                    type(exc).__name__,
                )
                self._aviso_dado = True
            return None

        try:
            return json.loads(datos.get("response") or "{}")
        except json.JSONDecodeError:
            logger.warning("Ollama devolvio algo que no es JSON valido")
            return None

    # -- Conversion y verificacion ----------------------------------------

    def _a_evento(
        self, crudo: dict[str, Any], mensaje: str, metadata: dict[str, Any]
    ) -> SignalEvent | None:
        if not crudo.get("es_senal"):
            return None

        tipo = str(crudo.get("tipo") or "NINGUNO").upper()
        if tipo == "NINGUNO":
            return None

        mapa = {
            "ABRIR": EventType.OPEN,
            "CERRAR": EventType.CLOSE,
            "CIERRE_PARCIAL": EventType.PARTIAL_CLOSE,
            "MOVER_SL": EventType.MOVE_SL,
        }
        event_type = mapa.get(tipo)
        if event_type is None:
            return None

        avisos: list[str] = []

        entrada = self._numero_verificado(crudo.get("entrada"), mensaje, "entrada", avisos)
        stop_loss = self._numero_verificado(crudo.get("stop_loss"), mensaje, "stop loss", avisos)

        take_profits: list[float] = []
        for bruto in (crudo.get("take_profits") or [])[:5]:
            valor = self._numero_verificado(bruto, mensaje, "take profit", avisos)
            if valor is not None:
                take_profits.append(valor)

        # Si el modelo invento CUALQUIER numero, se descarta todo. No se
        # rescata "la parte buena": un modelo que alucino un precio no es
        # confiable para el resto del mismo mensaje.
        if any("no aparece en el mensaje" in a for a in avisos):
            logger.warning("Interpretacion de la IA descartada por inventar numeros: %s", avisos)
            return None

        simbolo = self._normalizar_simbolo(crudo.get("simbolo"))
        direccion = str(crudo.get("direccion") or "").upper()
        side = Side.BUY if direccion == "BUY" else Side.SELL if direccion == "SELL" else None

        confianza = str(crudo.get("confianza") or "baja").lower()
        razon = str(crudo.get("razon") or "").strip()

        avisos.insert(0, f"Interpretado por IA local ({self.model}), confianza {confianza}")
        if razon:
            avisos.append(f"La IA entendio: {razon}")

        return SignalEvent(
            event_type=event_type,
            symbol=simbolo,
            side=side,
            order_type=OrderType.MARKET,
            entry_low=entrada,
            entry_high=entrada,
            stop_loss=stop_loss,
            take_profits=take_profits,
            raw_message=mensaje,
            telegram_message_id=metadata.get("message_id"),
            telegram_chat_id=metadata.get("chat_id"),
            is_edit=bool(metadata.get("is_edit")),
            reply_to_message_id=metadata.get("reply_to_message_id"),
            source="ollama",
            warnings=avisos,
        )

    @staticmethod
    def _normalizar_simbolo(bruto: Any) -> str | None:
        """Pasa lo que dijo la IA por el mismo diccionario de alias del parser."""
        if not bruto:
            return None
        from tct.signals.parser import SYMBOL_ALIASES

        limpio = re.sub(r"[^A-Z0-9]", "", str(bruto).upper())
        if not limpio:
            return None
        return SYMBOL_ALIASES.get(limpio, limpio)

    @staticmethod
    def _numero_verificado(
        bruto: Any, mensaje: str, etiqueta: str, avisos: list[str]
    ) -> float | None:
        """Convierte a float y verifica que el numero EXISTA en el mensaje.

        Esta es la guarda principal contra alucinaciones. Un modelo puede
        inventar un precio verosimil, pero no puede hacerlo aparecer en un
        texto que ya esta escrito.
        """
        if bruto is None or bruto == "":
            return None

        texto = str(bruto).strip()
        try:
            valor = float(texto.replace(",", "."))
        except ValueError:
            # Ultimo intento: "18,500" como separador de miles.
            try:
                valor = float(texto.replace(",", ""))
            except ValueError:
                return None

        if valor <= 0:
            return None

        if not _aparece_en_texto(valor, mensaje):
            avisos.append(f"El {etiqueta} {valor} no aparece en el mensaje")
            return None

        return valor


def _aparece_en_texto(valor: float, mensaje: str) -> bool:
    """True si `valor` figura en el mensaje, tolerando formatos distintos.

    Cubre 2345 / 2,345 / 2345.0 / 2345,00 y tambien el caso de que el modelo
    devuelva 1.265 donde el mensaje decia 1.2650.
    """
    candidatos = {
        f"{valor:.10f}".rstrip("0").rstrip("."),  # sin ceros sobrantes
        str(valor),
        str(int(valor)) if valor == int(valor) else "",
    }
    # Se normaliza el mensaje quitando separadores de miles para poder
    # comparar "39500" contra "39,500".
    plano = re.sub(r"(?<=\d)[,\s](?=\d{3}\b)", "", mensaje)

    for candidato in candidatos:
        if not candidato:
            continue
        # Frontera de digito: evita que "234" matchee dentro de "2345".
        if re.search(rf"(?<![\d.]){re.escape(candidato)}(?![\d])", plano):
            return True
        # El mensaje puede tener mas decimales que lo devuelto (1.2650 vs 1.265).
        if re.search(rf"(?<![\d.]){re.escape(candidato)}0*(?![\d])", plano):
            return True
    return False
