"""`tct mt5` dice cuantas posiciones entran, preguntandole el margen al broker.

POR QUE
-------
El 2026-09-20 la demo de FxPro de 500 rechazo TODAS las aperturas del dia con
"retcode=10019 No money": el margen de una sola posicion de 0.01 de oro no
entraba en la cuenta. El bot registro las senales y no opero ninguna, y eso no
se vio hasta leer el log entero al dia siguiente. El mismo numero decide
`MAX_OPEN_TRADES` en la cuenta real, y se elegia a ciegas.

Lo que importa probar es que el aviso salga ANTES de operar, con los numeros
del broker (no estimados con el apalancamiento), y que el comando siga sirviendo
cuando el `.env` todavia no carga -que es justo el momento de la cuenta real-.
"""

from __future__ import annotations

import argparse
import sys

import pytest

from tct import cli
from tct.brokers.mt5_native import elegir_nombre_de_simbolo


class CuentaFalsa:
    name = "Jezrel"
    company = "FxPro Financial Services Ltd"
    login = 7001234
    server = "FxPro-MT5 Demo"
    balance = 500.0
    equity = 500.0
    currency = "USD"
    trade_mode = 0  # DEMO

    def __init__(self, margin_free: float = 500.0, leverage: int = 5) -> None:
        self.margin_free = margin_free
        self.leverage = leverage


class SimboloFalso:
    def __init__(self, name: str, visible: bool = True, volume_min: float = 0.01,
                 trade_contract_size: float = 100.0) -> None:
        self.name = name
        self.visible = visible
        self.volume_min = volume_min
        self.trade_contract_size = trade_contract_size


class TickFalso:
    def __init__(self, bid: float, ask: float) -> None:
        self.bid = bid
        self.ask = ask


class TerminalFalsa:
    def __init__(self, path: str = "") -> None:
        self.path = path


# El precio con el que contesta el MT5 falso, y el tamano de contrato de cada
# instrumento, para que el margen que "pide el broker" y el que sale de la
# cuenta (contrato x precio x lote / apalancamiento) sean coherentes: si no, el
# aviso de "no me fio de este numero" salta en todos los tests.
PRECIO = 4350.0
CONTRATOS = {"GOLD": 100.0, "BITCOIN": 5.0, "EURUSD": 2.4}


class MT5Falso:
    """Lo justo de MetaTrader5 que usa `tct mt5`."""

    ORDER_TYPE_BUY = 0
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, *, margenes=None, simbolos=None, cuenta=None, margin_free=500.0):
        # Como FxPro: el oro se llama GOLD y con 1:5 pide 870 de margen.
        self.simbolos = simbolos if simbolos is not None else ["GOLD", "BITCOIN", "EURUSD"]
        self.margenes = margenes if margenes is not None else {
            "GOLD": 870.0, "BITCOIN": 43.5, "EURUSD": 21.0,
        }
        self.cuenta = cuenta if cuenta is not None else CuentaFalsa(margin_free)
        self.inicializado_con: list[dict] = []
        self.activados: list[str] = []
        self.margenes_pedidos: list[tuple[str, float]] = []

    # -- conexion
    def initialize(self, path=None, **kwargs):
        self.inicializado_con.append({"path": path, **kwargs})
        return True

    def last_error(self):
        return (0, "sin error")

    def account_info(self):
        return self.cuenta

    def terminal_info(self):
        return TerminalFalsa()

    # -- simbolos
    def symbols_get(self):
        return [SimboloFalso(n) for n in self.simbolos]

    def symbol_info(self, name):
        if name not in self.simbolos:
            return None
        return SimboloFalso(name, trade_contract_size=CONTRATOS.get(name, 100.0))

    def symbol_select(self, name, activar=True):
        self.activados.append(name)
        return name in self.simbolos

    def symbol_info_tick(self, name):
        if name not in self.simbolos:
            return None
        return TickFalso(PRECIO - 0.5, PRECIO)

    def order_calc_margin(self, tipo, simbolo, lote, precio):
        self.margenes_pedidos.append((simbolo, lote))
        return self.margenes.get(simbolo)

    def shutdown(self):
        pass


@pytest.fixture
def en_windows(monkeypatch):
    """El comando se niega fuera de Windows; los tests corren igual."""
    monkeypatch.setattr(sys, "platform", "win32")


def correr(monkeypatch, falso, env_file=None):
    monkeypatch.setitem(sys.modules, "MetaTrader5", falso)
    return cli.cmd_mt5(argparse.Namespace(env_file=env_file))


