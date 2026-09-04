"""Interfaz de linea de comandos.

    python -m tct check     # diagnostico: python, dependencias, .env, plataforma
    python -m tct mt5       # lee tu cuenta MT5 y dice que poner en el .env
    python -m tct chatid    # averigua el chat id para las notificaciones
    python -m tct simular   # reproduce los mensajes reales de hoy
    python -m tct probar    # verifica la cadena completa contra MT5
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
import math
import platform
import sys
from pathlib import Path

from tct.config import (
    PAPER_AND_METAAPI_DEMO,
    PAPER_AND_MT5_DEMO,
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
    elif settings.trading_mode == PAPER_AND_MT5_DEMO:
        print("  [OK]      Las senales van a ir a tu cuenta MT5 demo local.")
        print("            Acordate: MetaTrader 5 tiene que estar ABIERTO, logueado,")
        print("            y con el boton 'Algo Trading' en verde.")
    elif settings.trading_mode == PAPER_ONLY:
        print("  [papel]   Solo se registran operaciones simuladas.")
        if settings.was_auto_resolved:
            # El camino a la cuenta demo depende de la plataforma: en Windows
            # se habla directo con la terminal, en macOS hace falta el puente.
            print("            Para operar en tu cuenta MT5 demo, completa en el .env:")
            if sys.platform == "win32":
                print("                MT5_LOGIN=...")
                print("                MT5_PASSWORD=...")
                print("                MT5_SERVER=...")
                print("            (los tres, de tu cuenta demo en MetaTrader 5).")
            else:
                print("                METAAPI_TOKEN=...")
                print("                METAAPI_ACCOUNT_ID=...")
                print("            (de https://app.metaapi.cloud; en macOS el paquete")
                print("            MetaTrader5 no existe y hace falta ese puente).")
            print("            Ya esta todo instalado: no hay que cambiar TRADING_MODE.")
        else:
            print(f"            TRADING_MODE={settings.configured_mode} lo fija a mano.")
    else:
        print(f"  [OK]      Modo {settings.trading_mode}.")

    # --- IA local ---
    if settings.enable_ollama:
        import asyncio as _asyncio

        from tct.intelligence.ollama import OllamaParser

        print("\nIA local (Ollama):")
        listo, detalle = _asyncio.run(OllamaParser(settings).disponible())
        if listo:
            print(f"  [OK]      {detalle}")
            if settings.ollama_auto_execute:
                print("  [AVISO]   OLLAMA_AUTO_EXECUTE=true: la IA puede abrir operaciones.")
            else:
                print("            Solo avisa por Telegram, no opera. Es lo recomendado.")
        else:
            # No se marca como error: el bot corre perfecto sin IA.
            print(f"  [ausente] {detalle}")
            print("            El bot funciona igual, solo con el parser de reglas.")

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
# mt5
# --------------------------------------------------------------------------


def cmd_mt5(args: argparse.Namespace) -> int:
    """Lee la cuenta de la terminal MT5 abierta y dice que poner en el .env.

    Existe para eliminar la parte mas confusa de la instalacion: averiguar el
    nombre EXACTO del servidor del broker. Ese nombre no se adivina (cada
    broker tiene varios, y cambian), y escribirlo mal da un error de login que
    no explica nada. Si la terminal ya esta abierta y logueada, el dato esta
    ahi: se lee y listo.
    """
    if sys.platform != "win32":
        print("Este comando solo sirve en Windows: el paquete MetaTrader5 no")
        print("existe para otros sistemas. En macOS el camino es MetaApi.")
        return 1

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("Falta el paquete MetaTrader5. Reinstala con:")
        print("    pip install -r requirements.txt")
        return 1

    print("Conectando con la terminal MetaTrader 5 abierta...\n")
    if not mt5.initialize():
        codigo, mensaje = mt5.last_error()
        print(f"[ERROR] No se pudo conectar: {mensaje} (codigo {codigo})\n")
        print("Casi siempre es una de estas tres:")
        print("  1. MetaTrader 5 no esta abierto. Abrilo.")
        print("  2. Esta abierto pero sin loguear en ninguna cuenta.")
        print("  3. Se abrio 'como administrador' y este comando no. Los dos")
        print("     tienen que correr con el mismo nivel de permisos.")
        return 1

    try:
        cuenta = mt5.account_info()
        terminal = mt5.terminal_info()

        if cuenta is None:
            print("[ERROR] La terminal esta abierta pero sin cuenta cargada.")
            print("Logueate en tu cuenta demo y volve a probar.")
            return 1

        demo_const = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        es_demo = cuenta.trade_mode == demo_const if demo_const is not None else None

        print("=" * 58)
        print("  CUENTA DETECTADA")
        print("=" * 58)
        print(f"  Titular    : {cuenta.name}")
        print(f"  Broker     : {cuenta.company}")
        print(f"  Login      : {cuenta.login}")
        print(f"  Servidor   : {cuenta.server}")
        print(f"  Balance    : {cuenta.balance} {cuenta.currency}")
        tipo = "DEMO" if es_demo else "REAL" if es_demo is False else "desconocido"
        print(f"  Tipo       : {tipo}")

        print("\n" + "=" * 58)
        print("  QUE PONER EN EL .env")
        print("=" * 58)
        print("  Copia estas dos lineas tal cual (la tercera es tu password):\n")
        print(f"      MT5_LOGIN={cuenta.login}")
        print(f"      MT5_SERVER={cuenta.server}")
        print("      MT5_PASSWORD=<la de tu cuenta demo>")

        # Avisos que evitan un fallo silencioso mas adelante.
        problemas = []
        if es_demo is False:
            problemas.append(
                "Esta cuenta es REAL, no demo. El bot se va a negar a operar en\n"
                "     ella, que es justamente lo que queres. Crea una cuenta demo:\n"
                "     en MetaTrader, Archivo -> Abrir una cuenta."
            )
        if terminal is not None and getattr(terminal, "trade_allowed", True) is False:
            problemas.append(
                "El boton 'Algo Trading' esta APAGADO. Ninguna orden va a entrar.\n"
                "     Apretalo en la barra de arriba de MetaTrader (tiene que quedar\n"
                "     verde) o presiona Ctrl+E."
            )
        if getattr(cuenta, "trade_allowed", True) is False:
            problemas.append(
                "El broker tiene el trading deshabilitado en esta cuenta.\n"
                "     Suele pasar con cuentas demo vencidas: crea una nueva."
            )

        if problemas:
            print("\n" + "=" * 58)
            print("  HAY QUE ARREGLAR ESTO ANTES DE OPERAR")
            print("=" * 58)
            for i, p in enumerate(problemas, 1):
                print(f"  {i}. {p}")
        else:
            print("\n  Todo en orden: cuenta demo y Algo Trading activado.")

        return 1 if problemas else 0
    finally:
        mt5.shutdown()


# --------------------------------------------------------------------------
# chatid
# --------------------------------------------------------------------------


def cmd_chatid(args: argparse.Namespace) -> int:
    """Averigua el chat id para las notificaciones, preguntandoselo al bot.

    Es el dato que menos se puede adivinar de toda la configuracion: no
    aparece en ninguna pantalla de Telegram. El camino manual es abrir una URL
    de la API en el navegador y buscar un numero dentro de un JSON. Aca se
    hace solo.
    """
    import json
    import urllib.error
    import urllib.request

    settings = load_settings(args.env_file)
    token = settings.telegram_bot_token
    if not token:
        print("Falta TELEGRAM_BOT_TOKEN en el .env.")
        print("Se saca hablandole a @BotFather en Telegram: /newbot")
        return 1

    try:
        with urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=15
        ) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            print("Telegram rechazo el token: TELEGRAM_BOT_TOKEN esta mal copiado.")
            print("Volve a pedirselo a @BotFather con /mybots -> tu bot -> API Token")
            return 1
        print(f"Telegram respondio con un error HTTP {exc.code}.")
        return 1
    except Exception as exc:
        print(f"No se pudo consultar a Telegram: {type(exc).__name__}")
        return 1

    if not datos.get("ok"):
        print("Telegram no confirmo la consulta. Revisa el token.")
        return 1

    # Se recorren todos los updates: cada uno trae el chat donde ocurrio.
    encontrados: dict[str, str] = {}
    for update in datos.get("result", []):
        mensaje = update.get("message") or update.get("edited_message") or {}
        chat = mensaje.get("chat") or {}
        if chat.get("id") is None:
            continue
        nombre = (
            chat.get("title")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or chat.get("username")
            or "(sin nombre)"
        )
        encontrados[str(chat["id"])] = f"{nombre}  [{chat.get('type', '?')}]"

    if not encontrados:
        print("El bot todavia no recibio ningun mensaje, asi que no sabe con quien habla.\n")
        print("Hace esto y volve a correr el comando:")
        print("  1. Abri Telegram y busca tu bot por su nombre de usuario.")
        print("  2. Apreta INICIAR (o /start).")
        print("  3. Mandale cualquier cosa, por ejemplo: hola")
        print("\nUn bot no puede escribirle primero a nadie: necesita que le hablen")
        print("una vez para conocer el chat. Por eso este paso es obligatorio.")
        return 1

    print("=" * 58)
    print("  CHATS QUE CONOCE TU BOT")
    print("=" * 58)
    for chat_id, descripcion in encontrados.items():
        print(f"  {chat_id:<18} {descripcion}")

    print("\n" + "=" * 58)
    print("  QUE PONER EN EL .env")
    print("=" * 58)
    if len(encontrados) == 1:
        unico = next(iter(encontrados))
        print(f"\n      TELEGRAM_NOTIFY_CHAT_ID={unico}\n")
    else:
        print("\n  Elegi el tuyo de la lista de arriba:\n")
        print("      TELEGRAM_NOTIFY_CHAT_ID=<el numero>\n")
    return 0


# --------------------------------------------------------------------------
# simular
# --------------------------------------------------------------------------


def cmd_simular(args: argparse.Namespace) -> int:
    """Reproduce los mensajes reales de las ultimas horas contra el sistema.

    Es la unica forma de saber si el parser entiende a ESE grupo sin esperar a
    que llegue una senal nueva. Por defecto NO ejecuta nada: muestra que habria
    pasado con cada mensaje. Con --ejecutar, corre de verdad contra la cuenta
    demo.
    """
    settings = load_settings(args.env_file)
    setup_logging(verbose=args.verbose)

    if not settings.telegram_source_chats:
        print("No hay ningun chat configurado en TELEGRAM_SOURCE_CHATS.")
        print("Corre primero:  python -m tct chats")
        return 1

    return asyncio.run(_simular_async(settings, args))


async def _simular_async(settings: Settings, args: argparse.Namespace) -> int:
    from tct.brokers.base import build_broker
    from tct.brokers.paper import PaperBroker
    from tct.engine import Engine
    from tct.signals.parser import parse_signal
    from tct.store import Store
    from tct.telegram.reader import fetch_recent_messages

    print(f"Trayendo los mensajes de las ultimas {args.horas} horas...\n")
    mensajes = await fetch_recent_messages(settings, horas=args.horas, limite=args.limite)

    con_texto = [(t, m) for t, m in mensajes if t]
    sin_texto = len(mensajes) - len(con_texto)

    print("=" * 66)
    print(f"  {len(mensajes)} mensajes en las ultimas {args.horas}h "
          f"({len(con_texto)} con texto, {sin_texto} solo media)")
    print("=" * 66)

    if not con_texto:
        print("\nNo hay mensajes de texto en ese rango. Proba con mas horas:")
        print(f"    python -m tct simular --horas {args.horas * 3}")
        return 0

    # --- Modo mirada: solo el parser, sin motor ni broker -----------------
    if not args.ejecutar:
        from tct.signals.models import EventType

        # Con --con-precios se conecta el broker UNICAMENTE para leer
        # cotizaciones. Sigue sin registrar ni ejecutar nada, y es la unica
        # forma de calibrar MAX_SPREAD_FROM_ENTRY_PCT contra los mensajes
        # reales del grupo antes de que el filtro empiece a rechazar en serio.
        broker = None
        if args.con_precios and not settings.executes_orders:
            # En papel no hay ninguna fuente de precios: el broker simulado no
            # cotiza nada. Sin este aviso, la salida repetiria "el broker no
            # cotiza este simbolo" una vez por senal y nadie entenderia por que.
            print("[AVISO] Estas en modo papel, donde no hay precios de mercado.")
            print("        Para comparar contra precios reales hace falta MT5")
            print("        conectado (completar MT5_LOGIN/PASSWORD/SERVER en el .env).\n")
        elif args.con_precios:
            broker = build_broker(settings)
            if not await broker.connect():
                print(f"[AVISO] No se pudo conectar el broker '{broker.name}'.")
                print("        Se sigue sin comparar contra precios.")
                print("        Para ver que pasa:  python -m tct mt5\n")
                broker = None

        interpretados = 0
        distancias: list[tuple[str, float, bool, str]] = []
        try:
            for texto, meta in con_texto:
                evento = parse_signal(texto, **{
                    k: v for k, v in meta.items()
                    if k in {"message_id", "chat_id", "is_edit", "reply_to_message_id", "source"}
                })
                resumen = " ".join(texto.split())[:58]
                if evento is None:
                    if args.todos:
                        print(f"  .  {resumen}")
                    continue
                interpretados += 1
                lado = evento.side.value if evento.side else "-"
                print(f"  >  {resumen}")
                print(f"     -> {evento.event_type.value} {evento.symbol or '?'} {lado} "
                      f"e={evento.entry} sl={evento.stop_loss} tp={evento.take_profits}")
                for aviso in evento.warnings:
                    print(f"        aviso: {aviso}")
                if broker is not None and evento.event_type is EventType.OPEN:
                    await _mostrar_distancia(broker, settings, evento, distancias)
        finally:
            if broker is not None:
                await broker.disconnect()

        print("\n" + "=" * 66)
        print(f"  {interpretados} de {len(con_texto)} mensajes se interpretaron como senal")
        print("=" * 66)

        if distancias:
            _resumen_de_distancias(settings, distancias)

        print("\n  Esto fue solo una mirada: no se registro ni ejecuto nada.")
        print("  Para correrlo de verdad contra la cuenta demo:")
        print(f"      python -m tct simular --horas {args.horas} --ejecutar")
        if not args.todos:
            print("\n  Para ver tambien los mensajes descartados, agrega --todos")
        if not args.con_precios:
            print("  Para comparar cada entrada contra el precio real de MT5,")
            print("  agrega --con-precios (solo lee cotizaciones, no opera)")
        return 0

    # --- Modo ejecucion: el ciclo completo, con broker real ---------------
    # Se usa un almacenamiento aparte para no mezclar esta prueba con el
    # historial real del bot.
    carpeta = settings.data_dir / "simulacion"
    store = Store(
        carpeta / "events.jsonl", carpeta / "paper_trades.jsonl", carpeta / "state.json"
    )
    broker = build_broker(settings)
    if not await broker.connect():
        if settings.executes_orders:
            print(f"\n[ERROR] No se pudo conectar el broker '{broker.name}'.")
            print("Corre 'python -m tct mt5' para ver que pasa con MetaTrader.")
            return 1
        broker = PaperBroker()
        await broker.connect()

    print(f"\nEjecutando contra: {broker.name} (modo {settings.trading_mode})")
    print(f"Registros de esta prueba en: {carpeta}\n")

    engine = Engine(settings, store, broker)
    conteo: dict[str, int] = {}
    try:
        for texto, meta in con_texto:
            resultado = await engine.handle_message(texto, meta)
            estado = resultado.get("status", "?")
            conteo[estado] = conteo.get(estado, 0) + 1
            if estado in {"ignorado", "duplicado"}:
                continue
            resumen = " ".join(texto.split())[:52]
            print(f"  [{estado:<16}] {resumen}")
            for motivo in resultado.get("reasons", []):
                print(f"                     motivo: {motivo}")
    finally:
        await broker.disconnect()
        store.save_state()

    print("\n" + "=" * 66)
    print("  RESULTADO")
    print("=" * 66)
    for estado, veces in sorted(conteo.items(), key=lambda p: -p[1]):
        print(f"  {estado:<22} {veces}")

    abiertas = store.open_positions()
    if abiertas:
        print(f"\n  Quedaron {len(abiertas)} posicion(es) abiertas:")
        for p in abiertas:
            print(f"    {p.symbol} {p.side} lote={p.lot} ticket={p.broker_ticket}")
        print("\n  Si operaste contra MT5 demo, revisalas en la pestana 'Operaciones'")
        print("  de MetaTrader y cerralas a mano si no las queres.")
    return 0


async def _mostrar_distancia(broker, settings: Settings, evento, distancias: list) -> None:
    """Muestra a que distancia del precio real quedo la entrada de una senal.

    Usa `risk.distancia_al_mercado`, la misma cuenta que despues aplica el
    filtro. Calibrar el numero mirando otra formula seria calibrarlo contra
    algo que no es lo que se ejecuta.
    """
    from tct.risk import distancia_al_mercado
    from tct.signals.models import OrderType

    if not evento.symbol or evento.entry is None:
        return

    try:
        precio = await broker.market_price(evento.symbol)
    except Exception:
        precio = None
    if precio is None:
        print("        precio: el broker no cotiza este simbolo ahora")
        return

    distancia = distancia_al_mercado(evento, precio)
    if distancia is None:
        return

    a_mercado = evento.order_type is OrderType.MARKET
    limite = (
        settings.max_spread_from_entry_pct if a_mercado
        else settings.max_pending_distance_pct
    )
    llave = (
        "MAX_SPREAD_FROM_ENTRY_PCT" if a_mercado else "MAX_PENDING_DISTANCE_PCT"
    )
    rechaza = limite > 0 and distancia > limite
    print(f"        precio: mercado {precio} | distancia {distancia:.2f}% | "
          f"limite {limite}% -> {'RECHAZA' if rechaza else 'pasa'}")
    distancias.append((evento.symbol, distancia, rechaza, llave))


# Por encima de esta distancia no hay senal buena: es un simbolo mal leido o
# una escala cambiada. Sugerir un limite que la deje pasar seria sugerir
# apagar la proteccion.
_TOPE_SUGERENCIA_PCT = 5.0


def _resumen_de_distancias(settings: Settings, distancias: list) -> None:
    """Traduce las distancias medidas en algo accionable para el .env.

    A proposito NO propone un limite que deje pasar todo. El rechazo mas
    grande suele ser justamente el mensaje mal leido, y un numero que lo
    dejara entrar apagaria la proteccion entera; alguien que no programa lo
    copiaria sin poder notarlo. La sugerencia se calcula sobre el rechazo MAS
    CHICO, que es el unico candidato razonable a falso positivo.
    """
    rechazadas = sorted(
        (distancia, simbolo, llave)
        for simbolo, distancia, rechaza, llave in distancias if rechaza
    )
    peor = max(d for _, d, _, _ in distancias)

    print("\n" + "-" * 66)
    print(f"  DISTANCIA AL PRECIO REAL  ({len(distancias)} senales medidas)")
    print("-" * 66)

    if not rechazadas:
        print(f"  Ninguna se habria rechazado. La mas lejos quedo a {peor:.2f}%.")
    else:
        print(f"  Se habrian rechazado {len(rechazadas)}, a estas distancias:")
        for distancia, simbolo, _ in rechazadas:
            print(f"      {simbolo:<8} {distancia:7.2f}%")

        menor, _, llave_menor = rechazadas[0]
        print("\n  Anda a ver arriba que decian esos mensajes:")
        print("    - Si el bot los leyo MAL, el filtro hizo su trabajo. No toques nada.")
        if menor <= _TOPE_SUGERENCIA_PCT:
            print("    - Si alguno estaba BIEN, el limite quedo corto. Para que")
            print(f"      entrara el de {menor:.2f}%, en el .env:")
            print(f"          {llave_menor}={_limite_holgado(menor)}")
        else:
            print(f"    - Todos quedaron a mas de {_TOPE_SUGERENCIA_PCT}% del precio real.")
            print("      A esa distancia no hay senal buena que valga: no subas el")
            print("      limite, fijate que esta leyendo mal el parser.")
        print("\n  No subas el limite para que entre una senal que el bot leyo mal.")
        print("  Ese es exactamente el caso que este filtro existe para frenar.")

    # Sin esta aclaracion el numero enganaria: reproducir mensajes viejos
    # contra precios de hoy da distancias enormes que en su momento no
    # existieron. El resultado solo es representativo con pocas horas.
    print("\n  OJO: la distancia se mide contra el precio de AHORA, no contra")
    print("  el de cuando llego el mensaje. Una senal de ayer va a dar una")
    print("  distancia grande aunque en su momento fuera perfecta.")
    print("  Para que este numero signifique algo, usa pocas horas:")
    print("      python -m tct simular --horas 2 --con-precios")


def _limite_holgado(pct: float) -> float:
    """El limite mas chico que dejaria pasar esa distancia, con un poco de
    aire para no quedar justo en el borde."""
    return math.ceil(pct * 10 + 1) / 10


# --------------------------------------------------------------------------
# probar
# --------------------------------------------------------------------------


def cmd_probar(args: argparse.Namespace) -> int:
    """Verifica la cadena completa contra MetaTrader 5, paso por paso.

    Chequea conexion, cuenta demo, AutoTrading, resolucion de simbolos y
    cotizaciones. Con --operar hace ademas la prueba de fuego: abre una
    posicion del tamano minimo y la cierra enseguida. Eso es lo unico que
    demuestra de verdad que el filling mode del broker es compatible, que es
    la parte del sistema que no se puede verificar sin operar.
    """
    if sys.platform != "win32":
        print("Este comando prueba MetaTrader 5 nativo, que solo existe en Windows.")
        return 1

    settings = load_settings(args.env_file)
    setup_logging(verbose=args.verbose)
    return asyncio.run(_probar_async(settings, args))


async def _probar_async(settings: Settings, args: argparse.Namespace) -> int:
    from tct.brokers.mt5_native import MT5NativeBroker
    from tct.signals.models import OrderType, Side

    fallos: list[str] = []
    # Lo que no impide operar pero el usuario tiene que saber. Sin este cajon,
    # un simbolo que este broker no expone se imprimia como "FALTA" a mitad de
    # la salida y el resumen final igual decia TODO EN ORDEN.
    avisos: list[str] = []

    def paso(numero: str, titulo: str) -> None:
        print(f"\n[{numero}] {titulo}")

    print("=" * 66)
    print("  PRUEBA DE LA CADENA COMPLETA CONTRA METATRADER 5")
    print("=" * 66)

    # --- 1. Conexion y cuenta -------------------------------------------
    paso("1/5", "Conectando con MetaTrader 5...")
    broker = MT5NativeBroker(settings)
    if not await broker.connect():
        print("      FALLO. Revisa arriba el motivo.")
        print("\n  Lo mas comun: MetaTrader cerrado, sin loguear, o Algo Trading")
        print("  apagado. 'python -m tct mt5' lo dice con mas detalle.")
        return 1
    print("      OK: conectado, cuenta demo y AutoTrading activo.")

    mt5 = broker._mt5
    try:
        cuenta = mt5.account_info()
        print(f"      {cuenta.company} | {cuenta.server} | {cuenta.balance} {cuenta.currency}")

        # --- 2. Resolucion de simbolos -----------------------------------
        paso("2/5", "Resolviendo los simbolos de ALLOWED_SYMBOLS contra el broker...")
        resueltos: dict[str, str] = {}
        for simbolo in sorted(settings.allowed_symbols):
            real = await asyncio.to_thread(broker._resolver_contra_broker, simbolo)
            if real:
                resueltos[simbolo] = real
                marca = "" if real == simbolo else f"  (el broker lo llama '{real}')"
                print(f"      OK    {simbolo}{marca}")
            else:
                print(f"      FALTA {simbolo}  <- este broker no lo expone")
                # No es cosmetico: ninguna senal de ese simbolo va a poder
                # operar nunca, y cada una igual consume cupo diario, porque
                # el contador se incrementa antes de llamar al broker.
                avisos.append(
                    f"{simbolo} no existe en este broker. Ninguna senal suya va a "
                    "poder operar, y cada una igual gasta cupo de "
                    "MAX_SIGNALS_PER_DAY.\n"
                    "     Sacalo de ALLOWED_SYMBOLS en el .env, o activalo en "
                    "Market Watch si tu broker si lo tiene."
                )
        if not resueltos:
            fallos.append("El broker no expone ninguno de los simbolos configurados")
            print("\n      Ninguno resolvio. Revisa ALLOWED_SYMBOLS en el .env.")

        # --- 3. Cotizaciones ---------------------------------------------
        paso("3/5", "Pidiendo cotizaciones...")
        con_precio: list[tuple[str, str, float]] = []
        sin_precio: list[str] = []
        for canonico, real in resueltos.items():
            info = await asyncio.to_thread(broker._ensure_symbol, real)
            tick = mt5.symbol_info_tick(real) if info else None
            if tick and tick.ask:
                con_precio.append((canonico, real, tick.ask))
                print(f"      OK    {canonico:<8} bid={tick.bid} ask={tick.ask}")
            else:
                print(f"      sin cotizacion: {canonico}  (mercado cerrado?)")
                sin_precio.append(canonico)
        if not con_precio:
            fallos.append("Ningun simbolo tiene cotizacion (puede ser el mercado cerrado)")
        elif sin_precio:
            # La consecuencia que no era evidente: sin cotizacion,
            # `market_price()` devuelve None y el contraste con el precio real
            # NO opina. Es la politica correcta (sin dato no se inventa un
            # rechazo), pero significa que esos simbolos entran sin ese filtro.
            avisos.append(
                "Sin cotizacion ahora: " + ", ".join(sin_precio) + ".\n"
                "     Suele ser el horario del instrumento y se arregla solo. Pero\n"
                "     mientras dure, el control contra el precio real NO puede opinar\n"
                "     sobre ellos: una senal de esos simbolos entra sin ese filtro."
            )

        # El control que compara la entrada del mensaje contra el precio real
        # se alimenta de `broker.market_price()`, que resuelve el simbolo por
        # su cuenta. Se prueba ese camino y no el tick de arriba: un simbolo
        # que cotiza pero que `market_price` no resuelve dejaria la proteccion
        # muda, y muda se ve igual que activa.
        controlando = (
            settings.max_spread_from_entry_pct > 0
            or settings.max_pending_distance_pct > 0
        )
        if controlando and con_precio:
            mudos = [c for c, _, _ in con_precio if await broker.market_price(c) is None]
            if mudos:
                print(f"      AVISO No hay precio medio para: {', '.join(mudos)}")
                print("            El control contra el precio de mercado no va a")
                print("            opinar sobre esos simbolos: van a pasar sin ese filtro.")
                fallos.append(
                    "El control contra el precio de mercado se queda sin datos en "
                    + ", ".join(mudos)
                )
            else:
                print(
                    f"      OK    control contra el precio de mercado con datos "
                    f"({settings.max_spread_from_entry_pct}% a mercado, "
                    f"{settings.max_pending_distance_pct}% pendientes)"
                )
        elif not controlando:
            print("      AVISO el control contra el precio de mercado esta APAGADO")
            print("            (MAX_SPREAD_FROM_ENTRY_PCT y MAX_PENDING_DISTANCE_PCT en 0)")

        # --- 4. Volumen minimo -------------------------------------------
        paso("4/5", "Verificando el lote configurado...")
        for canonico, real, _ in con_precio[:3]:
            info = await asyncio.to_thread(broker._ensure_symbol, real)
            volumen = broker._normalize_volume(info, settings.default_lot)
            if volumen is None:
                print(f"      FALLA {canonico}: DEFAULT_LOT={settings.default_lot} fuera de rango")
                fallos.append(f"DEFAULT_LOT invalido para {canonico}")
            else:
                aviso = "" if volumen == settings.default_lot else f"  (se ajusta a {volumen})"
                print(f"      OK    {canonico:<8} lote {settings.default_lot}{aviso} "
                      f"| min={info.volume_min} paso={info.volume_step}")

        # --- 5. Orden real -------------------------------------------------
        paso("5/5", "Prueba de orden real")
        if not args.operar:
            print("      SALTADA. Es la unica que demuestra que el filling mode")
            print("      del broker es compatible, y es lo que no se puede saber")
            print("      sin operar. Para hacerla:")
            print("\n          python -m tct probar --operar")
            print("\n      Abre una posicion del tamano minimo y la cierra enseguida.")
        elif not con_precio:
            print("      No se puede: ningun simbolo tiene cotizacion.")
            fallos.append("Sin cotizaciones no se pudo probar una orden")
        else:
            canonico, real, precio = next(
                ((c, r, p) for c, r, p in con_precio if c == args.simbolo), con_precio[0]
            )
            print(f"      Abriendo {canonico} ({real}) al minimo, para cerrarla enseguida...")

            apertura = await broker.open_order(
                symbol=canonico, side=Side.BUY, order_type=OrderType.MARKET,
                lot=settings.default_lot, entry=None, stop_loss=None, take_profit=None,
            )
            if not apertura.ok:
                print(f"      FALLO al abrir: {apertura.reason}")
                fallos.append(f"No se pudo abrir la orden de prueba: {apertura.reason}")
            else:
                print(f"      OK: abierta. ticket={apertura.ticket} precio={apertura.price}")
                cierre = await broker.close_position(
                    ticket=apertura.ticket, symbol=canonico, fraction=1.0
                )
                if cierre.ok:
                    print(f"      OK: cerrada. {cierre.reason}")
                else:
                    print(f"      FALLO al cerrar: {cierre.reason}")
                    fallos.append(
                        f"La posicion {apertura.ticket} se abrio pero NO se cerro. "
                        "Cerrala a mano en MetaTrader."
                    )
    finally:
        await broker.disconnect()

    # --- Resumen ---------------------------------------------------------
    print("\n" + "=" * 66)
    if fallos:
        print("  HAY PROBLEMAS")
        print("=" * 66)
        for i, f in enumerate(fallos, 1):
            print(f"  {i}. {f}")
        return 1

    # "TODO EN ORDEN" con avisos sin nombrar es como decia antes que estaba
    # todo bien mientras un simbolo entero no existia en el broker.
    print("  TODO EN ORDEN" if not avisos else "  EN ORDEN, CON AVISOS")
    print("=" * 66)
    for i, aviso in enumerate(avisos, 1):
        print(f"  {i}. {aviso}")
    if avisos:
        print()
    if args.operar:
        print("  La cadena completa funciona: conexion, simbolos, cotizaciones,")
        print("  y una orden real que se abrio y se cerro contra tu cuenta demo.")
    else:
        print("  Todo lo que se puede verificar sin operar esta bien.")
        print("  Falta la prueba de fuego:  python -m tct probar --operar")
    return 0


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

    # Interprete de respaldo. Si no esta disponible se avisa y se sigue: el
    # sistema funciona identico sin el, solo pierde los mensajes raros.
    ollama = None
    if settings.enable_ollama:
        from tct.intelligence.ollama import OllamaParser

        candidato = OllamaParser(settings)
        listo, detalle = await candidato.disponible()
        if listo:
            ollama = candidato
            logger.info("IA local: %s", detalle)
        else:
            logger.warning("IA local desactivada. %s", detalle)

    engine = Engine(settings, store, broker, notifier, ollama=ollama)
    reader = TelegramReader(settings, engine.handle_message)

    if not await reader.start():
        logger.error("No se pudo iniciar la lectura de Telegram. Abortando.")
        await broker.disconnect()
        return

    # Control remoto por Telegram. Se engancha al MISMO cliente que ya abrio
    # el lector: no hay segundo login ni otro archivo .session.
    control = None
    if settings.enable_telegram_control:
        from tct.telegram.control import ControlTelegram, escuchar_comandos

        control = ControlTelegram(settings, store, engine)
        if await escuchar_comandos(reader.client, settings, control) is None:
            # Sin control remoto, la unica forma de frenar el bot es la PC.
            # Con dinero real eso es demasiado poco, asi que no se arranca.
            if settings.is_live:
                logger.error(
                    "No se pudo activar el control por Telegram y esta instancia opera "
                    "con DINERO REAL. Se aborta: sin el, la unica forma de frenarlo "
                    "seria estar frente a la PC."
                )
                await reader.stop()
                await broker.disconnect()
                return
            control = None
            logger.warning("Sin control por Telegram. Solo se puede frenar desde la PC.")

    encabezado = "BOT REAL arrancado" if settings.is_live else "Bot arrancado"
    await notifier.send(
        f"{encabezado} [{settings.instance_name.upper()}]\n"
        f"Modo: {settings.trading_mode}\n"
        f"Escuchando {len(settings.telegram_source_chats)} chat(s)."
        + (f"\n\nPara frenarlo: /pausa {settings.instance_name}" if control else "")
    )

    if store.is_paused:
        logger.warning(
            "ARRANCA PAUSADO (%s). No va a operar hasta que mandes /reanudar %s",
            store.state.paused_reason or "sin motivo registrado", settings.instance_name,
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
    sub.add_parser("mt5", help="Lee tu cuenta de MetaTrader 5 y dice que poner en el .env")
    sub.add_parser("chatid", help="Averigua el chat id para las notificaciones de Telegram")

    simular = sub.add_parser(
        "simular", help="Reproduce los mensajes reales de hoy contra el sistema")
    simular.add_argument("--horas", type=int, default=24,
                         help="Cuantas horas hacia atras traer (por defecto 24)")
    simular.add_argument("--limite", type=int, default=200,
                         help="Maximo de mensajes por chat (por defecto 200)")
    simular.add_argument("--ejecutar", action="store_true",
                         help="Ejecutar de verdad. Sin esto solo muestra que pasaria.")
    simular.add_argument("--todos", action="store_true",
                         help="Mostrar tambien los mensajes que se descartan")
    simular.add_argument("--con-precios", action="store_true", dest="con_precios",
                         help="Comparar cada entrada contra el precio real de MT5 "
                              "(solo lee cotizaciones, no opera)")

    probar = sub.add_parser(
        "probar", help="Verifica la cadena completa contra MetaTrader 5")
    probar.add_argument("--operar", action="store_true",
                        help="Abrir y cerrar una posicion real de prueba en la demo")
    probar.add_argument("--simbolo", default="XAUUSD",
                        help="Simbolo para la prueba de orden (por defecto XAUUSD)")

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
        "mt5": cmd_mt5,
        "chatid": cmd_chatid,
        "simular": cmd_simular,
        "probar": cmd_probar,
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
