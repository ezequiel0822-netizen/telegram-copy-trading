"""Varias instancias del bot, cada una contra su cuenta de MetaTrader.

MT5 admite una cuenta por terminal y una terminal por proceso, asi que dos
cuentas son dos procesos, cada uno con su `.env`. Los dos leen los MISMOS
Mensajes Guardados, y de ahi que los comandos acepten destinatario.

Los nombres eran una lista clavada `{demo, real, papel, paper}`. Ahora los
elige quien monta las instancias, porque "fxpro" y "exness" describen mejor lo
que hay que dos etiquetas genericas. Lo que NO cambia es que el vocabulario
siga siendo CERRADO: es lo unico que distingue `/pausa fxpro` (no es para mi)
de `/pausa mercado feo` (es para mi, con motivo).
"""

from __future__ import annotations

import asyncio

import pytest

from tct.brokers.paper import PaperBroker
from tct.config import ConfigError, load_settings
from tct.engine import Engine
from tct.store import Store
from tct.telegram.control import ControlTelegram
from tests.test_engine import build_settings, send

SENAL = "XAUUSD BUY\nEntry 2345\nSL 2335\nTP 2355"


def escribir_env(tmp_path, contenido: str, nombre=".env"):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def instancia(tmp_path, nombre, roster):
    carpeta = tmp_path / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    settings = build_settings(
        carpeta,
        instance_name=nombre,
        instance_names=tuple(roster),
        events_path=carpeta / "events.jsonl",
        paper_trades_path=carpeta / "paper.jsonl",
        state_path=carpeta / "state.json",
    )
    store = Store(settings.events_path, settings.paper_trades_path, settings.state_path)
    engine = Engine(settings, store, PaperBroker())
    return store, engine, ControlTelegram(settings, store, engine)


def a_todas(controles, texto):
    return [asyncio.run(c.manejar(texto)) for c in controles]


# --------------------------------------------------------------------------
# Nombres libres, declarados en el .env
# --------------------------------------------------------------------------


def test_un_nombre_propio_del_broker_es_valido(tmp_path):
    env = escribir_env(tmp_path, "INSTANCE_NAMES=fxpro,exness\nINSTANCE_NAME=fxpro\n")
    settings = load_settings(env)

    assert settings.instance_name == "fxpro"
    assert settings.instance_names == ("fxpro", "exness")


def test_sin_declarar_nada_sigue_andando_como_antes(tmp_path):
    """Los .env escritos antes de que esto existiera no se tocan."""
    settings = load_settings(escribir_env(tmp_path, "INSTANCE_NAME=demo\n"))

    assert settings.instance_names == ("demo", "real", "papel", "paper")


def test_un_nombre_fuera_del_roster_no_arranca(tmp_path):
    """Si esta instancia no figura en la lista que declaran las demas, sus
    comandos dirigidos nunca le llegarian. Mejor no arrancar."""
    env = escribir_env(tmp_path, "INSTANCE_NAMES=demo,fxpro\nINSTANCE_NAME=exness\n")

    with pytest.raises(ConfigError, match="no esta en INSTANCE_NAMES"):
        load_settings(env)


def test_el_error_dice_como_arreglarlo(tmp_path):
    env = escribir_env(tmp_path, "INSTANCE_NAMES=demo,fxpro\nINSTANCE_NAME=exness\n")

    with pytest.raises(ConfigError) as exc:
        load_settings(env)

    texto = str(exc.value)
    assert "INSTANCE_NAMES=demo,fxpro,exness" in texto, "no muestra la linea a pegar"
    assert "MISMA en cada .env" in texto, "no avisa que hay que tocar los dos"


@pytest.mark.parametrize("reservado", ["todos", "all", "ambos"])
def test_una_instancia_no_puede_llamarse_todos(tmp_path, reservado):
    """'todos' ya significa 'todas las instancias'. Una que se llame asi haria
    ambiguo cada comando dirigido."""
    env = escribir_env(
        tmp_path, f"INSTANCE_NAMES=demo,{reservado}\nINSTANCE_NAME=demo\n"
    )

    with pytest.raises(ConfigError, match="significa 'todas'"):
        load_settings(env)


@pytest.mark.parametrize("invalido", ["fx pro", "fx-pro", "fx.pro"])
def test_los_nombres_son_una_sola_palabra(tmp_path, invalido):
    """Con espacios o separadores, partir el mensaje en palabras deja de poder
    reconocer el nombre."""
    env = escribir_env(
        tmp_path, f"INSTANCE_NAMES=demo,{invalido}\nINSTANCE_NAME=demo\n"
    )

    with pytest.raises(ConfigError, match="nombre invalido"):
        load_settings(env)


