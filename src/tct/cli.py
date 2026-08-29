"""Interfaz de linea de comandos.

    python -m tct check     # diagnostico: python, dependencias, .env, plataforma
    python -m tct chats     # lista tus chats de Telegram con sus IDs
    python -m tct test      # prueba el parser con un mensaje, sin tocar nada
    python -m tct status    # posiciones abiertas y estadisticas
    python -m tct run       # arranca el bot

`check` es el primero que hay que correr en una maquina nueva: dice que falta
antes de que falte, en vez de fallar a mitad de la primera senal.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import platform
import sys
from pathlib import Path

from tct.config import (
    PAPER_AND_METAAPI_DEMO,
    PAPER_ONLY,
    ConfigError,
    Settings,
    load_settings,
)


def setup_logging(settings: Settings | None = None, verbose: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings is not None:
        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(settings.log_path, encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )
    # Telethon es muy verboso en INFO y tapa los logs propios.
    logging.getLogger("telethon").setLevel(logging.WARNING)


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    """Diagnostico completo del entorno. No necesita credenciales validas."""
    ok = True
    print("=" * 62)
    print("  DIAGNOSTICO DEL ENTORNO")
    print("=" * 62)

    # --- Plataforma ---
    print(f"\nSistema        : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python         : {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("  [ERROR] Se necesita Python 3.10 o superior (por la sintaxis 'X | None').")
        ok = False
    else:
        print("  [OK] Version de Python soportada.")

    # --- Dependencias ---
    # metaapi ya es requerida: se instala de entrada para que activar MT5 demo
    # despues sea solo completar el .env, sin volver a instalar nada.
    print("\nDependencias:")
    for module, label, required in [
        ("telethon", "telethon (leer Telegram)", True),
        ("dotenv", "python-dotenv (.env)", True),
        ("metaapi_cloud_sdk", "metaapi-cloud-sdk (MT5 demo)", True),
        ("pytesseract", "pytesseract (OCR de imagenes)", True),
        ("MetaTrader5", "MetaTrader5 (solo Windows)", False),
    ]:
        try:
            __import__(module)
            print(f"  [OK]      {label}")
        except ImportError:
            if required:
                print(f"  [FALTA]   {label}  <- reinstala con: pip install -r requirements.txt")
                ok = False
            else:
                print(f"  [ausente] {label}  (no aplica en este sistema)")

    # --- Aviso especifico de macOS ---
    if sys.platform == "darwin":
        print("\nmacOS detectado:")
        print("  El paquete MetaTrader5 NO existe para Mac (PyPI solo publica")
        print("  wheels win_amd64), asi que el camino a MT5 es MetaApi Cloud,")
        print("  que ya viene instalado.")

    # --- Configuracion ---
    print("\nConfiguracion (.env):")
    env_path = Path(args.env_file) if args.env_file else Path(".env")
    if not env_path.exists():
        print(f"  [FALTA]   No existe {env_path}. Copiá .env.example a .env y completalo.")
        return 0 if ok else 1

    try:
        settings = load_settings(args.env_file)
    except ConfigError as exc:
        print(f"  [ERROR]   {exc}")
        return 1

    print(f"  [OK]      {env_path} cargado\n")
    for line in settings.describe().splitlines():
        print(f"    {line}")

    # --- Donde van a parar las ordenes ---
    print("\nEjecucion:")
    if settings.trading_mode == PAPER_AND_METAAPI_DEMO:
        print("  [OK]      Las senales van a ir a tu cuenta MT5 demo via MetaApi.")
        print("            Se rechaza cualquier cuenta que no sea demo.")
    elif settings.trading_mode == PAPER_ONLY:
        print("  [papel]   Solo se registran operaciones simuladas.")
        if settings.was_auto_resolved:
            print("            Para operar en tu cuenta MT5 demo, completa en el .env:")
            print("                METAAPI_TOKEN=...")
            print("                METAAPI_ACCOUNT_ID=...")
            print("            (de https://app.metaapi.cloud). Ya esta todo instalado:")
            print("            no hay que instalar ni cambiar TRADING_MODE.")
        else:
            print(f"            TRADING_MODE={settings.configured_mode} lo fija a mano.")
    else:
        print(f"  [OK]      Modo {settings.trading_mode}.")

    for warning in settings.warnings:
        print(f"\n  [AVISO]   {warning}")

    if not settings.telegram_api_id:
        print("\n  [FALTA]   TELEGRAM_API_ID / TELEGRAM_API_HASH (sacalos de my.telegram.org)")
        ok = False
    if not settings.telegram_source_chats:
        print("  [FALTA]   TELEGRAM_SOURCE_CHATS (corré 'python -m tct chats' para verlos)")
        ok = False

    print("\n" + "=" * 62)
    print("  RESULTADO: " + ("todo listo para arrancar" if ok else "faltan cosas (ver arriba)"))
    print("=" * 62)
    return 0 if ok else 1


# --------------------------------------------------------------------------
# chats
# --------------------------------------------------------------------------


def cmd_chats(args: argparse.Namespace) -> int:
    from tct.telegram.reader import list_available_chats

    settings = load_settings(args.env_file)
    setup_logging(verbose=args.verbose)

    if not settings.telegram_api_id or not settings.telegram_api_hash:
        print("Faltan TELEGRAM_API_ID y TELEGRAM_API_HASH en el .env.")
        print("Se obtienen gratis en https://my.telegram.org -> API development tools")
        return 1

    rows = asyncio.run(list_available_chats(settings, limit=args.limit))
    print(f"\n{'ID':>16}  {'TIPO':<8}  TITULO")
    print("-" * 72)
    for row in rows:
        print(f"{row['id']:>16}  {row['type']:<8}  {row['title']}")
    print(
        f"\nCopiá el ID del grupo de senales a TELEGRAM_SOURCE_CHATS en el .env."
        f"\nSe pueden poner varios separados por coma."
    )
    return 0


# --------------------------------------------------------------------------
# test
# --------------------------------------------------------------------------


def cmd_test(args: argparse.Namespace) -> int:
    """Parsea un mensaje y muestra que entendio. No toca disco ni broker."""
    from tct.signals.parser import parse_signal

    if args.message:
        message = " ".join(args.message)
    else:
        print("Pegá el mensaje y terminá con Ctrl+D (Mac/Linux) o Ctrl+Z+Enter (Windows):\n")
        message = sys.stdin.read()

    event = parse_signal(message)
    if event is None:
        print("\n-> No parece un mensaje de trading. Se ignoraria.")
        return 0

    print("\n" + "-" * 52)
    print(f"Tipo de evento : {event.event_type.value}")
    print(f"Simbolo        : {event.symbol}")
    print(f"Direccion      : {event.side.value if event.side else '-'}")
    print(f"Tipo de orden  : {event.order_type.value}")
    if event.has_entry_range:
        print(f"Entrada        : {event.entry_low} - {event.entry_high} (medio: {event.entry})")
    else:
        print(f"Entrada        : {event.entry}")
    print(f"Stop loss      : {event.stop_loss}")
    print(f"Take profits   : {event.take_profits or '-'}")
    if event.close_fraction is not None:
        print(f"Fraccion cierre: {event.close_fraction:.0%}")
    if event.move_sl_to_breakeven:
        print("SL a breakeven : si")
    if event.warnings:
        print("\nAvisos:")
        for warning in event.warnings:
            print(f"  - {warning}")
    print("-" * 52)
    return 0


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    from collections import Counter

    from tct.store import Store

    settings = load_settings(args.env_file)
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)

    print(settings.describe())

    positions = store.open_positions()
    print(f"\nPosiciones abiertas: {len(positions)}")
    for position in positions:
        print(
            f"  {position.symbol:<8} {position.side:<4} lote={position.lot} "
            f"entrada={position.entry} SL={position.stop_loss} "
            f"restante={position.remaining_fraction:.0%} ticket={position.broker_ticket}"
        )

    events = store.read_events()
    if events:
        counts = Counter(event.get("kind") for event in events)
        print(f"\nEventos registrados: {len(events)}")
        for kind, count in counts.most_common():
            print(f"  {kind:<22} {count}")

    trades = store.read_paper_trades()
    print(f"\nPaper trades: {len(trades)}")
    print(f"Senales hoy : {store.signals_today()}/{settings.max_signals_per_day}")
    return 0


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.env_file)
    setup_logging(settings, verbose=args.verbose)
    logger = logging.getLogger("tct")

    for warning in settings.warnings:
        logger.warning(warning)

    logger.info("Arrancando\n%s", settings.describe())
    if settings.dry_run:
        logger.warning("DRY_RUN=true: se va a observar y registrar, sin operar ni siquiera en papel.")

    try:
        asyncio.run(_run_async(settings))
    except KeyboardInterrupt:
        logger.info("Detenido por el usuario")
    return 0


async def _run_async(settings: Settings) -> None:
    from tct.brokers.base import build_broker
    from tct.engine import Engine
    from tct.store import Store
    from tct.telegram.notifier import Notifier
    from tct.telegram.reader import TelegramReader

    logger = logging.getLogger("tct")

    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    broker = build_broker(settings)
    notifier = Notifier(settings)

    if not await broker.connect():
        if settings.executes_orders:
            # En un modo que ejecuta, un broker caido significa senales
            # aceptadas que no llegan a ningun lado: mejor no arrancar.
            logger.error("No se pudo conectar el broker '%s'. Abortando.", broker.name)
            return
        logger.warning("El broker '%s' no conecto, se sigue en modo papel.", broker.name)

    engine = Engine(settings, store, broker, notifier)
    reader = TelegramReader(settings, engine.handle_message)

    if not await reader.start():
        logger.error("No se pudo iniciar la lectura de Telegram. Abortando.")
        await broker.disconnect()
        return

    await notifier.send(
        f"Bot de copy trading arrancado.\nModo: {settings.trading_mode}\n"
        f"Escuchando {len(settings.telegram_source_chats)} chat(s)."
    )
    logger.info("Escuchando mensajes. Ctrl+C para parar.")

    try:
        await reader.run_forever()
    finally:
        await reader.stop()
        await broker.disconnect()
        store.save_state()
        logger.info("Cerrado limpio.")


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tct",
        description="Copy trading de senales de Telegram a MT5 (paper primero).",
    )
    parser.add_argument("--env-file", help="Ruta a un .env alternativo")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logs de debug")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Diagnostico del entorno y la configuracion")

    chats = sub.add_parser("chats", help="Lista tus chats de Telegram con sus IDs")
    chats.add_argument("--limit", type=int, default=60)

    test = sub.add_parser("test", help="Prueba el parser con un mensaje")
    test.add_argument("message", nargs="*", help="Mensaje (si se omite, se lee de stdin)")

    sub.add_parser("status", help="Posiciones abiertas y estadisticas")
    sub.add_parser("run", help="Arranca el bot")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "check": cmd_check,
        "chats": cmd_chats,
        "test": cmd_test,
        "status": cmd_status,
        "run": cmd_run,
    }
    try:
        return handlers[args.command](args)
    except ConfigError as exc:
        print(f"\n[ERROR DE CONFIGURACION]\n{exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