def env(tmp_path, nombre=".env.segunda", extra=""):
    ruta = tmp_path / nombre
    ruta.write_text(
        "TRADING_MODE=AUTO\nINSTANCE_NAME=fxpro\nINSTANCE_NAMES=demo,fxpro\n"
        "DEFAULT_LOT=0.01\nMAX_LOT=0.01\nALLOWED_SYMBOLS=XAUUSD,BTCUSD,EURUSD,NAS100\n"
        + extra,
        encoding="utf-8",
    )
    return ruta


# --------------------------------------------------------------------------
# El caso que costo un dia entero
# --------------------------------------------------------------------------


def test_avisa_que_no_entra_ninguna_posicion(tmp_path, monkeypatch, capsys, en_windows):
    falso = MT5Falso()

    assert correr(monkeypatch, falso, str(env(tmp_path))) == 0

    salida = capsys.readouterr().out
    assert "XAUUSD -> GOLD" in salida
    assert "870.00" in salida
    assert "NO ENTRA NINGUNA" in salida
    assert "No money" in salida and "10019" in salida


def test_dice_cuantas_entran_cuando_entran(tmp_path, monkeypatch, capsys, en_windows):
    # 1:20, que es donde el oro pide ~217 y entran 2 en 500.
    falso = MT5Falso(margenes={"GOLD": 217.0, "BITCOIN": 43.5, "EURUSD": 21.0},
                     cuenta=CuentaFalsa(leverage=20))

    correr(monkeypatch, falso, str(env(tmp_path)))

    salida = capsys.readouterr().out
    assert "entran 2" in salida       # 500 libres / 217
    assert "entran 11" in salida      # 500 / 43.5
    assert "NO ENTRA NINGUNA" not in salida
    assert "No money" not in salida


def test_dice_con_cuanto_apalancamiento_entraria(tmp_path, monkeypatch, capsys, en_windows):
    """Es la decision que sigue: mas apalancamiento, mas saldo, o nada."""
    correr(monkeypatch, MT5Falso(), str(env(tmp_path)))

    salida = capsys.readouterr().out
    assert "Con 1:5 pide 870.00" in salida
    assert "Con 1:100 pediria 43.50" in salida


def test_el_margen_lo_pide_al_broker_con_el_lote_del_env(tmp_path, monkeypatch, capsys, en_windows):
    """Estimarlo con el apalancamiento no sirve: los metales suelen tener su
    propia tabla, y el numero que decide es el del broker."""
    falso = MT5Falso()

    correr(monkeypatch, falso, str(env(tmp_path, extra="DEFAULT_LOT=0.02\nMAX_LOT=0.02\n")))

    assert ("GOLD", 0.02) in falso.margenes_pedidos


def test_el_margen_libre_manda_sobre_el_balance(tmp_path, monkeypatch, capsys, en_windows):
    """Con una posicion abierta perdiendo, el balance sigue en 500 y lo que
    decide es el margen libre."""
    falso = MT5Falso(margenes={"GOLD": 217.0, "BITCOIN": 43.5, "EURUSD": 21.0},
                     cuenta=CuentaFalsa(margin_free=180.0, leverage=20))

    correr(monkeypatch, falso, str(env(tmp_path)))

    salida = capsys.readouterr().out
    assert "Margen libre: 180.00 USD" in salida
    assert "NO ENTRA NINGUNA" in salida


# --------------------------------------------------------------------------
# Que no se caiga cuando el broker no contesta
# --------------------------------------------------------------------------


def test_un_simbolo_que_el_broker_no_tiene_se_lista_aparte(tmp_path, monkeypatch, capsys,
                                                           en_windows):
    correr(monkeypatch, MT5Falso(), str(env(tmp_path)))

    assert "Este broker no opera: NAS100" in capsys.readouterr().out


def test_si_el_broker_no_da_el_margen_se_estima_y_se_avisa(tmp_path, monkeypatch, capsys,
                                                           en_windows):
    """El caso real de la demo de FxPro a 1:2: para GOLD devolvio 0.0 mientras
    el bot recibia "No money" en cada apertura. Un 0.00 en pantalla se lee como
    "no pide margen", que es lo contrario de lo que pasaba."""
    falso = MT5Falso(margenes={"GOLD": 0.0, "BITCOIN": 43.5, "EURUSD": 21.0})

    assert correr(monkeypatch, falso, str(env(tmp_path))) == 0

    salida = capsys.readouterr().out
    # contrato 100 x precio 4350 x lote 0.01 / apalancamiento 5 = 870
    assert "870.00 (estimado)" in salida
    assert "NO ENTRA NINGUNA" in salida
    assert "cuenta mia, no del broker" in salida
    assert "entran 11" in salida, "una consulta que falla no puede tapar las demas"