def test_el_arranque_muestra_el_roster_completo(tmp_path):
    """Es lo que permite ver de un vistazo que los dos .env declaran lo mismo.
    Un roster distinto en cada uno es la unica forma de romper esto."""
    env = escribir_env(tmp_path, "INSTANCE_NAMES=fxpro,exness\nINSTANCE_NAME=fxpro\n")

    salida = load_settings(env).describe()

    assert "FXPRO" in salida
    assert "fxpro, exness" in salida


def test_con_una_sola_instancia_no_ensucia_el_arranque(tmp_path):
    """Quien corre un solo bot no tiene por que ver una lista de uno."""
    env = escribir_env(tmp_path, "INSTANCE_NAMES=fxpro\nINSTANCE_NAME=fxpro\n")

    primera = load_settings(env).describe().splitlines()[0]

    assert "de 1" not in primera


# --------------------------------------------------------------------------
# Dos instancias con nombres de broker, compartiendo el chat de control
# --------------------------------------------------------------------------


@pytest.fixture
def dos_brokers(tmp_path):
    roster = ("fxpro", "exness")
    store_a, engine_a, fxpro = instancia(tmp_path, "fxpro", roster)
    store_b, engine_b, exness = instancia(tmp_path, "exness", roster)
    send(engine_a, SENAL, message_id=1)
    send(engine_b, SENAL, message_id=1)
    return fxpro, exness, store_a, store_b


def test_un_comando_dirigido_solo_toca_a_su_instancia(dos_brokers):
    fxpro, exness, store_a, store_b = dos_brokers

    a_todas([fxpro, exness], "/pausa fxpro")

    assert store_a.is_paused, "no se pauso la que se nombro"
    assert not store_b.is_paused, "se pauso la otra"


def test_sin_destinatario_va_a_las_dos(dos_brokers):
    fxpro, exness, store_a, store_b = dos_brokers

    a_todas([fxpro, exness], "/pausa")

    assert store_a.is_paused and store_b.is_paused


def test_un_motivo_libre_no_se_confunde_con_un_destinatario(dos_brokers):
    """La trampa que hace que el vocabulario tenga que ser cerrado: 'mercado'
    no es una instancia, asi que la frase entera es el motivo y el comando va
    para todas."""
    fxpro, exness, store_a, store_b = dos_brokers

    a_todas([fxpro, exness], "/pausa mercado muy raro hoy")

    assert store_a.is_paused and store_b.is_paused
    assert "mercado muy raro hoy" in store_a.state.paused_reason


def test_cerrar_dirigido_a_una_no_arma_a_la_otra(dos_brokers):
    """El bug peor del proyecto, ahora con nombres de broker en vez de
    demo/real: tiene que seguir sin poder pasar."""
    fxpro, exness, store_a, store_b = dos_brokers

    a_todas([fxpro, exness], "/cerrar")
    a_todas([fxpro, exness], "/cerrar fxpro")
    a_todas([fxpro, exness], "SI")

    assert store_a.open_positions() == [], "no cerro la que se nombro"
    assert len(store_b.open_positions()) == 1, "cerro la cuenta que no se nombro"


def test_una_instancia_no_reconoce_un_nombre_fuera_de_su_roster(tmp_path):
    """El modo de falla si los dos .env declaran rosters distintos.

    Se verifica que caiga para el lado SEGURO: un cierre dirigido a un nombre
    desconocido no se entiende y se rechaza, en vez de tomarse como propio.
    """
    _, engine, control = instancia(tmp_path, "fxpro", ("fxpro",))
    send(engine, SENAL)

    respuesta = asyncio.run(control.manejar("/cerrar exness"))

    assert respuesta is not None and "No entendi" in respuesta
    assert control._confirmacion is None, "quedo armada por un comando ajeno"


# --------------------------------------------------------------------------
# MT5_PATH deja de poder estar vacio cuando hay dos instancias
# --------------------------------------------------------------------------


BASE_MT5 = (
    "TRADING_MODE=PAPER_AND_MT5_DEMO\n"
    "MT5_LOGIN=1\nMT5_PASSWORD=p\nMT5_SERVER=s\n"
)


def test_avisa_si_hay_dos_instancias_y_mt5_path_vacio(tmp_path, monkeypatch):
    """Con UNA instancia, vacio es lo mas robusto. Con DOS es al reves:
    'enganchate a la que encuentres' deja de tener respuesta correcta."""
    monkeypatch.setattr("sys.platform", "win32")
    env = escribir_env(
        tmp_path, BASE_MT5 + "INSTANCE_NAMES=fxpro,exness\nINSTANCE_NAME=fxpro\nMT5_PATH=\n"
    )

    aviso = " ".join(load_settings(env).warnings)

    assert "MT5_PATH" in aviso
    assert "misma cuenta" in aviso, "no explica el dano concreto"


