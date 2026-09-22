"""Cambiar valores de un .env desde la consola: `tct cambiar`.

POR QUE EXISTE
--------------
El usuario no programa, y cada cambio de configuracion era dictarle lineas
para que las busque y las reemplace a mano en el Bloc de notas. Dos veces dijo
"ya" y el archivo seguia igual. Lo pidio asi: "para eso no hay un comando que
se pueda poner en la consola para cambiarlo solo?".

    tct cambiar --env-file .env.segunda MAX_OPEN_TRADES=2 MAX_SIGNALS_PER_DAY=10
    tct cambiar --env-file .env.real MT5_LOGIN=7001234 MT5_PASSWORD

(La password va sin '=': el comando la pide, como `tct clave`. Ver abajo.)

QUE GARANTIZA
-------------
- Toca SOLO las lineas de esas variables. Credenciales, comentarios, el orden
  y los fines de linea de Windows quedan exactamente como estaban; en la linea
  cambiada se conserva el comentario del final, si tenia.
- Guarda lo que el bot va a LEER. Antes de reemplazar el archivo lo lee con el
  mismo lector que usa el bot (python-dotenv) y compara: si algun valor no
  llega tal cual se pidio, o si se movio o aparecio alguna OTRA variable, no
  guarda nada.
- No rompe un archivo que andaba: carga la configuracion nueva con
  `load_settings`, igual que al arrancar, y si da un error que antes no daba,
  no guarda nada.
- Un nombre mal escrito se rechaza. Si no, `MAX_OPEN_TRADE=2` se agregaria al
  final, el bot lo ignoraria, y el comando igual habria dicho "listo".

LA CONSOLA CAMBIA LO QUE SE ESCRIBE
-----------------------------------
cmd.exe procesa la linea ANTES de que llegue al bot: se come los ^, corta en
&, | y >, reemplaza %ALGO% y saca las comillas dobles. Con un numero no pasa
nada, pero una password de broker suele traer esos caracteres, y como en
pantalla sale como ****, nadie se enteraba de que se habia guardado otra. Por
eso las credenciales NO se aceptan en la linea: se escribe solo el nombre y el
comando las pide dos veces sin mostrarlas, que es texto que cmd no toca.
Por lo mismo se rechaza lo que tiene pinta de haber pasado por ese filtro: un
valor partido por un espacio, una comilla doble adentro, otro NOMBRE=VALOR
pegado adentro de un valor.

LO QUE NO TOCA, A PROPOSITO
---------------------------
- La clave de arranque: la pone `tct clave`, que guarda una huella.
- Las dos llaves del dinero real (TRADING_MODE y ALLOW_LIVE_TRADING). Pasar de
  demo a real se hace abriendo el archivo, no con una linea copiada de otro
  lado o escrita de memoria.
- Un archivo que no es de un bot: una plantilla (.example), o uno que no tiene
  ninguna variable del bot (un README, un .bat): `--env-file` elegido con TAB
  cae facil en el vecino.
"""

from __future__ import annotations

import difflib
import io
import logging
import math
import os
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from tct.config import VALORES_SI, VARIABLES_OBSOLETAS

# Las variables que lee `load_settings`, con el lector de `_Env` que usa cada
# una. `tests/test_cambiar_env.py` compara esta tabla contra config.py: una
# variable nueva que no se agregue aca hace fallar ese test, en vez de que
# `tct cambiar` la rechace como si estuviera mal escrita.
VARIABLES_DEL_ENV: dict[str, str] = {
    "TRADING_MODE": "str",
    "ALLOW_LIVE_TRADING": "bool",
    "CLAVE_DE_ARRANQUE": "str",
    "INSTANCE_NAME": "str",
    "INSTANCE_NAMES": "list",
    # Telegram
    "TELEGRAM_API_ID": "str",
    "TELEGRAM_API_HASH": "str",
    "TELEGRAM_SESSION_NAME": "str",
    "TELEGRAM_SOURCE_CHATS": "list",
    "TELEGRAM_SOURCE_CHAT": "list",
    "ENABLE_TELEGRAM_CONTROL": "bool",
    "TELEGRAM_CONTROL_CHAT": "str",
    # MetaTrader
    "MT5_LOGIN": "str",
    "MT5_PASSWORD": "str",
    "MT5_SERVER": "str",
    "MT5_PATH": "str",
    "MT5_BROKER_PROFILE": "str",
    "METAAPI_TOKEN": "str",
    "METAAPI_ACCOUNT_ID": "str",
    "METAAPI_REGION": "str",
    # Riesgo
    "DEFAULT_LOT": "float",
    "MAX_LOT": "float",
    "ALLOWED_SYMBOLS": "list",
    "MAX_OPEN_TRADES": "int",
    "MAX_SIGNALS_PER_DAY": "int",
    "POSITIONS_PER_SIGNAL": "int",
    "MAX_POSITIONS_PER_SYMBOL": "int",
    "REQUIRE_STOP_LOSS": "bool",
    "REQUIRE_TAKE_PROFIT": "bool",
    "MAX_SPREAD_FROM_ENTRY_PCT": "float",
    "MAX_PENDING_DISTANCE_PCT": "float",
    "MAX_DAILY_LOSS_PCT": "float",
    "BREAKEVEN_USES_REAL_ENTRY": "bool",
    # Funcionamiento
    "ENABLE_OCR": "bool",
    "DRY_RUN": "bool",
    "POLL_INTERVAL_SECONDS": "int",
    "DATA_DIR": "str",
    "PAPER_TRADES_PATH": "str",
    "EVENTS_PATH": "str",
    "STATE_PATH": "str",
    "LOG_PATH": "str",
    # IA local
    "ENABLE_OLLAMA": "bool",
    "OLLAMA_URL": "str",
    "OLLAMA_MODEL": "str",
    "OLLAMA_TIMEOUT_SECONDS": "int",
    "OLLAMA_AUTO_EXECUTE": "bool",
}