def test_sin_apalancamiento_no_se_inventa_el_margen(tmp_path, monkeypatch, capsys, en_windows):
    """Sin con que estimar, se dice que no se sabe. Inventar un numero aca es
    peor que no darlo: con el se decide si la cuenta real sirve."""
    cuenta = CuentaFalsa()
    cuenta.leverage = 0
    falso = MT5Falso(margenes={"GOLD": None, "BITCOIN": None, "EURUSD": None}, cuenta=cuenta)

    assert correr(monkeypatch, falso, str(env(tmp_path))) == 0

    salida = capsys.readouterr().out
    assert "no contesto el margen" in salida
    assert "estimado" not in salida


def test_un_margen_mucho_mas_chico_que_el_del_contrato_no_se_cree(tmp_path, monkeypatch, capsys,
                                                                  en_windows):
    """La misma cuenta de FxPro a 1:2 contesto 3.69 para la plata, donde por
    contrato y apalancamiento salen mas de mil. Decir "entran 135" de algo que
    no entra ninguna es peor que no decir nada."""
    falso = MT5Falso(margenes={"GOLD": 3.69, "BITCOIN": 43.5, "EURUSD": 21.0})

    assert correr(monkeypatch, falso, str(env(tmp_path))) == 0

    salida = capsys.readouterr().out
    assert "3.69 (?)" in salida
    assert "no me fio del numero" in salida
    assert "870.00" in salida, "tiene que decir cuanto daria por contrato"


def test_un_margen_normal_no_se_pone_en_duda(tmp_path, monkeypatch, capsys, en_windows):
    """La duda es para un numero que es una FRACCION del calculado; uno parecido
    -o mayor, que es lo normal con las tablas del broker- no se toca."""
    falso = MT5Falso(margenes={"GOLD": 700.0, "BITCOIN": 43.5, "EURUSD": 21.0})

    correr(monkeypatch, falso, str(env(tmp_path)))

    salida = capsys.readouterr().out
    assert "700.00" in salida
    assert "(?)" not in salida and "no me fio" not in salida


def test_no_dice_que_entran_miles(tmp_path, monkeypatch, capsys, en_windows):
    falso = MT5Falso(margenes={"GOLD": 870.0, "BITCOIN": 0.05, "EURUSD": 21.0})

    correr(monkeypatch, falso, str(env(tmp_path)))

    assert "entran +99" in capsys.readouterr().out


def test_un_lote_minimo_mas_grande_que_el_configurado_se_avisa(tmp_path, monkeypatch, capsys,
                                                               en_windows):
    """Con volume_min 0.1 y MAX_LOT 0.01 el bot no puede operar ese simbolo:
    el ejecutor no manda un volumen por arriba de MAX_LOT."""
    class LoteGrande(MT5Falso):
        def symbol_info(self, name):
            if name not in self.simbolos:
                return None
            return SimboloFalso(name, volume_min=0.1 if name == "BITCOIN" else 0.01)

    assert correr(monkeypatch, LoteGrande(), str(env(tmp_path))) == 0

    salida = capsys.readouterr().out
    assert "El lote minimo de BTCUSD en este broker es 0.1" in salida
    assert "NO lo va a" in salida


def test_sin_cotizacion_no_inventa_un_margen(tmp_path, monkeypatch, capsys, en_windows):
    class SinTick(MT5Falso):
        def symbol_info_tick(self, name):
            return None

    assert correr(monkeypatch, SinTick(), str(env(tmp_path))) == 0

    assert "no cotiza ahora" in capsys.readouterr().out


# --------------------------------------------------------------------------
# De que terminal lee, y con que .env
# --------------------------------------------------------------------------


def test_usa_la_terminal_del_env_que_se_pidio(tmp_path, monkeypatch, capsys, en_windows):
    """Con dos MetaTrader instalados, "la que encuentre" no tiene respuesta
    correcta: los datos tienen que ser de la cuenta de ESE bot."""
    ruta_mt5 = tmp_path / "FxPro" / "terminal64.exe"
    ruta_mt5.parent.mkdir()
    ruta_mt5.write_text("", encoding="utf-8")
    falso = MT5Falso()

    correr(monkeypatch, falso, str(env(tmp_path, extra=f"MT5_PATH={ruta_mt5}\n")))

    assert falso.inicializado_con == [{"path": str(ruta_mt5)}]
    assert str(ruta_mt5) in capsys.readouterr().out