def test_con_una_sola_instancia_no_avisa_nada_de_eso(tmp_path, monkeypatch):
    """Seria un aviso molesto y equivocado: para un solo bot, vacio es mejor."""
    monkeypatch.setattr("sys.platform", "win32")
    env = escribir_env(tmp_path, BASE_MT5 + "INSTANCE_NAME=demo\nMT5_PATH=\n")

    aviso = " ".join(load_settings(env).warnings)

    assert "MT5_PATH" not in aviso


def test_con_la_ruta_puesta_no_avisa(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    env = escribir_env(
        tmp_path,
        BASE_MT5 + "INSTANCE_NAMES=fxpro,exness\nINSTANCE_NAME=fxpro\n"
        r"MT5_PATH=C:\MT5-fxpro\terminal64.exe" + "\n",
    )

    aviso = " ".join(load_settings(env).warnings)

    assert "MT5_PATH" not in aviso


def test_en_papel_no_aplica(tmp_path):
    """Sin MetaTrader de por medio, la ruta no significa nada."""
    env = escribir_env(
        tmp_path, "TRADING_MODE=PAPER_ONLY\nINSTANCE_NAMES=a,b\nINSTANCE_NAME=a\n"
    )

    aviso = " ".join(load_settings(env).warnings)

    assert "MT5_PATH" not in aviso


# --------------------------------------------------------------------------
# El error mas facil de cometer: editar un .env y olvidar el otro
# --------------------------------------------------------------------------


def _avisar(tmp_path, monkeypatch, settings, env_file):
    import logging

    from tct.cli import _avisar_rosters_desparejos

    monkeypatch.chdir(tmp_path)
    logger = logging.getLogger("tct")
    capturado = []

    class Handler(logging.Handler):
        def emit(self, record):
            # getMessage() YA aplica los args. Volver a aplicarlos revienta y
            # logging se traga la excepcion, dejando el test en verde falso.
            capturado.append(record.getMessage())

    h = Handler(level=logging.WARNING)
    logger.addHandler(h)
    try:
        _avisar_rosters_desparejos(settings, env_file)
    finally:
        logger.removeHandler(h)
    return " ".join(capturado)


def test_avisa_si_el_otro_env_declara_otro_roster(tmp_path, monkeypatch):
    """El sintoma sin este aviso es silencioso: un '/pausa fxpro' no le llega
    al bot fxpro y en cambio pausa al principal."""
    escribir_env(tmp_path, "INSTANCE_NAMES=demo\nINSTANCE_NAME=demo\n", ".env")
    escribir_env(tmp_path, "INSTANCE_NAMES=demo,fxpro\nINSTANCE_NAME=fxpro\n", ".env.segunda")
    settings = load_settings(tmp_path / ".env.segunda")

    aviso = _avisar(tmp_path, monkeypatch, settings, str(tmp_path / ".env.segunda"))

    assert ".env" in aviso
    assert "IDENTICOS" in aviso


def test_no_avisa_si_los_dos_declaran_lo_mismo(tmp_path, monkeypatch):
    escribir_env(tmp_path, "INSTANCE_NAMES=demo,fxpro\nINSTANCE_NAME=demo\n", ".env")
    escribir_env(tmp_path, "INSTANCE_NAMES=demo,fxpro\nINSTANCE_NAME=fxpro\n", ".env.segunda")
    settings = load_settings(tmp_path / ".env.segunda")

    assert _avisar(tmp_path, monkeypatch, settings, str(tmp_path / ".env.segunda")) == ""


def test_las_plantillas_de_ejemplo_no_cuentan(tmp_path, monkeypatch):
    """Los .example estan para copiarse, no para correrse: compararse contra
    ellos daria un aviso permanente y falso."""
    escribir_env(tmp_path, "INSTANCE_NAMES=demo,fxpro\nINSTANCE_NAME=fxpro\n", ".env")
    escribir_env(tmp_path, "INSTANCE_NAMES=otra,cosa\n", ".env.segunda.example")
    settings = load_settings(tmp_path / ".env")

    assert _avisar(tmp_path, monkeypatch, settings, str(tmp_path / ".env")) == ""


def test_con_una_sola_instancia_no_compara_nada(tmp_path, monkeypatch):
    escribir_env(tmp_path, "INSTANCE_NAME=demo\n", ".env")
    escribir_env(tmp_path, "INSTANCE_NAMES=otra,cosa\n", ".env.vieja")
    settings = load_settings(tmp_path / ".env")

    assert _avisar(tmp_path, monkeypatch, settings, str(tmp_path / ".env")) == ""


def test_run_compara_los_rosters():
    """El cableado, que es lo que este proyecto olvida."""
    import inspect

    from tct import cli

    assert "_avisar_rosters_desparejos" in inspect.getsource(cli.cmd_run)
