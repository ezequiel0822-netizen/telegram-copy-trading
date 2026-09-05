"""Configuracion via variables de entorno (.env).

Todo se lee de un solo lugar y se valida al arrancar. Si algo esta mal, el
sistema lo dice al inicio y no a los 20 minutos con una posicion abierta.

Se usa `dotenv_values` y NO `load_dotenv` a proposito: `load_dotenv` escribe
en `os.environ`, que es estado global del proceso. Eso hace que cargar dos
configuraciones distintas contamine la segunda con la primera. Aca el .env se
lee a un diccionario propio y `os.environ` queda intacto.

Precedencia: las variables de entorno reales le ganan al .env, que es la
convencion habitual (permite sobreescribir un valor puntual sin editar el
archivo, util al correr en un servidor).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - el .env es opcional
    def dotenv_values(*_args, **_kwargs) -> dict[str, str]:
        return {}


class ConfigError(RuntimeError):
    """Configuracion invalida. Aborta el arranque."""


# Modos soportados. El orden es la escalera de riesgo que pide el CONTEXTO
# MAESTRO: primero papel, despues demo, y recien al final dinero real.
#
# AUTO es el modo por defecto y existe para que MT5 demo este disponible desde
# el minuto cero sin reinstalar ni reconfigurar nada: el sistema mira si hay
# credenciales de broker en el .env y decide solo. Completar METAAPI_TOKEN y
# METAAPI_ACCOUNT_ID es lo unico que separa el modo papel de la cuenta demo.
AUTO = "AUTO"
PAPER_ONLY = "PAPER_ONLY"
PAPER_AND_METAAPI_DEMO = "PAPER_AND_METAAPI_DEMO"
PAPER_AND_MT5_DEMO = "PAPER_AND_MT5_DEMO"
LIVE = "LIVE"

VALID_MODES = {AUTO, PAPER_ONLY, PAPER_AND_METAAPI_DEMO, PAPER_AND_MT5_DEMO, LIVE}

_DEFAULT_SYMBOLS = "XAUUSD,XAGUSD,EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,NAS100,US30,US500"

# Nombres que siempre significan "todas las instancias". Ninguna instancia
# puede llamarse asi, o "/pausa todos" quedaria ambiguo.
NOMBRES_RESERVADOS = frozenset({"todo", "todos", "all", "ambos", "ambas"})

# El roster de fabrica. Existe para que quien corre una sola instancia no tenga
# que declarar nada, y para que los `.env` escritos antes de que esto fuera
# configurable sigan funcionando igual.
ROSTER_POR_DEFECTO = ("demo", "real", "papel", "paper")


class _Env:
    """Lector tipado sobre un diccionario de configuracion."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = values

    def str(self, key: str, default: str = "") -> str:
        value = self._values.get(key)
        return (value if value is not None else default).strip()

    def bool(self, key: str, default: bool = False) -> bool:
        raw = self.str(key).lower()
        if not raw:
            return default
        return raw in {"1", "true", "yes", "y", "si", "on"}

    def float(self, key: str, default: float) -> float:
        raw = self.str(key)
        if not raw:
            return default
        try:
            return float(raw.replace(",", "."))
        except ValueError as exc:
            raise ConfigError(f"{key} tiene que ser un numero, llego '{raw}'") from exc

    def int(self, key: str, default: int) -> int:
        raw = self.str(key)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"{key} tiene que ser un entero, llego '{raw}'") from exc

    def list(self, key: str, default: str = "") -> list[str]:
        return [item.strip() for item in self.str(key, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    trading_mode: str

    # --- Telegram (lectura del grupo, via Telethon) ---
    telegram_api_id: int | None
    telegram_api_hash: str
    telegram_session_name: str
    telegram_source_chats: list[str]

    # --- Telegram (notificaciones nuestras, via Bot API) ---
    telegram_bot_token: str
    telegram_notify_chat_id: str

    # --- MetaApi (puente MT5 desde macOS) ---
    metaapi_token: str
    metaapi_account_id: str
    metaapi_region: str

    # --- MT5 nativo (solo Windows) ---
    mt5_login: str
    mt5_password: str
    mt5_server: str
    mt5_path: str
    mt5_broker_profile: str

    # --- Riesgo ---
    default_lot: float
    max_lot: float
    allowed_symbols: set[str]
    max_open_trades: int
    max_signals_per_day: int
    require_stop_loss: bool
    require_take_profit: bool
    # Cuanto puede alejarse la entrada del mensaje del precio REAL del
    # instrumento. Son dos numeros porque son dos situaciones distintas:
    # una orden a mercado entra al precio de ahora (una entrada lejana
    # significa que se leyo mal algo), y una pendiente se pone lejos a
    # proposito. 0 en cualquiera de los dos apaga ese control.
    max_spread_from_entry_pct: float
    max_pending_distance_pct: float
    allow_live_trading: bool

    # --- Comportamiento ---
    enable_ocr: bool
    dry_run: bool
    poll_interval_seconds: int

    # --- Rutas ---
    data_dir: Path
    paper_trades_path: Path
    events_path: Path
    state_path: Path
    log_path: Path

    # --- Identidad y control remoto ---
    # Nombre de esta instancia. Con dos bots corriendo (uno demo y uno real),
    # es lo que permite dirigirles ordenes por separado desde Telegram.
    instance_name: str = "demo"
    # El roster completo: todas las instancias que corren en esta
    # instalacion. Cada bot lo necesita para reconocer los nombres de los
    # OTROS y saber que un comando dirigido no es para el.
    instance_names: tuple[str, ...] = ROSTER_POR_DEFECTO
    enable_telegram_control: bool = True
    # Donde escuchar los comandos. "me" son tus Mensajes Guardados: privado,
    # siempre disponible y sin configurar nada.
    telegram_control_chat: str = "me"

    # Freno por perdida diaria, en % del balance del arranque del dia.
    # 0 = apagado. Para dinero real conviene ponerlo.
    max_daily_loss_pct: float = 0.0

    # --- IA local opcional (Ollama) ---
    # Respaldo para mensajes que el parser de reglas no entiende. Nunca es el
    # camino principal: si el parser entendio, la IA ni se entera.
    enable_ollama: bool = False
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: int = 180
    # Que la IA pueda OPERAR y no solo avisar. Apagado a proposito: las
    # validaciones de riesgo verifican que un precio sea coherente, no que sea
    # el correcto. Un precio inventado pero plausible las pasa todas.
    ollama_auto_execute: bool = False

    # Lo que decia el .env. Puede ser AUTO, mientras que `trading_mode` es
    # siempre el modo ya resuelto. Se guarda para poder mostrar la diferencia.
    configured_mode: str = ""

    warnings: list[str] = field(default_factory=list)

    # -- Ayudas de lectura -------------------------------------------------

    @property
    def executes_orders(self) -> bool:
        """True si este modo manda ordenes a un broker de verdad."""
        return self.trading_mode != PAPER_ONLY

    @property
    def was_auto_resolved(self) -> bool:
        return self.configured_mode == AUTO

    @property
    def is_live(self) -> bool:
        """True solo si esto opera con dinero real."""
        return self.trading_mode == LIVE and self.allow_live_trading

    def _describe_ollama(self) -> str:
        if not self.enable_ollama:
            return "apagada"
        rol = "puede OPERAR" if self.ollama_auto_execute else "solo avisa"
        return f"{self.ollama_model} ({rol})"

    def _describe_distancia(self) -> str:
        """Como se muestra el control contra el precio real al arrancar.

        Se imprime aunque este apagado. El freno por perdida diaria estuvo un
        tiempo escrito y desconectado mientras el arranque lo anunciaba como
        activo: un numero en pantalla no prueba que la proteccion exista, pero
        callarlo garantiza que nadie note que falta.
        """
        partes = []
        partes.append(
            f"a mercado {self.max_spread_from_entry_pct}%"
            if self.max_spread_from_entry_pct > 0 else "a mercado sin control"
        )
        partes.append(
            f"pendientes {self.max_pending_distance_pct}%"
            if self.max_pending_distance_pct > 0 else "pendientes sin control"
        )
        return " / ".join(partes)

    @property
    def broker_kind(self) -> str:
        return {
            PAPER_ONLY: "paper",
            PAPER_AND_METAAPI_DEMO: "metaapi",
            PAPER_AND_MT5_DEMO: "mt5",
            LIVE: "mt5",
        }[self.trading_mode]

    def describe(self) -> str:
        """Resumen para loguear al arrancar. Nunca incluye secretos."""
        modo = (
            f"AUTO -> {self.trading_mode}" if self.was_auto_resolved else self.trading_mode
        )
        lines = [
            f"Instancia       : {self.instance_name.upper()}"
            + (f"  (de {len(self.instance_names)}: "
               f"{', '.join(self.instance_names)})" if len(self.instance_names) > 1 else "")
            + ("   <<< DINERO REAL >>>" if self.is_live else ""),
            f"Modo            : {modo}",
            f"Broker          : {self.broker_kind}",
            f"Dry run         : {self.dry_run}",
            f"Lote / max lote : {self.default_lot} / {self.max_lot}",
            f"Simbolos        : {', '.join(sorted(self.allowed_symbols))}",
            f"Max abiertas    : {self.max_open_trades}",
            f"Max senales/dia : {self.max_signals_per_day}",
            f"Exige SL / TP   : {self.require_stop_loss} / {self.require_take_profit}",
            f"Dist. al mercado: {self._describe_distancia()}",
            f"Tope perdida dia: "
            + (f"{self.max_daily_loss_pct}%" if self.max_daily_loss_pct else "sin tope"),
            f"OCR imagenes    : {self.enable_ocr}",
            f"IA local        : {self._describe_ollama()}",
            f"Chats fuente    : {', '.join(self.telegram_source_chats) or '(ninguno)'}",
            f"Telethon        : {'configurado' if self.telegram_api_id else 'FALTA'}",
            f"Notificaciones  : {'configuradas' if self.telegram_bot_token else 'apagadas'}",
            f"Paper trades    : {self.paper_trades_path}",
        ]
        return "\n".join(lines)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Lee el .env indicado (o ./.env), valida y devuelve la configuracion."""
    path = Path(env_file) if env_file else Path(".env")

    values: dict[str, str] = {}
    if path.exists():
        values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    # Las variables reales del entorno tienen la ultima palabra.
    values.update(os.environ)

    env = _Env(values)
    warnings: list[str] = []

    configured_mode = env.str("TRADING_MODE", AUTO).upper()
    if configured_mode not in VALID_MODES:
        raise ConfigError(
            f"TRADING_MODE='{configured_mode}' no es valido. "
            f"Opciones: {', '.join(sorted(VALID_MODES))}"
        )

    if configured_mode == AUTO:
        mode = _resolve_auto(env, warnings)
    else:
        mode = configured_mode

    allow_live = env.bool("ALLOW_LIVE_TRADING", False)
    if mode == LIVE and not allow_live:
        raise ConfigError(
            "TRADING_MODE=LIVE requiere ademas ALLOW_LIVE_TRADING=true.\n"
            "Son dos llaves a proposito: nadie pasa a dinero real sin quererlo dos veces."
        )
    if allow_live:
        warnings.append(
            "ALLOW_LIVE_TRADING=true: la proteccion de cuenta demo esta DESACTIVADA."
        )

    data_dir = Path(env.str("DATA_DIR", "data"))
    default_lot = env.float("DEFAULT_LOT", 0.01)
    max_lot = env.float("MAX_LOT", 0.01)
    if default_lot <= 0:
        raise ConfigError("DEFAULT_LOT tiene que ser mayor que cero")
    if default_lot > max_lot:
        raise ConfigError(f"DEFAULT_LOT ({default_lot}) no puede superar MAX_LOT ({max_lot})")

    api_id_raw = env.str("TELEGRAM_API_ID")
    api_id: int | None = None
    if api_id_raw:
        try:
            api_id = int(api_id_raw)
        except ValueError as exc:
            raise ConfigError(
                f"TELEGRAM_API_ID tiene que ser numerico, llego '{api_id_raw}'"
            ) from exc

    source_chats = env.list("TELEGRAM_SOURCE_CHATS") or env.list("TELEGRAM_SOURCE_CHAT")
    if not source_chats:
        warnings.append(
            "TELEGRAM_SOURCE_CHATS vacio: el bot no va a escuchar ningun grupo. "
            "Corre 'python -m tct chats' para listar los tuyos."
        )

    instance_name = env.str("INSTANCE_NAME", "real" if mode == LIVE else "demo").lower()
    instance_names = _resolver_roster(env, instance_name)

    settings = Settings(
        trading_mode=mode,
        telegram_api_id=api_id,
        telegram_api_hash=env.str("TELEGRAM_API_HASH"),
        telegram_session_name=env.str("TELEGRAM_SESSION_NAME", "telegram_copy_trading"),
        telegram_source_chats=source_chats,
        telegram_bot_token=env.str("TELEGRAM_BOT_TOKEN"),
        telegram_notify_chat_id=env.str("TELEGRAM_NOTIFY_CHAT_ID"),
        metaapi_token=env.str("METAAPI_TOKEN"),
        metaapi_account_id=env.str("METAAPI_ACCOUNT_ID"),
        metaapi_region=env.str("METAAPI_REGION", "new-york"),
        mt5_login=env.str("MT5_LOGIN"),
        mt5_password=env.str("MT5_PASSWORD"),
        mt5_server=env.str("MT5_SERVER"),
        mt5_path=env.str("MT5_PATH"),
        mt5_broker_profile=env.str("MT5_BROKER_PROFILE", "default"),
        default_lot=default_lot,
        max_lot=max_lot,
        allowed_symbols={s.upper() for s in env.list("ALLOWED_SYMBOLS", _DEFAULT_SYMBOLS)},
        max_open_trades=env.int("MAX_OPEN_TRADES", 5),
        max_signals_per_day=env.int("MAX_SIGNALS_PER_DAY", 20),
        require_stop_loss=env.bool("REQUIRE_STOP_LOSS", True),
        require_take_profit=env.bool("REQUIRE_TAKE_PROFIT", True),
        max_spread_from_entry_pct=env.float("MAX_SPREAD_FROM_ENTRY_PCT", 0.5),
        max_pending_distance_pct=env.float("MAX_PENDING_DISTANCE_PCT", 3.0),
        allow_live_trading=allow_live,
        enable_ocr=env.bool("ENABLE_OCR", False),
        dry_run=env.bool("DRY_RUN", False),
        poll_interval_seconds=env.int("POLL_INTERVAL_SECONDS", 5),
        data_dir=data_dir,
        paper_trades_path=Path(env.str("PAPER_TRADES_PATH", str(data_dir / "paper_trades.jsonl"))),
        events_path=Path(env.str("EVENTS_PATH", str(data_dir / "events.jsonl"))),
        state_path=Path(env.str("STATE_PATH", str(data_dir / "state.json"))),
        log_path=Path(env.str("LOG_PATH", "logs/tct.log")),
        instance_name=instance_name,
        instance_names=instance_names,
        enable_telegram_control=env.bool("ENABLE_TELEGRAM_CONTROL", True),
        telegram_control_chat=env.str("TELEGRAM_CONTROL_CHAT", "me"),
        max_daily_loss_pct=env.float("MAX_DAILY_LOSS_PCT", 0.0),
        enable_ollama=env.bool("ENABLE_OLLAMA", False),
        ollama_url=env.str("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=env.str("OLLAMA_MODEL", "llama3.2:3b"),
        ollama_timeout_seconds=env.int("OLLAMA_TIMEOUT_SECONDS", 180),
        ollama_auto_execute=env.bool("OLLAMA_AUTO_EXECUTE", False),
        configured_mode=configured_mode,
        warnings=warnings,
    )

    _validate_mode_requirements(settings)
    return settings


def _resolver_roster(env: _Env, instance_name: str) -> tuple[str, ...]:
    """La lista COMPLETA de instancias que existen en esta instalacion.

    POR QUE HACE FALTA DECLARARLA
    -----------------------------
    Los comandos de Telegram aceptan destinatario (`/pausa fxpro`), y la
    primera palabra despues del comando puede ser un nombre de instancia o el
    principio de un texto libre (`/pausa mercado feo`). Distinguirlos sin
    ambiguedad solo se puede con un vocabulario CERRADO, y ese vocabulario
    tiene que ser el mismo en todas las instancias: cada bot necesita
    reconocer los nombres de los OTROS para saber que un comando no es para el.

    Por eso no alcanza con que cada `.env` diga como se llama el suyo. Todos
    tienen que declarar la misma lista en INSTANCE_NAMES.

    Si dos `.env` declaran listas distintas, el error se cae para el lado
    seguro: un `/pausa <nombre-que-no-conozco>` se lee como texto libre y esa
    instancia se pausa de mas (pausar nunca pierde plata), y un
    `/cerrar <nombre-que-no-conozco>` no se entiende y se rechaza. Igual
    conviene que coincidan, y por eso el roster se imprime al arrancar.
    """
    declarado = env.list("INSTANCE_NAMES", "")
    roster = tuple(dict.fromkeys(n.lower() for n in declarado)) or ROSTER_POR_DEFECTO

    for nombre in roster:
        if not nombre.isalnum():
            raise ConfigError(
                f"INSTANCE_NAMES tiene un nombre invalido: '{nombre}'.\n"
                "Los nombres son una sola palabra de letras y numeros, sin "
                "espacios ni guiones:\n"
                "    INSTANCE_NAMES=demo,fxpro,real"
            )
        if nombre in NOMBRES_RESERVADOS:
            raise ConfigError(
                f"Una instancia no se puede llamar '{nombre}': esa palabra ya "
                "significa 'todas'.\n"
                f"Reservadas: {', '.join(sorted(NOMBRES_RESERVADOS))}."
            )

    if instance_name not in roster:
        raise ConfigError(
            f"INSTANCE_NAME='{instance_name}' no esta en INSTANCE_NAMES.\n"
            f"El roster declarado es: {', '.join(roster)}.\n\n"
            "INSTANCE_NAME es como se llama ESTE bot; INSTANCE_NAMES es la lista\n"
            "de todos los que corren, y tiene que ser la MISMA en cada .env.\n"
            "Si agregaste una instancia nueva, agregala en los dos archivos:\n"
            f"    INSTANCE_NAMES={','.join(roster)},{instance_name}"
        )

    return roster


def _resolve_auto(env: _Env, warnings: list[str]) -> str:
    """Elige el modo real segun que credenciales de broker haya en el .env.

    Es lo que hace que MT5 demo este disponible desde el principio: no hay que
    cambiar TRADING_MODE ni reinstalar nada, alcanza con completar dos
    variables y reiniciar. Mientras esten vacias, el sistema corre en papel.

    MetaApi va primero porque es el unico camino que funciona en macOS, que es
    la maquina destino.
    """
    import sys

    if env.str("METAAPI_TOKEN") and env.str("METAAPI_ACCOUNT_ID"):
        return PAPER_AND_METAAPI_DEMO

    if (
        sys.platform == "win32"
        and env.str("MT5_LOGIN")
        and env.str("MT5_PASSWORD")
        and env.str("MT5_SERVER")
    ):
        return PAPER_AND_MT5_DEMO

    # Que completar depende de la plataforma: en Windows se habla directo con
    # la terminal MT5, en macOS hace falta el puente de MetaApi.
    faltante = (
        "MT5_LOGIN, MT5_PASSWORD y MT5_SERVER"
        if sys.platform == "win32"
        else "METAAPI_TOKEN y METAAPI_ACCOUNT_ID"
    )
    warnings.append(
        f"Corriendo en papel: no hay credenciales de broker. Para operar en tu "
        f"cuenta MT5 demo, completa {faltante} en el .env y volve a arrancar "
        f"(ya esta todo instalado)."
    )
    return PAPER_ONLY


def _validate_mode_requirements(settings: Settings) -> None:
    """Cada modo necesita sus credenciales. Se avisa ahora, no en produccion."""
    if settings.trading_mode == PAPER_AND_METAAPI_DEMO:
        missing = [
            key
            for key, value in (
                ("METAAPI_TOKEN", settings.metaapi_token),
                ("METAAPI_ACCOUNT_ID", settings.metaapi_account_id),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"TRADING_MODE={PAPER_AND_METAAPI_DEMO} necesita: {', '.join(missing)}"
            )

    if settings.trading_mode in {PAPER_AND_MT5_DEMO, LIVE}:
        import sys

        if sys.platform != "win32":
            raise ConfigError(
                f"TRADING_MODE={settings.trading_mode} usa el paquete MetaTrader5, que solo "
                f"existe para Windows (PyPI solo publica wheels win_amd64).\n"
                f"En macOS usa {PAPER_ONLY} o {PAPER_AND_METAAPI_DEMO}."
            )