# `_Env.bool` toma como "no" cualquier cosa que no sea un "si". Aca se exige
# que sea uno de los dos: un "ture" escrito apurado apagaria la opcion en
# silencio.
VALORES_NO = frozenset({"0", "false", "no", "n", "off"})

_DOS_LLAVES = (
    "Es una de las dos llaves del dinero real, y esas se cambian a mano, a\n"
    "    proposito. Abri el archivo con:  notepad {ruta}"
)

# Las que este comando no toca, con lo que hay que hacer en su lugar. El {ruta}
# se completa con `entre_comillas`: la carpeta del proyecto tiene espacios, y
# un comando sugerido sin comillas no funciona copiado.
NO_SE_CAMBIAN_ACA = {
    "CLAVE_DE_ARRANQUE": (
        "La clave se pone con:  tct clave --env-file {ruta}\n"
        "    (el .env guarda una huella de la clave, no la clave)"
    ),
    "TRADING_MODE": _DOS_LLAVES,
    "ALLOW_LIVE_TRADING": _DOS_LLAVES,
}

# Credenciales: no se muestran nunca, y no se aceptan en la linea del comando
# (la consola las cambia sin avisar): se piden.
SECRETAS = frozenset({"MT5_PASSWORD", "TELEGRAM_API_HASH", "METAAPI_TOKEN"})

# Lo que va despues de ".env." en un archivo que NO es de un bot: plantillas,
# el temporal de este mismo comando, respaldos, y el ".txt" que agrega el Bloc
# de notas al "Guardar como".
_NO_SON_DE_UN_BOT = frozenset({"example", "tmp", "bak", "old", "orig", "txt", "backup",
                               "copia", "viejo"})

# La marca que pone el Bloc de notas viejo al principio del archivo. Se arma
# con chr() y no con su secuencia de escape: las herramientas de edicion la
# convertian en el caracter invisible (CONTEXTO_MAESTRO, seccion 7).
BOM = chr(0xFEFF)
_BARRA = chr(92)

_NOMBRE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PALABRA_EN_MAYUSCULAS = re.compile(r"[A-Z][A-Z0-9_]*")


class CambioRechazado(ValueError):
    """No se guardo nada. El mensaje dice por que y que hacer."""


@dataclass(frozen=True)
class Cambio:
    nombre: str
    antes: str | None  # lo que el bot leia del archivo; None = no estaba
    despues: str

    @property
    def cambia(self) -> bool:
        return self.antes != self.despues


@dataclass
class Resultado:
    cambios: list[Cambio]
    guardado: bool = False
    # El error con el que el archivo TODAVIA no deja arrancar el bot, cuando ya
    # no arrancaba antes y el cambio no lo empeora: un `.env.real` al que le
    # faltan las credenciales, completado de a una.
    error_que_queda: str | None = None
    # Variables que tambien estan en el entorno de Windows: esas le ganan al
    # archivo, asi que el cambio no va a tener efecto.
    pisadas_por_el_entorno: dict[str, str] = field(default_factory=dict)
    # Si se cambio INSTANCE_NAMES: lo que declara cada uno de los otros .env.
    rosters_de_los_otros: dict[str, str | None] = field(default_factory=dict)


