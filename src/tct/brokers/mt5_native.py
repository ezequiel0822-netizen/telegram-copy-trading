"""Broker MT5 nativo. SOLO Windows, y el camino recomendado ahi.

En Windows se habla directo con la terminal MT5 instalada en la maquina, sin
intermediarios ni servicios de terceros: menos latencia, menos piezas que
puedan fallar y nada que pagar. Es el motivo por el que conviene una PC
Windows dedicada antes que una Mac.

Fuera de Windows este modulo no puede funcionar: el paquete `MetaTrader5` solo
publica wheels `win_amd64`. `config.py` bloquea el modo con un mensaje claro y
en macOS el camino es MetaApi.

La logica dificil (negociacion de filling mode, normalizacion de volumen,
validacion de cuenta demo) esta portada de `app/brokers/mt5_demo_trader.py`
de tradingalertaIA, que ya la tenia resuelta contra brokers reales.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tct.brokers.base import Broker, OrderResult
from tct.brokers.symbol_map import to_broker_symbol
from tct.signals.models import OrderType, Side

# Con que se reconocen las ordenes de este bot en la cuenta.
MAGIA = 20260829

# Los codigos con que el paquete MetaTrader5 dice que se corto el canal con la
# terminal (MetaTrader5/__init__.py): envio y recepcion fallidos, sin conexion
# IPC, timeout. Pasa cuando MetaTrader se reinicia o se cierra con el bot
# andando, y el paquete NO se reengancha solo.
_SIN_TERMINAL = frozenset({-10001, -10002, -10004, -10005})

# Rechazos por precio: el broker contesta que la orden NO se ejecuto porque el
# precio se movio. No entro nada, asi que reintentar es seguro, pero lo decide
# el motor, que es el que puede volver a pasar el precio nuevo por el filtro de
# entrada tarde (ver `_open_sync`).
_RECOTIZACION = frozenset({10004, 10020, 10021})

logger = logging.getLogger(__name__)

# Otros nombres con los que un broker puede bautizar al mismo instrumento.
# Se prueban despues del nombre canonico, cuando la busqueda exacta falla.
_ALIAS_DE_BROKER: dict[str, tuple[str, ...]] = {
    "XAUUSD": ("GOLD", "XAUUSD.", "GOLDUSD"),
    "XAGUSD": ("SILVER", "SILVERUSD"),
    "NAS100": ("USTEC", "US100", "NDX100", "NASDAQ100", "TECH100", "USTECH"),
    "US30": ("DJ30", "DOW30", "WS30", "USA30", "DJIUSD"),
    "US500": ("SPX500", "SP500", "USA500", "US500Cash"),
    "GER40": ("DE40", "GER30", "DAX40", "DE30"),
    "UK100": ("FTSE100", "UKX", "GB100"),
    "USOIL": ("XTIUSD", "WTI", "CRUDOIL", "OIL"),
    "UKOIL": ("XBRUSD", "BRENT"),
    "BTCUSD": ("BITCOIN", "BTCUSDT"),
    "ETHUSD": ("ETHEREUM", "ETHUSDT"),
}


def elegir_nombre_de_simbolo(canonico: str, nombres: Iterable[str]) -> str | None:
    """Como se llama `canonico` entre los nombres que expone un broker, o None.

    El orden es lo que importa:
    1) Nombre exacto.
    2) Alias conocidos del instrumento (GOLD para XAUUSD, BITCOIN para BTCUSD).
    3) Los dos, con el sufijo del broker (XAUUSDm, XAUUSD.r, XAUUSD.s...).

    Solo se acepta un sufijo CORTO: si no, "EURUSD" se comeria "EURUSDT", que
    es otro instrumento (la cripto). Es puro a proposito: lo usa el bot para
    operar y `tct mt5` para calcular el margen, y asi los dos resuelven igual.
    """
    canonico = canonico.strip().upper()
    nombres = list(nombres)
    candidatos = [canonico, *_ALIAS_DE_BROKER.get(canonico, ())]
    for candidato in candidatos:
        for nombre in nombres:
            if nombre.upper() == candidato:
                return nombre
    for candidato in candidatos:
        for nombre in nombres:
            arriba = nombre.upper()
            if arriba.startswith(candidato) and len(arriba) - len(candidato) <= 4:
                resto = arriba[len(candidato):]
                if resto == "" or not resto[0].isalnum() or len(resto) <= 2:
                    return nombre
    return None


def modo_de_la_cuenta(mt5, account) -> str | None:
    """"hedging", "netting", o None si la terminal no lo informa.

    El bot da por hecho HEDGING: cada operacion es su propia posicion, con su
    ticket, su stop y su breakeven. En NETTING, MetaTrader junta todo lo de un
    simbolo en UNA posicion: una senal SELL con un BUY abierto CIERRA ese BUY
    en vez de vender, y mover el stop de una senal mueve el de la otra. FxPro
    es hedging y por eso nunca aparecio; al cambiar de broker, hay que mirarlo.
    Es puro a proposito: lo usan el bot al conectar y `tct mt5`.
    """
    modo = getattr(account, "margin_mode", None)
    if modo is None:
        return None
    if modo == getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2):
        return "hedging"
    if modo in (getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_NETTING", 0),
                getattr(mt5, "ACCOUNT_MARGIN_MODE_EXCHANGE", 1)):
        return "netting"
    return None


def _volumen_confirmado(result: Any, pedido: float) -> float:
    """El volumen que el broker dice haber ejecutado, o el pedido si no lo dice.

    `OrderSendResult.volume` es el volumen CONFIRMADO por el broker, y no tiene
    por que coincidir con el solicitado: un llenado parcial ejecuta menos. El
    motor arma el estado con este numero, asi que informar el pedido lo dejaba
    creyendo tener abierto mas de lo que hay, y calculando los cierres
    parciales sobre un lote que no existe.
    """
    ejecutado = getattr(result, "volume", None)
    try:
        ejecutado = float(ejecutado) if ejecutado is not None else 0.0
    except (TypeError, ValueError):
        ejecutado = 0.0
    return ejecutado or float(pedido)


# Codigo que devuelve MT5 cuando no pudo lanzar la terminal. Es el unico que
# apunta a un problema de RUTA y no de estado de la terminal.
_IPC_INITIALIZE_FAILED = -10003

# RES_E_AUTH_FAILED. La terminal esta ahi pero no hay sesion iniciada, o el
# login que se le paso no fue aceptado. Es un caso muy distinto de "no la
# encuentro", y merece su propia explicacion.
_AUTH_FAILED = -6

# RES_E_AUTO_TRADING_DISABLED. El boton verde de la barra esta apagado.
_AUTOTRADING_APAGADO = -8


def _motivo_de_cierre(mt5, reason) -> str:
    """Traduce el DEAL_REASON de MT5. Lo dice el broker, no se deduce.

    Deducirlo comparando precios se equivocaria justo en el caso que mas
    importa en este canal: un stop movido a breakeven cierra por SL a precio
    de entrada, y sin el motivo no hay como distinguirlo de una salida a mano.
    """
    if reason is None:
        return "otro"
    conocidos = {
        getattr(mt5, "DEAL_REASON_TP", 5): "tp",
        getattr(mt5, "DEAL_REASON_SL", 4): "sl",
        getattr(mt5, "DEAL_REASON_CLIENT", 0): "manual",
        getattr(mt5, "DEAL_REASON_MOBILE", 1): "manual",
        getattr(mt5, "DEAL_REASON_WEB", 2): "manual",
        getattr(mt5, "DEAL_REASON_EXPERT", 3): "programa",
    }
    return conocidos.get(reason, "otro")


def _pistas_de_initialize(codigo: int, mt5_path: str) -> list[str]:
    """Que hacer ante un initialize() fallido, en castellano y accionable.

    El mensaje crudo de MT5 nombra funciones internas ("IPC initialize failed")
    y no sugiere nada. Quien lo lee no programa: necesita saber que apretar, no
    como se llama la capa que fallo.
    """
    if codigo == _IPC_INITIALIZE_FAILED:
        if mt5_path:
            return [
                "No se pudo ARRANCAR MetaTrader desde esa ruta.",
                "Casi siempre la ruta esta mal escrita, o MetaTrader se instalo",
                "en otra carpeta. Para encontrar la verdadera: clic derecho en el",
                "acceso directo de MetaTrader 5 -> Propiedades -> 'Destino'.",
                "O directamente dejá MT5_PATH vacio en el .env y abri MetaTrader",
                "a mano antes de arrancar el bot.",
            ]
        return [
            "No se encontro ninguna terminal MetaTrader 5 para arrancar.",
            "Abri MetaTrader 5 a mano y volve a intentar, o completá MT5_PATH",
            "en el .env con la ruta a terminal64.exe.",
        ]

    if codigo == _AUTH_FAILED:
        # No es "no encuentro MetaTrader": es "esta ahi y no hay sesion".
        # Decir las tres causas genericas aca manda a revisar cosas que ya
        # estan bien, y la verdadera queda escondida entre ellas.
        return [
            "MetaTrader esta ahi, pero SIN LA CUENTA INICIADA.",
            "El bot no puede operar contra una terminal sin sesion.",
            "",
            "Abri MetaTrader y fijate abajo a la derecha: si dice 'Sin conexion'",
            "o no muestra el balance, esta deslogueada.",
            "  Archivo -> Iniciar sesion en cuenta de operaciones",
            "  y TILDA 'Guardar contrasena de la cuenta'.",
            "",
            "Sin ese tilde, cada reinicio de Windows te deja el bot sin poder",
            "arrancar hasta que entres a mano, y el arranque automatico no",
            "sirve de nada.",
            "",
            "Si la cuenta SI esta iniciada, entonces MT5_LOGIN/MT5_PASSWORD/",
            "MT5_SERVER del .env no coinciden con ella y el login fue rechazado.",
            "Corre 'tct mt5' con MetaTrader abierto: te dice que poner.",
        ]

    if codigo == _AUTOTRADING_APAGADO:
        return [
            "El boton 'Algo Trading' de MetaTrader esta APAGADO.",
            "Abrilo y apretalo hasta que quede verde, o presiona Ctrl+E.",
            "Sin eso ninguna orden va a entrar, aunque todo lo demas ande.",
        ]

    return [
        "Casi siempre es una de estas tres:",
        "  1. MetaTrader 5 no esta abierto. Abrilo.",
        "  2. Esta abierto pero sin loguear en ninguna cuenta.",
        "  3. Se abrio 'como administrador' y el bot no. Los dos tienen que",
        "     correr con el mismo nivel de permisos.",
    ]


class MT5NativeBroker(Broker):
    name = "mt5"

    def __init__(self, settings) -> None:
        self.settings = settings
        self._mt5 = None
        self._ready = False
        # Cache de simbolo canonico -> nombre real en este broker. None como
        # valor significa "ya se busco y no existe": evita repetir el barrido.
        self._symbol_cache: dict[str, str | None] = {}
        # Reconectar lo pueden pedir a la vez el vigilante y una orden: que lo
        # haga uno solo.
        self._reconectando = threading.Lock()

    # -- Ciclo de vida -----------------------------------------------------

    async def connect(self) -> bool:
        return await asyncio.to_thread(self._connect_sync)

    def _connect_sync(self) -> bool:
        try:
            import MetaTrader5 as mt5
        except ImportError:
            logger.error(
                "El paquete MetaTrader5 no esta instalado. Solo existe para Windows; "
                "en macOS usa TRADING_MODE=PAPER_ONLY o PAPER_AND_METAAPI_DEMO."
            )
            return False

        self._mt5 = mt5
        kwargs: dict[str, Any] = {}
        if self.settings.mt5_path:
            # Se verifica ANTES de llamar a initialize(), porque el error que
            # devuelve MT5 cuando la ruta no existe es
            #     (-10003, "IPC initialize failed, Process create failed '<ruta>'")
            # que no dice que el problema sea la ruta, ni que la ruta salga del
            # .env, ni que se pueda dejar vacia. Una sola letra de menos en el
            # nombre de la carpeta ("MetaTrade 5") produce exactamente eso.
            if not Path(self.settings.mt5_path).exists():
                logger.error(
                    "MT5_PATH apunta a un archivo que no existe:\n"
                    "            %s\n"
                    "        Corregilo en el .env, o dejalo VACIO (MT5_PATH=) y abri\n"
                    "        MetaTrader 5 a mano antes de arrancar el bot: sin ruta, se\n"
                    "        conecta a la terminal que ya este abierta y no hace falta\n"
                    "        acertarle a la ruta.",
                    self.settings.mt5_path,
                )
                return False
            kwargs["path"] = self.settings.mt5_path

        if not mt5.initialize(**kwargs):
            codigo, mensaje = mt5.last_error()
            logger.error("mt5.initialize() fallo: %s (codigo %s)", mensaje, codigo)
            for linea in _pistas_de_initialize(codigo, self.settings.mt5_path):
                logger.error("        %s", linea)
            return False

        if self.settings.mt5_login and self.settings.mt5_password and self.settings.mt5_server:
            try:
                login = int(self.settings.mt5_login)
            except ValueError:
                logger.error("MT5_LOGIN tiene que ser numerico")
                return False
            if not mt5.login(
                login, password=self.settings.mt5_password, server=self.settings.mt5_server
            ):
                logger.error("mt5.login() fallo: %s", mt5.last_error())
                return False

        # El boton "AutoTrading" de la barra de MT5. Si esta apagado, todo
        # parece funcionar hasta que la primera orden vuelve con retcode
        # 10027 y un mensaje cripto. Se chequea aca para que el problema
        # aparezca al arrancar y con una instruccion concreta, no a mitad de
        # una senal real.
        terminal = mt5.terminal_info()
        if terminal is not None and getattr(terminal, "trade_allowed", True) is False:
            logger.error(
                "MT5 tiene el AutoTrading APAGADO: ninguna orden va a entrar.\n"
                "        Abri MetaTrader 5 y apreta el boton 'Algo Trading' de la barra\n"
                "        de arriba (tiene que quedar verde), o presiona Ctrl+E."
            )
            return False

        account = mt5.account_info()
        if account is None:
            logger.error("No se pudo leer account_info() de MT5")
            return False

        # La cuenta a la que se LLEGO tiene que ser la que dice el .env.
        #
        # Nada lo garantizaba: si falta alguna credencial no se llama a
        # `login()`, y si MT5_PATH esta vacio `initialize()` se engancha a la
        # terminal que encuentre. Las dos cosas terminan igual -operando una
        # cuenta que nadie eligio- y hasta ahora el unico rastro era la linea
        # 'MT5 listo | servidor=...' del arranque, que nadie mira cuando el bot
        # levanta solo. Con dos terminales instaladas y dos cuentas del mismo
        # broker, esto deja de ser hipotetico.
        if self.settings.mt5_login:
            try:
                esperado = int(self.settings.mt5_login)
            except ValueError:
                logger.error("MT5_LOGIN tiene que ser numerico")
                return False
            if account.login != esperado:
                logger.error(
                    "La terminal quedo en OTRA cuenta:\n"
                    "            el .env pide  %s\n"
                    "            y se conecto a %s (%s)\n"
                    "        No se opera nada. Casi siempre es una de dos:\n"
                    "          1. MT5_PATH apunta a la terminal equivocada, o esta\n"
                    "             vacio y se engancho a la primera que encontro.\n"
                    "          2. La password o el servidor estan mal y el login\n"
                    "             fallo sin cambiar la cuenta que ya estaba cargada.",
                    esperado,
                    account.login,
                    account.server,
                )
                return False

        # Una cuenta NETTING rompe la idea de "una senal, una posicion" (ver
        # `modo_de_la_cuenta`). No se opera: una SELL cerraria el BUY de otra
        # senal. Si la terminal no lo informa, no se inventa un motivo.
        if modo_de_la_cuenta(mt5, account) == "netting":
            logger.error(
                "La cuenta %s es NETTING: MetaTrader junta todo lo de un simbolo\n"
                "        en UNA sola posicion. El bot necesita una cuenta HEDGING, donde\n"
                "        cada operacion es su propia posicion.\n"
                "        En netting, una senal SELL con un BUY abierto CIERRA ese BUY en\n"
                "        vez de vender, y el stop de una senal pisa el de la otra.\n"
                "        No se opera nada. El tipo se elige al abrir la cuenta: abri una\n"
                "        HEDGING (si no aparece la opcion, preguntale al broker).",
                account.login,
            )
            return False

        ok, reason = self._ensure_demo(account._asdict())
        if not ok:
            logger.error("MT5: %s", reason)
            return False

        self._ready = True
        # Se guarda para poder decirlo despues. Con DOS bots corriendo, "contra
        # que cuenta esta este" es la pregunta que mas importa y la unica que
        # no se puede contestar desde el telefono: /estado decia "Broker: mt5"
        # en los dos, que es cierto y no sirve para nada. Si los dos apuntan a
        # la misma terminal -un MT5_PATH mal puesto- nada avisa.
        self.cuenta = f"{account.server} #{account.login}"
        logger.info("MT5 listo | servidor=%s balance=%s", account.server, account.balance)
        return True

    async def disconnect(self) -> None:
        if self._mt5 is not None:
            await asyncio.to_thread(self._mt5.shutdown)
        self._ready = False

    async def is_ready(self) -> bool:
        return self._ready and self._mt5 is not None

    # -- Reconexion ----------------------------------------------------------
    #
    # `initialize()` se llamaba UNA vez, al arrancar. Si MetaTrader se
    # reiniciaba -se colgo, o alguien lo cerro y lo volvio a abrir- el paquete
    # perdia el canal y no se reenganchaba solo: todas las senales siguientes
    # terminaban en "no se pudo leer en que cuenta esta la terminal", y un
    # breakeven pendiente no se movia, hasta que alguien reiniciara el bot a
    # mano y escribiera la clave. Ahora se reconecta solo, por los dos lados:
    # el vigilante de `tct run` cada 30 segundos, y la propia orden si
    # encuentra el canal cortado.

    def _se_corto_la_terminal(self) -> bool:
        try:
            return self._mt5.last_error()[0] in _SIN_TERMINAL
        except Exception:
            return False

    def _reconectar_sync(self) -> bool:
        """Vuelve a hacer el arranque entero: initialize, login, AutoTrading y
        la cuenta del .env. Si MetaTrader volvio en OTRA cuenta, no reconecta.
        Nunca manda una orden."""
        with self._reconectando:
            try:
                if self._mt5.terminal_info() is not None:
                    return True  # otro hilo ya reconecto mientras se esperaba
            except Exception:
                pass
            logger.warning("Se corto la conexion con MetaTrader (se reinicio o se "
                           "cerro). Reconectando...")
            try:
                self._mt5.shutdown()
            except Exception:
                pass
            if self._connect_sync():
                logger.warning("MetaTrader: reconectado a %s.", self.cuenta)
                return True
            logger.error("MetaTrader: NO se pudo reconectar. No se abre ni se mueve nada "
                         "hasta que vuelva; se reintenta solo cada 30 segundos.")
            return False

    async def revisar_conexion(self) -> None:
        """Para el vigilante de `tct run`: si la terminal no contesta, reconecta."""
        if not await self.is_ready():
            return
        await asyncio.to_thread(self._revisar_conexion_sync)

    def _revisar_conexion_sync(self) -> None:
        try:
            viva = self._mt5.terminal_info() is not None
        except Exception:
            viva = False
        if not viva:
            self._reconectar_sync()

    def _cuenta_sigue_siendo_la_del_env(self) -> str:
        """"" si la terminal sigue en la cuenta del .env, o el motivo para no operar.

        La verificacion de `connect()` corre UNA vez, al arrancar. Con dos
        cuentas del mismo broker en la MISMA terminal -el plan del usuario: la
        demo de FxPro y la real conviven ahi- alcanza con que alguien loguee la
        terminal en la otra cuenta con el bot andando para que todas las ordenes
        siguientes vayan a la cuenta equivocada. Reproducido: el bot de la demo
        -que corre sin topes y sin freno diario- abrio en la cuenta REAL, y el
        resultado volvio ok=True, "orden ejecutada".

        Por eso se pregunta antes de CADA `order_send`, y tambien antes de dar
        el equity: el freno diario comparando contra el saldo de otra cuenta es
        otra forma de mentir.

        AL REVES QUE EL RESTO DEL BOT: aca, sin dato, NO se opera. La regla de
        §9 -"sin dato no se inventa un rechazo"- vale para el equity y para la
        cotizacion, donde lo que se arriesga es perder una senal. No saber en
        que cuenta se esta es otra cosa: el lado barato es no mandar nada.

        Sin `MT5_LOGIN` no hay contra que comparar (una sola cuenta, el .env no
        la nombra) y no se opina: engancharse a la terminal que haya abierta es
        lo documentado para ese caso.
        """
        if not self.settings.mt5_login:
            return ""
        try:
            esperado = int(self.settings.mt5_login)
        except ValueError:
            return "MT5_LOGIN no es numerico"
        try:
            cuenta = self._mt5.account_info()
        except Exception:
            cuenta = None
        if cuenta is None and self._se_corto_la_terminal() and self._reconectar_sync():
            # MetaTrader se reinicio: reconectado, se vuelve a preguntar. La
            # reconexion ya verifico la cuenta, pero la pregunta es esta.
            try:
                cuenta = self._mt5.account_info()
            except Exception:
                cuenta = None
        if cuenta is None:
            return "no se pudo leer en que cuenta esta la terminal"
        actual = getattr(cuenta, "login", None)
        if actual != esperado:
            return (f"la terminal esta en la cuenta {actual} y este bot es de la "
                    f"{esperado}: primero se cierra el bot, despues se toca la cuenta")
        return ""

    def _ensure_demo(self, account: dict[str, Any]) -> tuple[bool, str]:
        # El chequeo se saltea SOLO con las dos llaves: `is_live` exige
        # TRADING_MODE=LIVE y ALLOW_LIVE_TRADING=true. Antes miraba solo la
        # segunda, y con TRADING_MODE=AUTO una cuenta real pasaba como demo.
        # `config.py` ya rechaza esa combinacion al cargar; esto es la segunda
        # red, para Settings armados sin pasar por `load_settings`.
        if getattr(self.settings, "is_live", False):
            return True, "TRADING_MODE=LIVE y ALLOW_LIVE_TRADING=true, chequeo de demo omitido"
        if account.get("trade_allowed") is False:
            return False, "La cuenta tiene trade_allowed=false"

        demo_const = getattr(self._mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_const is not None and account.get("trade_mode") == demo_const:
            return True, "ok"

        haystack = " ".join(
            str(account.get(key) or "") for key in ("server", "company", "name")
        ).upper()
        if "DEMO" in haystack:
            return True, "ok"

        return False, (
            "La cuenta no es demo. Se bloquea la ejecucion. Para operar una "
            "cuenta real hacen falta TRADING_MODE=LIVE y ALLOW_LIVE_TRADING=true."
        )

    async def account_equity(self) -> float | None:
        if not await self.is_ready():
            return None
        return await asyncio.to_thread(self._equity_sync)

    def _equity_sync(self) -> float | None:
        # El equity de otra cuenta es peor que no tener equity: el freno diario
        # compararia el saldo de hoy contra el de una cuenta que no es esta.
        motivo = self._cuenta_sigue_siendo_la_del_env()
        if motivo:
            logger.error("No se lee el equity: %s", motivo)
            return None
        try:
            cuenta = self._mt5.account_info()
        except Exception:
            logger.warning("No se pudo leer el equity de MT5", exc_info=True)
            return None
        return float(cuenta.equity) if cuenta is not None else None

    async def desenlace_de(self, ticket: int | None) -> dict[str, Any] | None:
        if ticket is None or not await self.is_ready():
            return None
        return await asyncio.to_thread(self._desenlace_sync, ticket)

    def _desenlace_sync(self, ticket: int) -> dict[str, Any] | None:
        """Lee el historial de una posicion. NO manda ordenes de ningun tipo."""
        try:
            deals = self._mt5.history_deals_get(position=ticket)
        except Exception:
            logger.debug("No se pudo leer el historial de %s", ticket, exc_info=True)
            return None

        if not deals:
            # Puede ser que la posicion siga abierta, o que MT5 todavia no
            # tenga ese tramo del historial cargado. En los dos casos el dato
            # es "no se sabe", que no es lo mismo que "no paso nada".
            return None

        # Un cierre es OUT, y tambien OUT_BY: cerrar una posicion contra otra
        # opuesta ("close by") no deja un OUT, y sin contarlo la operacion
        # figuraba como "sigue abierta" y su plata no entraba al neto.
        salidas = {getattr(self._mt5, "DEAL_ENTRY_OUT", 1),
                   getattr(self._mt5, "DEAL_ENTRY_OUT_BY", 3)}
        cierres = [d for d in deals if getattr(d, "entry", None) in salidas]
        if not cierres:
            return None

        # El precio al que ENTRO de verdad. El bot pone el breakeven ahi, no en
        # el numero del mensaje, asi que es contra este precio que se decide si
        # un cierre por stop fue breakeven o stop. Contra el del mensaje, un
        # llenado 3 puntos corrido -pasa, medido- contaba un breakeven como stop.
        entrada_codigo = getattr(self._mt5, "DEAL_ENTRY_IN", 0)
        entradas = [d for d in deals if getattr(d, "entry", None) == entrada_codigo]
        precio_entrada = (float(getattr(entradas[0], "price", 0.0) or 0.0) or None) if entradas else None

        # Con cierres parciales hay varios. El ultimo es el que termino de
        # cerrar la posicion; el profit se suma, porque el resultado de la
        # operacion es el total y no el del ultimo pedazo.
        ultimo = cierres[-1]

        # Lo que la cuenta se movio de verdad no es solo `profit`. MT5 trae
        # comision, swap y fee en campos APARTE, y la comision se cobra casi
        # siempre en el deal de ENTRADA, que `cierres` deja afuera. Por eso los
        # costos se suman sobre TODOS los deals de la posicion. Antes el informe
        # decia "Resultado neto" sumando solo `profit`: a 0.01 lotes, con
        # resultados de +-1 dolar, la comision y el swap son del tamano del
        # resultado mismo y pueden darle vuelta el signo.
        def _suma(campo: str, que_deals) -> float:
            return sum(float(getattr(d, campo, 0.0) or 0.0) for d in que_deals)

        bruto = _suma("profit", cierres)
        comision = _suma("commission", deals)
        swap = _suma("swap", deals)
        fee = _suma("fee", deals)
        return {
            "precio": float(getattr(ultimo, "price", 0.0) or 0.0),
            "precio_entrada": precio_entrada,
            "profit": bruto,
            "comision": comision,
            "swap": swap,
            "fee": fee,
            "neto": bruto + comision + swap + fee,
            "motivo": _motivo_de_cierre(self._mt5, getattr(ultimo, "reason", None)),
            "cerrada_en": getattr(ultimo, "time", None),
        }

    async def posicion_existe(self, ticket: int | None) -> bool | None:
        if ticket is None or not await self.is_ready():
            return None
        return await asyncio.to_thread(self._posicion_existe_sync, ticket)

    def _posicion_existe_sync(self, ticket: int) -> bool | None:
        # En otra cuenta, "no esta" es mentira: la posicion vive en la cuenta
        # de este bot. Sin esto, con la terminal logueada en la demo, el motor
        # borraba del registro las posiciones REALES vivas -sin breakeven y
        # fuera de los topes- y abria mas. None es "no se sabe": se conservan.
        motivo = self._cuenta_sigue_siendo_la_del_env()
        if motivo:
            logger.error("No se revisa la posicion %s: %s", ticket, motivo)
            return None
        try:
            posiciones = self._mt5.positions_get(ticket=ticket)
        except Exception:
            logger.warning("No se pudo consultar la posicion %s", ticket, exc_info=True)
            return None

        # None y () NO son lo mismo, y confundirlos cuesta caro en la direccion
        # peligrosa: None es un error de consulta (terminal caida) y ahi la
        # posicion puede estar viva; solo la tupla vacia significa "no esta".
        if posiciones is None:
            return None
        if len(posiciones) > 0:
            return True

        # Todavia puede estar viva como ORDEN PENDIENTE, que vive en otra lista.
        # Sin preguntar aca, el motor la daba por "se cerro sola en el broker" y
        # la sacaba del registro: la orden seguia en la cuenta y podia
        # dispararse despues, abriendo una posicion REAL que el bot ya no
        # gestiona -sin breakeven, sin parcial, y sin ocupar lugar en
        # MAX_OPEN_TRADES-.
        try:
            ordenes = self._mt5.orders_get(ticket=ticket)
        except Exception:
            logger.warning("No se pudo consultar la orden %s", ticket, exc_info=True)
            return None
        if ordenes is None:
            return None
        return len(ordenes) > 0

    async def market_price(self, symbol: str) -> float | None:
        if not await self.is_ready():
            return None
        return await asyncio.to_thread(self._market_price_sync, symbol)

    def _market_price_sync(self, symbol: str) -> float | None:
        """Precio medio del instrumento, o None si el broker no lo da.

        Se resuelve el nombre igual que al abrir (`_resolver_contra_broker`,
        que ademas cachea), asi el control contra el mercado y la orden miran
        exactamente el mismo simbolo. Si divergieran, el control validaria un
        instrumento y la orden entraria en otro, que es justo el error que
        este chequeo existe para atajar.
        """
        try:
            broker_symbol = self._resolver_contra_broker(symbol) or to_broker_symbol(
                symbol, self.settings.mt5_broker_profile
            )
            if self._ensure_symbol(broker_symbol) is None:
                return None
            tick = self._mt5.symbol_info_tick(broker_symbol)
        except Exception:
            logger.warning("No se pudo leer la cotizacion de %s", symbol, exc_info=True)
            return None

        if tick is None:
            return None

        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        # Fuera de horario un lado puede venir en cero. Con uno solo alcanza:
        # la tolerancia se mide en puntos porcentuales y el spread no la mueve.
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        return bid or ask or None

    # -- Operaciones -------------------------------------------------------

    async def open_order(
        self,
        *,
        symbol: str,
        side: Side,
        order_type: OrderType,
        lot: float,
        entry: float | None,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "open", "MT5 no esta conectado", symbol=symbol)
        return await asyncio.to_thread(
            self._open_sync, symbol, side, order_type, lot, entry, stop_loss, take_profit
        )

    def _open_sync(
        self,
        symbol: str,
        side: Side,
        order_type: OrderType,
        lot: float,
        entry: float | None,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> OrderResult:
        mt5 = self._mt5

        # Antes de CADA orden: la terminal puede haber cambiado de cuenta con
        # el bot andando (dos cuentas del mismo broker, una sola terminal).
        motivo = self._cuenta_sigue_siendo_la_del_env()
        if motivo:
            logger.error("NO se abrio nada: %s", motivo)
            return OrderResult(False, "open", f"No se abrio nada: {motivo}",
                               symbol=symbol)

        # Primero se le pregunta al broker como se llama el instrumento; el
        # perfil de sufijos del .env queda como respaldo por si la terminal
        # todavia no tiene la lista cargada.
        broker_symbol = self._resolver_contra_broker(symbol) or to_broker_symbol(
            symbol, self.settings.mt5_broker_profile
        )

        info = self._ensure_symbol(broker_symbol)
        if info is None:
            return OrderResult(
                False, "open", f"El broker no expone el simbolo {broker_symbol}", symbol=symbol
            )

        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return OrderResult(False, "open", f"Sin cotizacion para {broker_symbol}", symbol=symbol)

        is_buy = side is Side.BUY
        market_price = tick.ask if is_buy else tick.bid

        volume = self._normalize_volume(info, lot)
        if volume is None:
            return OrderResult(
                False, "open", f"Volumen {lot} fuera de los limites de {broker_symbol}", symbol=symbol
            )

        # MAX_LOT es un techo, no una sugerencia, y este es el unico lugar donde
        # se conoce el numero definitivo. `_normalize_volume` puede SUBIR el
        # lote hasta el minimo del instrumento: un indice con volume_min=0.1
        # convierte un DEFAULT_LOT de 0.01 en una posicion diez veces mas
        # grande, y risk.py no lo ve porque compara default_lot contra max_lot,
        # nunca el volumen que se manda. Con los ALLOWED_SYMBOLS de fabrica
        # (NAS100, US30, US500) es una configuracion perfectamente posible.
        #
        # Solo aplica al ABRIR. Cerrar por encima del techo tiene que poder
        # hacerse siempre: negarse a cerrar es mucho peor que abrir de mas, y
        # ademas ahi la posicion ya existe.
        max_lot = getattr(self.settings, "max_lot", 0) or 0
        if max_lot and volume > max_lot + 1e-9:
            return OrderResult(
                False, "open",
                f"El lote minimo de {broker_symbol} es {volume} y supera MAX_LOT={max_lot}. "
                f"No se abre nada. Para operar este instrumento hay que poner "
                f"MAX_LOT={volume} en el .env, sabiendo que cada operacion suya va a "
                f"ser de ese tamano.",
                symbol=symbol, lot=volume,
            )

        if order_type is OrderType.MARKET or entry is None:
            action = mt5.TRADE_ACTION_DEAL
            mt5_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
            price = market_price
        else:
            action = mt5.TRADE_ACTION_PENDING
            price = entry
            # LIMIT espera a que el precio vuelva; STOP a que rompa. Cual de
            # los dos corresponde depende de si la entrada esta por encima o
            # por debajo del mercado, no solo de lo que dijo el mensaje.
            if order_type is OrderType.LIMIT:
                mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if is_buy else mt5.ORDER_TYPE_SELL_LIMIT
            else:
                mt5_type = mt5.ORDER_TYPE_BUY_STOP if is_buy else mt5.ORDER_TYPE_SELL_STOP

        request = {
            "action": action,
            "symbol": broker_symbol,
            "volume": volume,
            "type": mt5_type,
            "price": float(price),
            "deviation": 20,
            "magic": MAGIA,
            "comment": "tct-copy",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        if stop_loss is not None:
            request["sl"] = float(stop_loss)
        if take_profit is not None:
            request["tp"] = float(take_profit)

        pendiente = action != mt5.TRADE_ACTION_DEAL
        # Lo que este bot ya tenia en el simbolo ANTES de mandar: si order_send
        # no contesta, es la unica forma de reconocer despues si la orden entro.
        antes = self._tickets_propios(broker_symbol, pendiente)

        hecho = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
        parcial = getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
        colocada = getattr(mt5, "TRADE_RETCODE_PLACED", 10008)

        # Los brokers no coinciden en que modo de llenado aceptan y devuelven
        # 10030 (unsupported filling mode) sin decir cual sirve. Se prueban en
        # orden hasta que uno pase.
        last_result = None
        modos = self._filling_modes(info)
        cual = 0
        while cual < len(modos):
            request["type_filling"] = modos[cual]
            result = mt5.order_send(request)
            last_result = result
            if result is None or (result.retcode == colocada and not pendiente):
                # Sin respuesta, la orden pudo haber llegado igual: un corte al
                # RECIBIR la contestacion no deshace lo que el servidor ya
                # ejecuto. Antes se reenviaba con el modo de llenado siguiente,
                # y eso podia abrir una SEGUNDA posicion real que el bot no
                # gestionaba. Ahora nunca se reenvia: se mira la cuenta.
                return self._orden_sin_respuesta(broker_symbol, symbol, pendiente, antes,
                                                 volume, result, tipo=mt5_type)
            if (result.retcode == hecho
                    or (result.retcode == parcial and not pendiente)
                    or (result.retcode == colocada and pendiente)):
                if result.retcode == parcial:
                    logger.warning("El broker lleno solo una parte: %s de %s lotes.",
                                   getattr(result, "volume", "?"), volume)
                return OrderResult(
                    ok=True,
                    action="open",
                    reason="orden ejecutada",
                    ticket=int(result.order or result.deal or 0) or None,
                    price=float(result.price or price),
                    # El volumen CONFIRMADO por el broker, no el que se pidio.
                    # MT5 puede llenar menos de lo solicitado, y el motor
                    # construye el estado con este numero: informar el pedido
                    # dejaba al bot creyendo tener abierto mas de lo que hay.
                    lot=_volumen_confirmado(result, volume),
                    symbol=symbol,
                    raw={"retcode": result.retcode, "comment": result.comment},
                )
            if result.retcode in _RECOTIZACION and not pendiente:
                # El precio se movio y el broker no ejecuto: no entro nada. NO
                # se reintenta aca. El broker no conoce la senal, y reintentar
                # con la cotizacion nueva se salteaba el filtro de entrada
                # tarde: una entrada 4432 abrio a 4440.5, con el tope en 0.05%.
                # El motor vuelve a pasar el precio por el filtro y recien ahi
                # reintenta (`Engine._send_open`).
                return OrderResult(
                    False, "open",
                    f"El broker pidio otro precio (retcode {result.retcode}): no entro nada",
                    symbol=symbol, lot=volume,
                    raw={"retcode": result.retcode, "recotizacion": True},
                )
            if result.retcode != getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030):
                break  # el rechazo no es por filling mode: no tiene sentido reintentar
            cual += 1

        reason = (
            f"order_send rechazado: retcode={last_result.retcode} {last_result.comment}"
            if last_result is not None
            else f"order_send devolvio None: {mt5.last_error()}"
        )
        # El retcode viaja en `raw` y no solo dentro del texto del motivo: hay
        # rechazos que NO son un defecto del sistema (10018, mercado cerrado) y
        # quien los recibe tiene que poder distinguirlos sin parsear una frase.
        return OrderResult(
            False, "open", reason, symbol=symbol, lot=volume,
            raw={"retcode": last_result.retcode} if last_result is not None else {},
        )

    def _tickets_propios(self, broker_symbol: str, pendiente: bool) -> set[int] | None:
        """Los tickets de este bot en el simbolo: posiciones Y ordenes. None si
        no se pudo preguntar.

        Las dos listas, siempre. Una pendiente del bot que se dispara mientras
        se espera la respuesta pasa de ordenes a posiciones CON EL MISMO
        ticket; si `antes` no la tenia, se la tomaba por la orden nueva y dos
        senales quedaban registradas sobre una sola posicion.
        """
        try:
            posiciones = self._mt5.positions_get(symbol=broker_symbol)
            ordenes = self._mt5.orders_get(symbol=broker_symbol)
        except Exception:
            return None
        if posiciones is None or ordenes is None:
            return None
        return {int(p.ticket) for p in (*posiciones, *ordenes)
                if getattr(p, "magic", None) == MAGIA}

    def _orden_sin_respuesta(self, broker_symbol: str, symbol: str, pendiente: bool,
                             antes: set[int] | None, volume: float, result: Any,
                             tipo: int | None = None) -> OrderResult:
        """order_send no confirmo: se busca en la cuenta si la orden entro.

        Se pregunta unas veces durante ~1,5 segundos, y hasta ~5 si hay una
        orden propia en curso (aceptada y todavia ejecutandose: vive un rato en
        las ordenes antes de ser posicion). Si el canal con la terminal se
        corto -el caso tipico de un order_send sin respuesta es que MetaTrader
        se reinicio- se reconecta para poder mirar.

        Lo que se encuentra se devuelve como abierto, para que el motor lo
        gestione. Lo que no, NUNCA se afirma que "no entro": vuelve como
        `sin_confirmar`, y el motor lo sigue buscando (`buscar_sin_registrar`).
        """
        detalle = (f"retcode={result.retcode}" if result is not None
                   else f"devolvio None: {self._mt5.last_error()}")
        reconecto = False
        despues = None
        intento = 0
        limite = 4
        while intento < limite:
            if intento:
                time.sleep(0.5)
            intento += 1
            despues = self._tickets_propios(broker_symbol, pendiente)
            if despues is None and not reconecto and self._se_corto_la_terminal():
                reconecto = True
                self._reconectar_sync()
                limite += 1
                continue
            if antes is None or despues is None:
                continue
            for ticket in sorted(despues - antes, reverse=True):
                encontrada = self._propia(ticket, pendiente)
                if encontrada is None:
                    # Todavia es una orden en curso (a mercado): esperar.
                    limite = 10
                    continue
                if tipo is not None and getattr(encontrada, "type", tipo) != tipo:
                    continue
                logger.warning("order_send no confirmo (%s), pero la orden SI entro: "
                               "ticket %s.", detalle, ticket)
                return OrderResult(
                    ok=True, action="open",
                    reason="orden ejecutada (order_send no confirmo; se encontro en la cuenta)",
                    ticket=ticket,
                    price=float(getattr(encontrada, "price_open", 0) or 0) or None,
                    lot=float(getattr(encontrada, "volume_current",
                                      getattr(encontrada, "volume", volume)) or volume),
                    symbol=symbol, raw={"sin_respuesta": True},
                )
        logger.error(
            "order_send no confirmo (%s) y la orden no aparecio en la cuenta todavia.\n"
            "        El bot la sigue buscando y, si aparece, la toma bajo su gestion.\n"
            "        Si no aparece en unos minutos, no entro.", detalle)
        return OrderResult(False, "open",
                           f"order_send no confirmo ({detalle}) y la orden no aparecio "
                           "todavia en la cuenta: el bot la sigue buscando",
                           symbol=symbol, lot=volume,
                           raw={"sin_respuesta": True, "sin_confirmar": True})

    def _propia(self, ticket: int, pendiente: bool):
        """La posicion (o, si es pendiente, la orden) con ese ticket, o None."""
        consulta = self._mt5.orders_get if pendiente else self._mt5.positions_get
        try:
            return (consulta(ticket=ticket) or [None])[0]
        except Exception:
            return None

    async def buscar_sin_registrar(self, *, symbol: str, side: Side,
                                   conocidos: set[int]) -> OrderResult | None:
        """Una posicion de ESTE bot en el simbolo y el lado pedidos que el motor
        no tiene registrada, o None. Es como aparece despues una orden que
        order_send no confirmo."""
        if not await self.is_ready():
            return None
        return await asyncio.to_thread(self._buscar_sin_registrar_sync, symbol, side,
                                       conocidos)

    def _buscar_sin_registrar_sync(self, symbol: str, side: Side,
                                   conocidos: set[int]) -> OrderResult | None:
        broker_symbol = self._resolver_contra_broker(symbol) or to_broker_symbol(
            symbol, self.settings.mt5_broker_profile)
        try:
            posiciones = self._mt5.positions_get(symbol=broker_symbol)
        except Exception:
            return None
        tipo = (self._mt5.POSITION_TYPE_BUY if side is Side.BUY
                else self._mt5.POSITION_TYPE_SELL)
        for p in posiciones or ():
            if (getattr(p, "magic", None) == MAGIA and getattr(p, "type", None) == tipo
                    and int(p.ticket) not in conocidos):
                return OrderResult(
                    True, "open", "orden sin confirmar: aparecio en la cuenta",
                    ticket=int(p.ticket),
                    price=float(getattr(p, "price_open", 0) or 0) or None,
                    lot=float(getattr(p, "volume", 0) or 0) or None,
                    symbol=symbol, raw={"sin_respuesta": True},
                )
        return None

    async def close_position(
        self, *, ticket: int | None, symbol: str, fraction: float = 1.0
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "close", "MT5 no esta conectado", symbol=symbol)
        if ticket is None:
            return OrderResult(False, "close", "Falta el ticket de la posicion", symbol=symbol)
        return await asyncio.to_thread(self._close_sync, ticket, symbol, fraction)

    def _close_sync(self, ticket: int, symbol: str, fraction: float) -> OrderResult:
        mt5 = self._mt5
        action = "close" if fraction >= 1.0 else "partial_close"

        # Antes de CADA orden: la terminal puede haber cambiado de cuenta con
        # el bot andando (dos cuentas del mismo broker, una sola terminal).
        motivo = self._cuenta_sigue_siendo_la_del_env()
        if motivo:
            logger.error("NO se cerro nada: %s", motivo)
            return OrderResult(False, action, f"No se cerro nada: {motivo}",
                               ticket=ticket, symbol=symbol)

        positions = mt5.positions_get(ticket=ticket)
        # None y () NO son lo mismo, y confundirlos cuesta caro en las dos
        # direcciones. None es un error de consulta (terminal caida, sin
        # conexion): ahi la posicion puede estar perfectamente viva y darla por
        # cerrada la dejaria corriendo sin registro. () es "la busque y no
        # esta", que es informacion buena.
        if positions is None:
            return OrderResult(
                False, action,
                f"No se pudo consultar la posicion {ticket}: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        if not positions:
            return OrderResult(
                False, action,
                f"La posicion {ticket} ya no existe en MT5: la cerro el SL o el TP, "
                "o la cerraste a mano. No habia nada que cerrar.",
                ticket=ticket, symbol=symbol, raw={"ausente": True},
            )
        position = positions[0]

        info = self._ensure_symbol(position.symbol)
        volume = position.volume if fraction >= 1.0 else self._normalize_volume(
            info, position.volume * fraction
        )
        if not volume:
            return OrderResult(False, action, "Volumen de cierre invalido", symbol=symbol)

        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            return OrderResult(False, action, f"Sin cotizacion para {position.symbol}", symbol=symbol)

        # Cerrar es abrir la operacion opuesta contra el mismo ticket.
        is_long = position.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": position.symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if is_long else tick.ask,
            "deviation": 20,
            "magic": MAGIA,
            "comment": "tct-close",
        }

        volumen_antes = float(position.volume)
        last_result = None
        for filling in self._filling_modes(info):
            request["type_filling"] = filling
            result = mt5.order_send(request)
            last_result = result
            if result is None:
                # Igual que al abrir: sin respuesta NO se reenvia -un parcial
                # mandado dos veces achicaba la posicion dos veces-. Se mira
                # como quedo la posicion.
                return self._cierre_sin_respuesta(ticket, symbol, action, volumen_antes)
            if result.retcode in (mt5.TRADE_RETCODE_DONE,
                                  getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)):
                cerrado = _volumen_confirmado(result, volume)
                if fraction >= 1.0 and (
                        result.retcode != mt5.TRADE_RETCODE_DONE
                        or cerrado < volumen_antes - 1e-9):
                    # Se pidio cerrar TODO y el broker cerro una parte. Darla
                    # por cerrada sacaba la posicion del registro y dejaba el
                    # resto corriendo sin breakeven y fuera de los topes.
                    return self._cierre_total_incompleto(ticket, symbol,
                                                         volumen_antes, cerrado)
                return OrderResult(
                    ok=True, action=action, reason="cierre ejecutado", ticket=ticket,
                    price=float(result.price or 0) or None,
                    # Igual que al abrir: lo que el broker cerro de verdad. De
                    # este numero sale la fraccion que el motor da por cerrada.
                    lot=_volumen_confirmado(result, volume), symbol=symbol,
                    raw={"retcode": result.retcode},
                )
            if result.retcode != getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030):
                break

        reason = (
            f"cierre rechazado: retcode={last_result.retcode} {last_result.comment}"
            if last_result is not None
            else f"order_send devolvio None: {mt5.last_error()}"
        )
        return OrderResult(False, action, reason, ticket=ticket, symbol=symbol)

    def _cierre_total_incompleto(self, ticket: int, symbol: str, volumen_antes: float,
                                 cerrado: float) -> OrderResult:
        """Se pidio cerrar todo y el broker informo menos: se mira la cuenta.

        Solo es un cierre si la posicion ya no existe. Si queda algo, no es ok
        y `raw["restante"]` dice cuanto, para que el motor la siga gestionando
        con el lote que de verdad quedo.
        """
        try:
            posiciones = self._mt5.positions_get(ticket=ticket)
        except Exception:
            posiciones = None
        if posiciones is None:
            restante = max(0.0, round(volumen_antes - cerrado, 8))
        else:
            restante = float(getattr(posiciones[0], "volume", 0.0)) if posiciones else 0.0
        if restante <= 1e-9:
            return OrderResult(True, "close", "cierre ejecutado", ticket=ticket,
                               lot=volumen_antes, symbol=symbol)
        logger.error("Se pidio cerrar %s y el broker cerro solo una parte: quedan %s "
                     "lotes abiertos.", ticket, restante)
        return OrderResult(False, "close",
                           f"el broker cerro solo una parte: quedan {restante:g} lotes abiertos",
                           ticket=ticket, lot=round(volumen_antes - restante, 8),
                           symbol=symbol, raw={"restante": restante})

    def _cierre_sin_respuesta(self, ticket: int, symbol: str, action: str,
                              volumen_antes: float) -> OrderResult:
        """order_send no confirmo el cierre: se mira como quedo la posicion."""
        detalle = f"devolvio None: {self._mt5.last_error()}"
        for intento in range(4):
            if intento:
                time.sleep(0.5)
            try:
                posiciones = self._mt5.positions_get(ticket=ticket)
            except Exception:
                posiciones = None
            if posiciones is None:
                continue
            restante = float(getattr(posiciones[0], "volume", 0.0)) if posiciones else 0.0
            if action == "close" and 1e-9 < restante < volumen_antes - 1e-9:
                # Cierre TOTAL que entro a medias: igual que con respuesta.
                return self._cierre_total_incompleto(ticket, symbol, volumen_antes,
                                                     volumen_antes - restante)
            if restante < volumen_antes - 1e-9:
                logger.warning("order_send no confirmo el cierre de %s, pero SE cerro "
                               "(quedan %s lotes).", ticket, restante)
                return OrderResult(True, action, "cierre ejecutado (confirmado en la cuenta)",
                                   ticket=ticket, lot=round(volumen_antes - restante, 8),
                                   symbol=symbol, raw={"sin_respuesta": True})
        return OrderResult(False, action,
                           f"order_send no confirmo el cierre ({detalle}); mira MetaTrader",
                           ticket=ticket, symbol=symbol, raw={"sin_respuesta": True})

    async def modify_stop_loss(
        self, *, ticket: int | None, symbol: str, stop_loss: float
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "modify_sl", "MT5 no esta conectado", symbol=symbol)
        if ticket is None:
            return OrderResult(False, "modify_sl", "Falta el ticket de la posicion", symbol=symbol)
        return await asyncio.to_thread(self._modify_sl_sync, ticket, symbol, stop_loss)

    def _modify_sl_sync(self, ticket: int, symbol: str, stop_loss: float) -> OrderResult:
        mt5 = self._mt5
        # Antes de CADA orden: la terminal puede haber cambiado de cuenta con
        # el bot andando (dos cuentas del mismo broker, una sola terminal).
        motivo = self._cuenta_sigue_siendo_la_del_env()
        if motivo:
            logger.error("NO se movio el stop: %s", motivo)
            return OrderResult(False, "modify_sl", f"No se movio el stop: {motivo}",
                               ticket=ticket, symbol=symbol)

        positions = mt5.positions_get(ticket=ticket)
        if positions is None:
            return OrderResult(
                False, "modify_sl",
                f"No se pudo consultar la posicion {ticket}: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        if not positions:
            return OrderResult(
                False, "modify_sl",
                f"La posicion {ticket} ya no existe en MT5: no hay stop que mover.",
                ticket=ticket, symbol=symbol, raw={"ausente": True},
            )
        position = positions[0]

        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": float(stop_loss),
            "tp": float(position.tp or 0.0),  # conservar el TP vigente
        })
        if result is None:
            return OrderResult(
                False, "modify_sl", f"order_send devolvio None: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        # 10025 (NO_CHANGES) NO es un fallo: significa que el stop YA estaba en
        # ese precio. O sea, la prueba de que el movimiento se hizo.
        #
        # Pasa siempre y por un motivo normal: este canal EDITA sus mensajes, y
        # las ediciones se reprocesan a proposito (para captar un SL corregido).
        # Asi que un "MOVER SL A 4467" se ejecuta una vez de verdad y otras dos
        # sobre un stop que ya vale 4467. Contarlo como rechazo hacia que el bot
        # avisara "NO se pudo mover el SL" justo despues de haberlo movido bien:
        # la persona lee que quedo sin proteccion cuando en realidad esta
        # protegida. Es exactamente el tipo de mentira que este proyecto viene
        # sacando.
        sin_cambios = result.retcode == getattr(mt5, "TRADE_RETCODE_NO_CHANGES", 10025)
        ok = result.retcode == mt5.TRADE_RETCODE_DONE or sin_cambios

        if sin_cambios:
            reason = f"el stop ya estaba en {stop_loss}: no habia nada que cambiar"
        elif ok:
            reason = "SL modificado"
        else:
            reason = f"rechazado: retcode={result.retcode} {result.comment}"

        return OrderResult(
            ok=ok, action="modify_sl", reason=reason,
            ticket=ticket, price=stop_loss, symbol=symbol,
            raw={"retcode": result.retcode, "sin_cambios": sin_cambios},
        )

    async def modify_take_profit(
        self, *, ticket: int | None, symbol: str, take_profit: float
    ) -> OrderResult:
        if not await self.is_ready():
            return OrderResult(False, "modify_tp", "MT5 no esta conectado", symbol=symbol)
        if ticket is None:
            return OrderResult(False, "modify_tp", "Falta el ticket de la posicion", symbol=symbol)
        return await asyncio.to_thread(self._modify_tp_sync, ticket, symbol, take_profit)

    def _modify_tp_sync(self, ticket: int, symbol: str, take_profit: float) -> OrderResult:
        """Espejo de `_modify_sl_sync`: el mismo pedido SLTP, con el STOP conservado.

        MetaTrader no tiene un pedido para cambiar solo el TP: TRADE_ACTION_SLTP
        lleva los dos, y un 0 en el que no se quiere tocar lo BORRA. Mover el TP
        mandando sl=0 dejaria la posicion sin stop. Por eso se relee la posicion
        y se manda el stop que tiene puesto.
        """
        mt5 = self._mt5
        # Antes de CADA orden: la terminal puede haber cambiado de cuenta con
        # el bot andando (dos cuentas del mismo broker, una sola terminal).
        motivo = self._cuenta_sigue_siendo_la_del_env()
        if motivo:
            logger.error("NO se movio el TP: %s", motivo)
            return OrderResult(False, "modify_tp", f"No se movio el TP: {motivo}",
                               ticket=ticket, symbol=symbol)

        positions = mt5.positions_get(ticket=ticket)
        if positions is None:
            return OrderResult(
                False, "modify_tp",
                f"No se pudo consultar la posicion {ticket}: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        if not positions:
            return OrderResult(
                False, "modify_tp",
                f"La posicion {ticket} ya no existe en MT5: no hay take profit que mover.",
                ticket=ticket, symbol=symbol, raw={"ausente": True},
            )
        position = positions[0]

        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": float(position.sl or 0.0),  # conservar el stop vigente
            "tp": float(take_profit),
        })
        if result is None:
            return OrderResult(
                False, "modify_tp", f"order_send devolvio None: {mt5.last_error()}",
                ticket=ticket, symbol=symbol,
            )
        # 10025 igual que con el stop: el TP ya estaba en ese precio, que es la
        # prueba de que el pedido se cumple, no un rechazo.
        sin_cambios = result.retcode == getattr(mt5, "TRADE_RETCODE_NO_CHANGES", 10025)
        ok = result.retcode == mt5.TRADE_RETCODE_DONE or sin_cambios

        if sin_cambios:
            reason = f"el take profit ya estaba en {take_profit}: no habia nada que cambiar"
        elif ok:
            reason = "TP modificado"
        else:
            reason = f"rechazado: retcode={result.retcode} {result.comment}"

        return OrderResult(
            ok=ok, action="modify_tp", reason=reason,
            ticket=ticket, price=take_profit, symbol=symbol,
            raw={"retcode": result.retcode, "sin_cambios": sin_cambios},
        )

    # -- Auxiliares (portados de tradingalertaIA) --------------------------

    def _ensure_symbol(self, symbol: str):
        """Devuelve symbol_info, activandolo en Market Watch si hace falta."""
        mt5 = self._mt5
        try:
            info = mt5.symbol_info(symbol)
        except Exception:
            return None
        if info is None:
            return None
        if not bool(getattr(info, "visible", True)):
            try:
                if not mt5.symbol_select(symbol, True):
                    return None
                info = mt5.symbol_info(symbol)
            except Exception:
                return None
        return info

    def _resolver_contra_broker(self, canonico: str) -> str | None:
        """Encuentra como se llama REALMENTE este instrumento en este broker.

        Se le pregunta a MT5 en vez de confiar en una tabla de sufijos escrita
        a mano. Cada broker bautiza distinto (XAUUSD, XAUUSDm, XAUUSD.r,
        GOLD...), y una tabla estatica queda desactualizada o simplemente no
        cubre al broker que termine usando el usuario. Con la terminal
        conectada, la lista autoritativa esta a una llamada de distancia.

        Elegir el nombre es `elegir_nombre_de_simbolo`, que es puro y lo usa
        tambien el diagnostico de `tct mt5`. Aca queda lo que necesita la
        terminal: preguntarle la lista, cachear y contar lo que paso.

        El resultado se cachea: `symbols_get()` devuelve miles de simbolos y
        recorrerlos en cada senal seria un desperdicio.
        """
        canonico = canonico.strip().upper()
        if canonico in self._symbol_cache:
            return self._symbol_cache[canonico]

        try:
            todos = self._mt5.symbols_get()
        except Exception:
            logger.warning("No se pudo listar los simbolos del broker", exc_info=True)
            return None
        if not todos:
            # None es una falla de consulta, y una lista vacia es la terminal
            # que todavia no bajo los simbolos (el primer login a un servidor
            # nuevo). Ninguna de las dos dice "este broker no tiene oro": no se
            # cachea, y la proxima senal vuelve a preguntar. Cacheado, el oro
            # quedaba muerto toda la sesion.
            logger.warning("El broker no devolvio la lista de simbolos: se vuelve a "
                           "preguntar en la proxima senal.")
            return None

        elegido = elegir_nombre_de_simbolo(canonico, [getattr(s, "name", "") for s in todos])
        if elegido is None:
            # INFO y no ERROR: que un broker no tenga un instrumento es un
            # hecho sobre ese broker, no una falla. Quien SI tiene que gritar
            # es el que necesitaba el simbolo: al abrir, `_open_sync` devuelve
            # un OrderResult con el motivo y el motor lo loguea como error; al
            # arrancar, `tct run` avisa la lista completa de una sola vez.
            #
            # Estaba en ERROR y salia una linea roja alarmante justo antes del
            # aviso bueno, diciendo lo mismo peor. Un ERROR que no es un error
            # entrena a la persona a ignorar los que si lo son.
            logger.info("El broker no expone ningun simbolo para %s", canonico)
        elif elegido.upper() != canonico:
            logger.info("Simbolo %s resuelto como '%s' en este broker", canonico, elegido)
        self._symbol_cache[canonico] = elegido
        return elegido

    @staticmethod
    def _normalize_volume(info: Any, lot: float) -> float | None:
        """Ajusta el lote al paso del broker y verifica min/max."""
        if info is None:
            return None
        step = float(getattr(info, "volume_step", 0.01) or 0.01)
        minimum = float(getattr(info, "volume_min", 0.01) or 0.01)
        maximum = float(getattr(info, "volume_max", 100.0) or 100.0)

        steps = round(lot / step)
        volume = round(steps * step, 8)
        if volume < minimum:
            volume = minimum
        if volume > maximum:
            return None
        # Se redondea a la precision del paso: 0.01 -> 2 decimales.
        precision = max(0, len(f"{step:.8f}".rstrip("0").split(".")[-1]))
        return round(volume, precision)

    def _filling_modes(self, info: Any) -> list[int]:
        """Modos de llenado a probar, en orden de preferencia.

        `symbol_info.filling_mode` viene como flags de capacidad del simbolo,
        mientras que `order_send` espera un enum ORDER_FILLING_*. No son la
        misma escala y confundirlos es la causa clasica del retcode 10030.
        """
        mt5 = self._mt5
        mode = getattr(info, "filling_mode", None)
        order_fok = getattr(mt5, "ORDER_FILLING_FOK", 0)
        order_ioc = getattr(mt5, "ORDER_FILLING_IOC", 1)
        order_return = getattr(mt5, "ORDER_FILLING_RETURN", 2)
        symbol_fok = getattr(mt5, "SYMBOL_FILLING_FOK", 1)
        symbol_ioc = getattr(mt5, "SYMBOL_FILLING_IOC", 2)

        modes: list[int] = []
        if isinstance(mode, int):
            if mode & symbol_ioc:
                modes.append(order_ioc)
            if mode & symbol_fok:
                modes.append(order_fok)
        for fallback in (order_ioc, order_fok, order_return):
            if fallback not in modes:
                modes.append(fallback)
        return modes