def test_sin_ruta_en_el_env_se_engancha_a_la_que_haya(tmp_path, monkeypatch, capsys, en_windows):
    falso = MT5Falso()

    correr(monkeypatch, falso, str(env(tmp_path)))

    assert falso.inicializado_con == [{"path": None}]


def test_un_env_real_a_medio_llenar_igual_da_el_diagnostico(tmp_path, monkeypatch, capsys,
                                                            en_windows):
    """`load_settings` se niega con LIVE sin credenciales -bien-, y es JUSTO
    cuando hace falta saber si el lote entra en la cuenta."""
    ruta = tmp_path / ".env.real"
    ruta.write_text("TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=true\nDEFAULT_LOT=0.02\n"
                    "ALLOWED_SYMBOLS=XAUUSD\n", encoding="utf-8")
    with pytest.raises(Exception):
        from tct.config import load_settings
        load_settings(ruta)
    falso = MT5Falso()

    assert correr(monkeypatch, falso, str(ruta)) == 0

    salida = capsys.readouterr().out
    assert "NO ENTRA NINGUNA" in salida
    assert "BITCOIN" not in salida, "la real opera solo oro"
    assert falso.margenes_pedidos == [("GOLD", 0.02)], "no leyo el lote de ese archivo"


def test_sin_env_ninguno_mira_el_oro(tmp_path, monkeypatch, capsys, en_windows):
    monkeypatch.chdir(tmp_path)

    assert correr(monkeypatch, MT5Falso()) == 0

    assert "GOLD" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Elegir el nombre del simbolo: lo mismo que usa el bot para operar
# --------------------------------------------------------------------------


@pytest.mark.parametrize("canonico,nombres,esperado", [
    ("XAUUSD", ["XAUUSD", "GOLD"], "XAUUSD"),          # exacto primero
    ("XAUUSD", ["GOLD", "EURUSD"], "GOLD"),            # alias del broker
    ("XAUUSD", ["XAUUSDm"], "XAUUSDm"),                # con sufijo
    ("XAUUSD", ["XAUUSD.r"], "XAUUSD.r"),
    ("BTCUSD", ["BITCOIN"], "BITCOIN"),
    ("NAS100", ["EURUSD", "GOLD"], None),
    # El exacto gana aunque el del sufijo aparezca primero en la lista.
    ("XAUUSD", ["XAUUSDm", "XAUUSD"], "XAUUSD"),
    ("XAUUSD", ["GOLD", "XAUUSD"], "XAUUSD"),
])
def test_elegir_el_nombre_del_simbolo(canonico, nombres, esperado):
    assert elegir_nombre_de_simbolo(canonico, nombres) == esperado


def test_el_sufijo_de_una_letra_no_distingue_una_cripto_de_un_sufijo_de_broker():
    """Limite conocido, y NO se toca aca: 'EURUSDT' (la cripto contra USDT) y
    'EURUSDm' (el mismo EURUSD con el sufijo del broker) tienen la misma forma,
    asi que la regla del sufijo corto acepta las dos. El comentario del codigo
    decia que lo evitaba y no es cierto; esta anotado en §8 del CONTEXTO_MAESTRO.

    Hoy no muerde porque el nombre exacto gana primero, y un broker que ofrece
    EURUSDT ofrece EURUSD. Este test existe para que el dia que se toque la
    regla, se vea que esto cambia."""
    assert elegir_nombre_de_simbolo("EURUSD", ["EURUSDT"]) == "EURUSDT"
    assert elegir_nombre_de_simbolo("EURUSD", ["EURUSD", "EURUSDT"]) == "EURUSD"


def test_el_bot_y_el_diagnostico_resuelven_igual(tmp_path):
    """Si no, el margen se calcula de un simbolo y la orden se manda a otro.

    Se compara el COMPORTAMIENTO y no el codigo: una version anterior de este
    test miraba si el nombre de la funcion aparecia en la fuente del broker, y
    pasaba igual con la llamada sacada, porque el nombre estaba en el
    comentario (§7)."""
    from tct.brokers.mt5_native import MT5NativeBroker
    from tests.fake_mt5 import FakeMT5, enchufar
    from tests.test_engine import build_settings

    fake = FakeMT5({"GOLD": {"bid": 4349.5, "ask": 4350.0}})
    broker = enchufar(MT5NativeBroker(build_settings(tmp_path)), fake)

    del_bot = broker._resolver_contra_broker("XAUUSD")
    del_diagnostico = elegir_nombre_de_simbolo(
        "XAUUSD", [getattr(s, "name", "") for s in fake.symbols_get()])

    assert del_bot == del_diagnostico == "GOLD"