def mostrar(nombre: str, valor: str | None) -> str:
    """Como se ve un valor en pantalla. Las credenciales no se ven nunca."""
    if valor is None:
        return "(no estaba)"
    if valor == "":
        return "(vacio)"
    if nombre in SECRETAS:
        return "****"
    # Un valor de varias lineas (entre comillas) se muestra en una sola, para
    # que no desarme la tabla de antes -> despues.
    return " / ".join(valor.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def mismo_roster(uno: str | None, otro: str | None) -> bool:
    """Si dos INSTANCE_NAMES declaran la misma lista, como la lee config.py."""
    def nombres(texto: str | None) -> set[str]:
        return {n.strip().lower() for n in (texto or "").split(",") if n.strip()}
    return nombres(uno) == nombres(otro)


def entre_comillas(ruta: Path | str) -> str:
    """Una ruta lista para copiar en la consola. La del proyecto tiene espacios."""
    texto = str(ruta)
    return f'"{texto}"' if " " in texto else texto


def _quizas_queria(nombre_de_archivo: str) -> str | None:
    """El `.env` de un bot que se parece a este nombre: `.env.real.bak` -> `.env.real`."""
    candidato = nombre_de_archivo
    while "." in candidato[1:]:
        candidato = candidato[:candidato.rfind(".")]
        if es_env_de_un_bot(candidato):
            return candidato
    return None


def es_env_de_un_bot(nombre_de_archivo: str) -> bool:
    """Si un archivo es un .env que un bot puede leer: `.env`, `.env.segunda`...

    Y no una plantilla (`.env.real.example`), el temporal de este comando, o
    un respaldo (`.env.segunda.bak`, el `.env.txt` del Bloc de notas). Lo usan
    los avisos de roster desparejo: mandar a "arreglar" un respaldo confunde.
    """
    if nombre_de_archivo == ".env":
        return True
    sufijo = re.fullmatch(r"\.env\.([A-Za-z0-9_-]+)", nombre_de_archivo)
    return bool(sufijo) and sufijo.group(1).lower() not in _NO_SON_DE_UN_BOT


# --------------------------------------------------------------------------
# Leer como lo lee el bot
# --------------------------------------------------------------------------


@contextmanager
def _sin_quejas_de_dotenv() -> Iterator[None]:
    """Calla a python-dotenv mientras se prueban formas de escribir un valor.

    Cada forma que no le cierra la anuncia en ingles ("could not parse
    statement starting at line 1"), y la "linea 1" es la de la prueba, no la
    del archivo de la persona.
    """
    registro = logging.getLogger("dotenv.main")
    antes = registro.disabled
    registro.disabled = True
    try:
        yield
    finally:
        registro.disabled = antes


def _leer_texto(texto: str) -> dict[str, str | None]:
    from dotenv import dotenv_values

    with _sin_quejas_de_dotenv():
        return dict(dotenv_values(stream=io.StringIO(texto)))


def leer_archivo(ruta: Path) -> dict[str, str | None]:
    """Exactamente lo que hace `load_settings` con el archivo.

    Tambien para el "antes", y no el texto ya leido: abrir el archivo en modo
    texto convierte los CRLF de adentro de un valor de varias lineas, y leer
    el antes de otra forma que el despues hacia parecer que ese valor cambio.
    """
    from dotenv import dotenv_values

    return dict(dotenv_values(ruta))


def _error_al_cargar(archivo: Path, ruta_real: Path) -> str | None:
    """El error con el que el bot se negaria a arrancar con este archivo, o None.

    El mensaje se devuelve como si fuera del archivo real: algunos lo nombran,
    y el temporal no puede hacer que el mismo error parezca otro.
    """
    from tct.config import load_settings

    try:
        load_settings(archivo)
    except Exception as exc:  # noqa: BLE001 - lo que sea que impida arrancar
        return str(exc).replace(str(archivo), str(ruta_real))
    return None


def _variables_que_nombra(texto: str) -> set[str]:
    return {p for p in _PALABRA_EN_MAYUSCULAS.findall(texto) if p in VARIABLES_DEL_ENV}


_LINEA_SUELTA = ("El cambio dejaria una linea suelta en el archivo. Pasa cuando un valor\n"
                 "    entre comillas ocupa mas de una linea.")


def verificar_lectura(antes: dict[str, str | None], temporal: Path,
                      pedidos: dict[str, str], consejo: str) -> None:
    """La ultima red: el archivo nuevo, leido por el bot, es el viejo + lo pedido.

    Cada pedido tiene que llegar tal cual, y ninguna OTRA variable puede
    cambiar, aparecer ni desaparecer -tampoco una sin valor, que es como
    python-dotenv lee un pedazo suelto de un valor de varias lineas-.
    """
    despues = leer_archivo(temporal)
    mal = [n for n, v in pedidos.items() if despues.get(n) != v]
    if mal:
        raise CambioRechazado(
            f"{', '.join(mal)} no quedaria como se pidio al leerlo el bot.\n    {consejo}"
        )
    otras = sorted(
        n for n in set(antes) | set(despues)
        if n not in pedidos
        and ((n in antes) != (n in despues) or antes.get(n) != despues.get(n))
    )
    # Un nombre que no es una variable del bot es un pedazo de otro valor:
    # nombrarlo manda a buscar una variable que no existe en ninguna parte.
    variables = [n for n in otras if n in VARIABLES_DEL_ENV]
    if variables:
        raise CambioRechazado(
            f"El cambio movia tambien {', '.join(variables)}, que no se pidieron.\n"
            f"    {consejo}"
        )
    if otras:
        raise CambioRechazado(f"{_LINEA_SUELTA}\n    {consejo}")


def verificar_asignaciones(viejo: str, nuevo: str, pedidos: dict[str, str], consejo: str) -> None:
    """Que no aparezca ni desaparezca una ASIGNACION que no se pidio.

    `verificar_lectura` compara lo que el bot LEE, y eso no alcanza en un caso:
    si un valor de varias lineas se parte, el pedazo que queda suelto puede ser
    una asignacion tapada por otra de mas abajo -el bot lee lo mismo, pero el
    archivo queda con una linea de basura que la persona va a ver-. Aca se
    comparan las asignaciones una por una, con el mismo parser de python-dotenv.
    """
    try:
        from dotenv.parser import parse_stream
    except ImportError:  # pragma: no cover - si cambia el paquete, se sigue sin esto
        return

    def asignaciones(texto: str) -> list[tuple[str, str | None]]:
        # Los CRLF se normalizan en los dos lados: la comparacion es relativa,
        # y python-dotenv los convierte al leer del archivo.
        parejo = texto.replace("\r\n", "\n")
        with _sin_quejas_de_dotenv():
            return [(b.key, b.value) for b in parse_stream(io.StringIO(parejo))
                    if b.key is not None and b.key not in pedidos]

    if asignaciones(viejo) != asignaciones(nuevo):
        raise CambioRechazado(f"{_LINEA_SUELTA}\n    {consejo}")


# --------------------------------------------------------------------------
# Editar el texto
# --------------------------------------------------------------------------


def partir_en_lineas(texto: str) -> list[str]:
    """Corta donde python-dotenv ve un fin de linea, y cada linea conserva el suyo.

    Eso es CRLF, LF y tambien un CR suelto -si no, una linea que empieza con
    un CR suelto escondia una asignacion que el bot si lee-. Y NADA mas:
    `splitlines` corta tambien en caracteres raros (U+2028, el tabulador
    vertical, el salto de pagina...) que python-dotenv no toma como fin de
    linea, y una variable podia quedar escrita en el medio del valor de otra.
    """
    return re.findall(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+$", texto)


def _comentario_al_final(linea: str) -> str:
    """El comentario del final de una asignacion (`MAX_LOT=0.01  # nota`), o "".

    Se reconoce como lo hace python-dotenv: es comentario lo que, sacado, deja
    el mismo valor. Asi un '#' que es parte del valor (`a#b`, o entre
    comillas) no se toma por comentario.
    """
    cuerpo = linea.rstrip("\r\n")
    completo = _leer_texto(cuerpo + "\n")
    for marca in re.finditer(r"[^\S\r\n]+#", cuerpo):
        if _leer_texto(cuerpo[:marca.start()] + "\n") == completo:
            return cuerpo[marca.start():]
    return ""


def poner_linea(texto: str, nombre: str, linea: str, *, comentario: str | None = None) -> str:
    """Devuelve `texto` con `linea` en lugar de cada asignacion de `nombre`.

    Si `nombre` no esta, la agrega al final (con `comentario` arriba, si hay).
    Se reemplazan TODAS las asignaciones y no solo la primera: python-dotenv se
    queda con la ultima, y cambiar la primera dejaria vigente el valor viejo.
    Los comentarios (`# MAX_OPEN_TRADES=5`) no son asignaciones y no se tocan,
    y el del final de una linea reemplazada se le vuelve a poner.
    """
    fin = "\r\n" if "\r\n" in texto else "\n"
    # Lo mismo que acepta python-dotenv delante del nombre: espacios y un
    # `export` opcional. `[^\S\r\n]` es "espacio que no sea fin de linea".
    patron = re.compile(
        rf"^{BOM}?[^\S\r\n]*(?:export[^\S\r\n]+)?{re.escape(nombre)}[^\S\r\n]*="
    )
    lineas = partir_en_lineas(texto)
    reemplazos = 0
    for i, actual in enumerate(lineas):
        if patron.match(actual):
            # La marca BOM va pegada a la primera linea: es del archivo, no de
            # la variable, y se conserva.
            bom = BOM if actual.startswith(BOM) else ""
            cierre = actual[len(actual.rstrip("\r\n")):] or fin
            lineas[i] = bom + linea + _comentario_al_final(actual) + cierre
            reemplazos += 1
    if not reemplazos:
        if lineas and not lineas[-1].endswith(("\n", "\r")):
            lineas[-1] += fin
        if comentario:
            lineas.append(f"{fin}{comentario}{fin}")
        lineas.append(linea + fin)
    return "".join(lineas)


def escribir_atomico(
    ruta: Path, texto: str, *, antes_de_reemplazar: Callable[[Path], None] | None = None
) -> None:
    """Escribe al lado y reemplaza de una: o queda el archivo nuevo entero, o el viejo intacto.

    El .env tiene las credenciales de MetaTrader y de Telegram; un corte a
    mitad de escritura lo dejaria truncado. Por eso tambien el `fsync`: sin
    el, tras un corte de luz el reemplazo puede quedar hecho con el contenido
    todavia sin bajar al disco. `antes_de_reemplazar` recibe el archivo nuevo
    ya escrito, y si lanza una excepcion el viejo no se toca.
    """
    ruta = Path(ruta)
    temporal = ruta.with_name(ruta.name + ".tmp")
    try:
        with open(temporal, "wb") as archivo:
            archivo.write(texto.encode("utf-8"))
            archivo.flush()
            os.fsync(archivo.fileno())
        if antes_de_reemplazar is not None:
            antes_de_reemplazar(temporal)
        os.replace(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)


def _como_se_escribe(nombre: str, valor: str) -> str:
    """La forma de escribir `valor` para que python-dotenv lea exactamente eso.

    Pelado, que es lo que corresponde casi siempre -y lo UNICO que sirve para
    MT5_PATH, por eso va primero: las comillas dobles convierten la barra-t de
    terminal64.exe en un tabulador-. Entre comillas simples si pelado no llega
    igual, por ejemplo con un ' #' adentro, que python-dotenv lee como el
    principio de un comentario. Y entre comillas dobles, con sus barras y
    comillas escapadas, lo que no entra en ninguna de las dos (un ' y un #).
    """
    dobles = '"' + valor.replace(_BARRA, _BARRA * 2).replace('"', _BARRA + '"') + '"'
    for escrito in (valor, f"'{valor}'", dobles):
        if _leer_texto(f"{nombre}={escrito}\n").get(nombre) == valor:
            return escrito
    motivo = (
        "Tiene un ${...} adentro, y el bot lo reemplazaria por otra variable."
        if "${" in valor else "Tiene una combinacion de caracteres que el .env no guarda igual."
    )
    raise CambioRechazado(
        f"{nombre}: no hay forma de escribir {mostrar(nombre, valor)!r} en el .env para\n"
        f"    que el bot lo lea igual. {motivo}"
    )


# --------------------------------------------------------------------------
# Lo que se pidio
# --------------------------------------------------------------------------


def _sin_comillas(valor: str) -> str:
    """`MT5_SERVER="FxPro Live"` se lee como FxPro Live, igual que en el .env."""
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
        return valor[1:-1]
    return valor


def _problema_con(nombre: str, valor: str, ruta: Path) -> str | None:
    if nombre in NO_SE_CAMBIAN_ACA:
        return (f"{nombre} no se cambia con este comando.\n    "
                + NO_SE_CAMBIAN_ACA[nombre].format(ruta=entre_comillas(ruta)))
    if nombre in VARIABLES_OBSOLETAS:
        return (f"{nombre} ya no existe: el bot no manda avisos por Telegram.\n"
                "    Si esta en el archivo, podes borrar esa linea.")
    tipo = VARIABLES_DEL_ENV.get(nombre)
    if tipo is None:
        parecida = difflib.get_close_matches(nombre, list(VARIABLES_DEL_ENV), n=1, cutoff=0.8)
        pista = f" Quisiste decir {parecida[0]}?" if parecida else ""
        return f"{nombre} no es una variable que el bot lea.{pista}"

    if not valor:
        return None  # vacio es "el valor por defecto", que el bot sabe leer
    if tipo in ("int", "float"):
        try:
            numero = int(valor) if tipo == "int" else float(valor.replace(",", "."))
        except ValueError:
            ejemplo = "un numero entero, como 2" if tipo == "int" else "un numero, como 0.05"
            return f"{nombre} tiene que ser {ejemplo}. Llego {valor!r}."
        # config.py los acepta y no avisa: un freno diario en -5 o en nan
        # queda APAGADO mientras el arranque sigue mostrando un tope.
        if not math.isfinite(numero):
            return f"{nombre} tiene que ser un numero comun, como 0.05. Llego {valor!r}."
        if numero < 0:
            pista = (" Para frenar al perder un 5%, se escribe 5, sin signo (0 lo apaga)."
                     if nombre == "MAX_DAILY_LOSS_PCT" else "")
            return f"{nombre} no puede ser negativo. Llego {valor!r}.{pista}"
    elif tipo == "bool" and valor.lower() not in VALORES_SI | VALORES_NO:
        return f"{nombre} es de si o no: escribi true o false. Llego {valor!r}."

    # Lo que deja la consola cuando se equivoca con las comillas: la comilla
    # de cierre escapada por una barra se queda adentro y se traga lo que
    # sigue, y un espacio "duro" pegado desde un chat no separa nada.
    if '"' in valor:
        return (f"El valor de {nombre} tiene una comilla doble adentro. Suele pasar cuando\n"
                "    un valor termina en una barra invertida justo antes de la comilla de\n"
                "    cierre: la consola se come la comilla y todo lo que sigue. Sacale la\n"
                "    barra del final.")
    pegado = re.search(r"\s([A-Za-z_][A-Za-z0-9_]*)=", valor)
    if pegado:
        return (f"El valor de {nombre} trae pegado otro cambio ({pegado.group(1)}=...): van\n"
                "    separados por un espacio comun. Escribilos de nuevo a mano, sin pegar.")
    return None


def _valor_partido(nombre: str, valor: str, sueltas: list[str]) -> str:
    completo = " ".join([valor, *sueltas])
    return (f"El valor de {nombre} quedo partido: tiene espacios, y en la consola un\n"
            "    valor con espacios va entre comillas DOBLES (las simples no sirven):\n"
            f'        {nombre}="{completo}"')


def interpretar(asignaciones: list[str], ruta: Path) -> tuple[dict[str, str], list[str]]:
    """Lo que se pidio: ({"MAX_OPEN_TRADES": "2", ...}, [credenciales a pedir]).

    Junta TODOS los problemas antes de rechazar: quien escribio cinco cambios
    con dos errores tiene que enterarse de los dos de una vez. Y no repite en
    pantalla nada que pueda ser una password: solo nombres de variables.
    """
    pedidos: dict[str, str] = {}
    a_pedir: list[str] = []
    problemas: list[str] = []
    anterior: str | None = None  # el NOMBRE=VALOR de justo antes, bien leido
    i = 0
    while i < len(asignaciones):
        texto = asignaciones[i]
        i += 1
        nombre, igual, valor = texto.partition("=")
        nombre = nombre.strip().upper()
        conocido = nombre in VARIABLES_DEL_ENV

        if not igual:
            if i < len(asignaciones) and asignaciones[i].startswith("="):
                # NOMBRE = VALOR, o NOMBRE =VALOR: se consume el resto, que
                # puede ser una password, sin mostrarlo.
                if asignaciones[i] == "=" and i + 1 < len(asignaciones):
                    i += 1
                i += 1
                cual = repr(texto.strip()) if conocido else "Un nombre"
                problemas.append(f"{cual} va pegado a su valor, sin espacios alrededor del =:"
                                 "  NOMBRE=VALOR")
            elif nombre in SECRETAS:
                if nombre not in a_pedir:
                    a_pedir.append(nombre)
            elif (anterior is not None and not conocido
                  and VARIABLES_DEL_ENV[anterior] in ("str", "list")):
                # Solo un texto puede tener espacios: despues de un numero,
                # una palabra suelta es otra cosa, y no se repite.
                sueltas = [texto]
                # Se corta en el nombre de otra variable: si no, un
                # `MT5_SERVER=FxPro-MT5 Live MT5_PASSWORD` sugeria pegar
                # MT5_SERVER="FxPro-MT5 Live MT5_PASSWORD" -que se acepta, y
                # deja la cuenta real sin poder loguear- y encima la password
                # ya no se pedia.
                while (i < len(asignaciones) and "=" not in asignaciones[i]
                       and asignaciones[i].strip().upper() not in VARIABLES_DEL_ENV):
                    sueltas.append(asignaciones[i])
                    i += 1
                problemas.append(_valor_partido(anterior, pedidos.pop(anterior), sueltas))
            elif conocido:
                problemas.append(f"{texto.strip()!r} no tiene valor: va NOMBRE=VALOR, todo junto.")
            else:
                problemas.append("Hay una palabra suelta que no es NOMBRE=VALOR (no se muestra:\n"
                                 "    podria ser una password).")
            anterior = None
            continue

        anterior = None
        if not nombre:
            problemas.append("Hay un = sin nombre adelante: va NOMBRE=VALOR, todo junto.")
            continue
        if (not valor.strip() and i < len(asignaciones) and "=" not in asignaciones[i]
                and asignaciones[i].strip().upper() not in VARIABLES_DEL_ENV):
            # NOMBRE= VALOR: el valor quedo suelto, y puede ser una password. (Si
            # lo que sigue es un nombre, es "vaciar esta y pedir aquella".)
            i += 1
            problemas.append(f"{nombre if conocido else 'Un nombre'} va pegado a su valor, sin "
                             "espacios despues del =:  NOMBRE=VALOR")
            continue
        if nombre in SECRETAS:
            while i < len(asignaciones) and "=" not in asignaciones[i]:
                i += 1  # el resto de una password con espacios: tampoco se muestra
            problemas.append(
                f"{nombre} no se escribe en la linea del comando: la consola le cambia\n"
                "    caracteres como ^ & % \" sin avisar. Escribi solo el nombre, sin =,\n"
                "    y el comando te la pide sin mostrarla:\n"
                f"        tct cambiar --env-file {entre_comillas(ruta)} {nombre}"
            )
            continue

        valor = _sin_comillas(valor.strip())
        problema = _problema_con(nombre, valor, ruta)
        if problema:
            problemas.append(problema)
            continue
        if nombre in pedidos and pedidos[nombre] != valor:
            problemas.append(
                f"{nombre} esta dos veces y con valores distintos "
                f"({mostrar(nombre, pedidos[nombre])} y {mostrar(nombre, valor)}). "
                "Deja uno solo."
            )
            continue
        pedidos[nombre] = valor
        anterior = nombre

    if problemas:
        raise CambioRechazado("\n".join(problemas))
    return pedidos, a_pedir


def hay_teclado() -> bool:
    """Si hay una consola donde escribir algo que no se muestra.

    `getpass` lee del TECLADO de la consola y no de la entrada: sin consola no
    falla, se queda esperando para siempre y hay que matar el proceso. Es una
    funcion aparte para poder reemplazarla en las pruebas, igual que el
    `es_interactivo` de `clave.pedir_y_verificar`.
    """
    return sys.stdin.isatty()


def pedir_en_consola(nombre: str) -> str:
    """Pide una credencial dos veces, sin mostrarla. Lo escrito aca, cmd no lo toca."""
    import getpass

    if not hay_teclado():
        raise CambioRechazado(
            f"{nombre} se escribe a mano, y esta ventana no tiene teclado propio.\n"
            "    Abri scripts\\consola.bat y corre el comando ahi (no se puede pasar\n"
            "    por un pipe ni por un archivo)."
        )
    try:
        primera = getpass.getpass(f"{nombre} (no se ve mientras la escribis): ")
        segunda = getpass.getpass("Repetila: ")
    except (EOFError, KeyboardInterrupt) as exc:
        raise CambioRechazado(f"No se escribio {nombre}.") from exc
    if primera != segunda:
        raise CambioRechazado(f"{nombre}: lo que escribiste las dos veces no coincide.")
    return primera


# --------------------------------------------------------------------------
# Todo junto
# --------------------------------------------------------------------------


def cambiar_variables(
    ruta: Path, asignaciones: list[str], *, pedir_secreto: Callable[[str], str] | None = None
) -> Resultado:
    """Aplica `NOMBRE=VALOR` al archivo, o lanza CambioRechazado sin tocarlo."""
    ruta = Path(ruta)
    if not ruta.is_file():
        # No se crea: un nombre mal escrito (".env.segunada") no puede
        # terminar en un archivo nuevo que ningun bot lee.
        raise CambioRechazado(
            f"No existe {ruta}. Para ver como se llaman tus archivos:  dir /b .env*"
        )
    if ruta.name.lower().endswith(".example"):
        raise CambioRechazado(
            f"{ruta} es una plantilla: ningun bot la lee. Los que leen los bots son\n"
            "    .env, .env.segunda, .env.real... Para verlos:  dir /b .env*"
        )
    if not es_env_de_un_bot(ruta.name):
        # Lo peor que puede pasar con este comando: editar una COPIA. Sale de
        # apretar TAB, que ofrece el respaldo y el .env.txt del Bloc de notas
        # al lado del de verdad. El comando decia "Listo" con todo bien, y el
        # bot seguia leyendo el original -con el freno del dia en 0-.
        sugerido = _quizas_queria(ruta.name)
        raise CambioRechazado(
            f"{ruta} no es un archivo que lea un bot: parece una copia, un respaldo\n"
            "    o un temporal, y cambiarlo no cambia nada de lo que hace el bot.\n"
            + (f"    Quisiste decir {ruta.parent / sugerido}?\n" if sugerido else "")
            + "    Para ver los que leen los bots:  dir /b .env*\n"
            "    (Si de verdad tenes un .env con otro nombre, editalo con el Bloc de notas.)"
        )
    pedidos, a_pedir = interpretar(asignaciones, ruta)

    original = ruta.read_bytes()
    try:
        crudo = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CambioRechazado(
            f"{ruta} no esta guardado como UTF-8, y el bot no lo puede tocar sin\n"
            "arriesgar lo que tiene adentro. Abrilo con el Bloc de notas, Archivo ->\n"
            "Guardar como, y en 'Codificacion' elegi UTF-8."
        ) from exc
    antes = leer_archivo(ruta)
    if not any(n in VARIABLES_DEL_ENV for n in antes):
        raise CambioRechazado(
            f"{ruta} no parece la configuracion de un bot: no tiene ninguna de sus\n"
            "    variables. Fijate el nombre del archivo:  dir /b .env*"
        )

    # Las credenciales se piden recien ahora: que nadie escriba la password
    # para enterarse despues de que habia un nombre mal escrito.
    for nombre in a_pedir:
        valor = (pedir_secreto or pedir_en_consola)(nombre).strip()
        if not valor:
            raise CambioRechazado(f"No escribiste nada para {nombre}: queda como estaba.")
        pedidos[nombre] = valor

    nuevo = crudo
    cambios = []
    for nombre, valor in pedidos.items():
        cambio = Cambio(nombre, antes.get(nombre), valor)
        cambios.append(cambio)
        if cambio.cambia:
            nuevo = poner_linea(nuevo, nombre, f"{nombre}={_como_se_escribe(nombre, valor)}")

    resultado = Resultado(cambios=cambios)
    # En Windows el entorno no distingue mayusculas, igual que el bot al leerlo.
    resultado.pisadas_por_el_entorno = {
        nombre: os.environ[nombre]
        for nombre, valor in pedidos.items()
        if nombre in os.environ and os.environ[nombre] != valor
    }
    # Se decide por lo PEDIDO, no por si el texto cambio: si algo se pidio
    # distinto y el texto quedo igual, algo fallo al escribirlo, y eso lo
    # tiene que atrapar la relectura de abajo, no pasar como "no habia nada".
    if not any(c.cambia for c in cambios):
        return resultado

    error_antes = _error_al_cargar(ruta, ruta)
    consejo = f"Cambialo a mano:  notepad {entre_comillas(ruta)}"

    def revisar(temporal: Path) -> None:
        verificar_lectura(antes, temporal, pedidos, consejo)
        verificar_asignaciones(crudo, nuevo, pedidos, consejo)
        error = _error_al_cargar(temporal, ruta)
        if error and error != error_antes:
            # Un archivo que ya no arrancaba se puede ir completando de a una
            # cosa: .env.real con el login y todavia sin la password. Se deja
            # pasar SOLO si el error de ahora es de OTRAS variables; uno que
            # nombra lo que se cambio, o que no nombra ninguna, es de este cambio.
            culpables = _variables_que_nombra(error)
            if error_antes is None or not culpables or culpables & set(pedidos):
                raise CambioRechazado("Con este cambio el bot no arrancaria:\n\n" + error)
        resultado.error_que_queda = error
        # Si alguien lo guardo desde otro lado mientras tanto (el Bloc de
        # notas no lo bloquea), reemplazarlo borraria lo que guardo.
        if ruta.read_bytes() != original:
            raise CambioRechazado(
                f"{ruta} cambio mientras se guardaba (lo tenias abierto en otro\n"
                "    programa?). Cerralo y volve a correr el comando."
            )

    escribir_atomico(ruta, nuevo, antes_de_reemplazar=revisar)
    resultado.guardado = True

    if "INSTANCE_NAMES" in pedidos:
        resultado.rosters_de_los_otros = _rosters_de_los_otros(ruta)
    return resultado


def _rosters_de_los_otros(ruta: Path) -> dict[str, str | None]:
    """Lo que declara en INSTANCE_NAMES cada uno de los otros .env de la carpeta.

    Tiene que ser la MISMA lista en todos; quien acaba de cambiarla en uno es
    quien mas necesita ver si quedo igual que en los demas.
    """
    otros: dict[str, str | None] = {}
    for otro in sorted(ruta.resolve().parent.glob(".env*")):
        if (otro.resolve() == ruta.resolve() or not otro.is_file()
                or not es_env_de_un_bot(otro.name)):
            continue
        try:
            otros[otro.name] = leer_archivo(otro).get("INSTANCE_NAMES")
        except Exception:  # noqa: BLE001 - es un aviso, no una validacion
            continue
    return otros
