"""La cuenta se verifica antes de CADA orden, no solo al conectar.

POR QUE
-------
`connect()` verifica una vez que la terminal este en la cuenta del `.env`. Con
DOS cuentas del mismo broker en la MISMA terminal -que es exactamente el plan
del usuario: la demo de FxPro y la real conviven ahi- alcanza con que alguien
loguee la terminal en la otra cuenta con el bot andando para que TODAS las
ordenes siguientes vayan a la cuenta equivocada. El bot no se entera: manda la
orden, el broker la acepta, y el resultado vuelve ok=True.

Reproducido antes de arreglarlo, con la configuracion real del 22/09: el bot de
la DEMO -que desde ese dia corre sin topes y sin freno diario- abrio una
posicion en la cuenta REAL, con ok=True y "orden ejecutada".

El lado barato aca es al reves que en el resto del bot: cuando NO se puede saber
en que cuenta se esta, no se manda la orden. Una senal perdida cuesta poco; una
orden en la cuenta equivocada, no (§12).
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.mt5_native import MT5NativeBroker
from tct.signals.models import OrderType, Side
from tests.fake_mt5 import FakeMT5, enchufar

DEMO = 592098515
REAL = 516648640


class TerminalCompartida(FakeMT5):
    """Una terminal donde alguien puede cambiar de cuenta en cualquier momento."""

    def __init__(self, cuenta_activa=DEMO, sin_cuenta=False):
        super().__init__({"GOLD": {"bid": 4349.5, "ask": 4350.0}})
        self.cuenta_activa = cuenta_activa
        self.sin_cuenta = sin_cuenta

    def account_info(self):
        if self.sin_cuenta:
            return None
        activa = self.cuenta_activa

        class Cuenta:
            login = activa
            equity = 500.0
            balance = 500.0
            trade_mode = 0

            def _asdict(self):
                return {"login": activa, "trade_mode": 0, "equity": 500.0}
        return Cuenta()


class Ajustes:
    """Como esta .env.segunda hoy: la demo de FxPro, sin topes."""
    mt5_login = str(DEMO)
    mt5_password = "x"
    mt5_server = "FxPro-MT5 Demo"
    mt5_path = ""
    mt5_broker_profile = "default"
    max_lot = 0.01
    default_lot = 0.01
    allow_live_trading = False
    trading_mode = "PAPER_AND_MT5_DEMO"
    is_live = False


def armar(**kwargs):
    terminal = TerminalCompartida(**kwargs)
    broker = enchufar(MT5NativeBroker(Ajustes()), terminal)
    return broker, terminal


def abrir(broker):
    return asyncio.run(broker.open_order(
        symbol="XAUUSD", side=Side.BUY, order_type=OrderType.MARKET,
        lot=0.01, entry=4350.0, stop_loss=4342.0, take_profit=4354.0))


# --------------------------------------------------------------------------
# Abrir
# --------------------------------------------------------------------------


def test_con_la_cuenta_correcta_opera_normal():
    broker, terminal = armar()

    resultado = abrir(broker)

    assert resultado.ok
    assert terminal.volumenes_enviados() == [0.01]


def test_si_la_terminal_cambio_de_cuenta_no_manda_la_orden():
    """El caso que motiva todo esto: la orden entraba en la otra cuenta."""
    broker, terminal = armar()
    terminal.cuenta_activa = REAL

    resultado = abrir(broker)

    assert not resultado.ok
    assert str(REAL) in resultado.reason and str(DEMO) in resultado.reason
    assert terminal.volumenes_enviados() == [], "mando la orden a la otra cuenta"


def test_si_no_se_puede_leer_la_cuenta_tampoco_manda():
    """No saber en que cuenta se esta no es lo mismo que estar en la correcta."""
    broker, terminal = armar(sin_cuenta=True)

    resultado = abrir(broker)

    assert not resultado.ok
    assert terminal.volumenes_enviados() == []


def test_sin_mt5_login_en_el_env_no_opina():
    """Con una sola cuenta, el .env no la nombra y no hay contra que comparar:
    el bot se engancha a la que este abierta, que es lo documentado."""
    class SinLogin(Ajustes):
        mt5_login = ""

    terminal = TerminalCompartida()
    broker = enchufar(MT5NativeBroker(SinLogin()), terminal)
    terminal.cuenta_activa = REAL

    assert abrir(broker).ok
    assert terminal.volumenes_enviados() == [0.01]


# --------------------------------------------------------------------------
# Cerrar y mover: el mismo ticket puede existir en la otra cuenta
# --------------------------------------------------------------------------


def _abrir_y_cambiar_de_cuenta():
    broker, terminal = armar()
    resultado = abrir(broker)
    terminal.cuenta_activa = REAL
    return broker, terminal, resultado.ticket


def test_no_cierra_en_la_cuenta_equivocada():
    broker, terminal, ticket = _abrir_y_cambiar_de_cuenta()
    enviados = len(terminal.enviados)

    resultado = asyncio.run(broker.close_position(ticket=ticket, symbol="XAUUSD", fraction=1.0))

    assert not resultado.ok
    assert len(terminal.enviados) == enviados, "mando un cierre a la otra cuenta"


def test_no_mueve_el_stop_en_la_cuenta_equivocada():
    broker, terminal, ticket = _abrir_y_cambiar_de_cuenta()
    enviados = len(terminal.enviados)

    resultado = asyncio.run(broker.modify_stop_loss(ticket=ticket, symbol="XAUUSD", stop_loss=4345.0))

    assert not resultado.ok
    assert len(terminal.enviados) == enviados


def test_no_mueve_el_tp_en_la_cuenta_equivocada():
    broker, terminal, ticket = _abrir_y_cambiar_de_cuenta()
    enviados = len(terminal.enviados)

    resultado = asyncio.run(broker.modify_take_profit(ticket=ticket, symbol="XAUUSD", take_profit=4360.0))

    assert not resultado.ok
    assert len(terminal.enviados) == enviados


# --------------------------------------------------------------------------
# El freno diario no puede mirar el equity de otra cuenta
# --------------------------------------------------------------------------


def test_el_equity_de_otra_cuenta_no_cuenta():
    """Si devolviera el equity de la otra cuenta, el freno diario compararia
    contra un numero que no es de esta cuenta. Sin dato no se rechaza nada
    (§9), pero un dato de otra cuenta es peor que no tener dato."""
    broker, terminal = armar()
    assert asyncio.run(broker.account_equity()) == 500.0

    terminal.cuenta_activa = REAL

    assert asyncio.run(broker.account_equity()) is None


@pytest.mark.parametrize("cuenta", [DEMO, REAL])
def test_el_chequeo_no_depende_de_que_connect_haya_corrido(cuenta):
    """`enchufar` saltea connect(): la verificacion tiene que estar en el camino
    de la orden, no en el arranque."""
    broker, terminal = armar()
    terminal.cuenta_activa = cuenta

    assert abrir(broker).ok is (cuenta == DEMO)
