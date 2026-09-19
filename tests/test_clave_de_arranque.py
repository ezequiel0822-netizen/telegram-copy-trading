"""La clave de arranque: el bot real, y el que el usuario elija, no arrancan sin ella.

Lo pidio asi: "cada que quiera iniciar el bot real, quiero que me pida
contrasena antes de iniciarlo, tambien en la demo de fxpro". Un doble clic en el
`.bat` equivocado alcanzaba para poner a operar la cuenta real.

Lo que importa probar no es que se pregunte, es que con la clave mal el bot NO
LLEGUE A HACER NADA: ni el candado de la carpeta, ni MetaTrader, ni Telegram.
"""

from __future__ import annotations

import argparse
import asyncio

import pytest

from tct import cli
from tct.clave import (
    VARIABLE,
    coincide,
    es_valida,
    escribir_en_env,
    hashear,
    pedir_y_verificar,
)
from tct.config import ConfigError, load_settings
from tests.test_engine import build_settings

CLAVE = "oro4432"


# --------------------------------------------------------------------------
# La huella
# --------------------------------------------------------------------------


def test_la_clave_correcta_coincide_y_otra_no():
    huella = hashear(CLAVE)

    assert coincide(CLAVE, huella)
    assert not coincide("oro4433", huella)
    assert not coincide("", huella)


def test_la_clave_no_se_puede_leer_de_la_huella():
    assert CLAVE not in hashear(CLAVE)


def test_la_misma_clave_da_huellas_distintas():
    """Por la sal. Si dieran lo mismo, dos .env con la misma clave se delatarian
    entre si, y una tabla de claves comunes la adivinaria."""
    assert hashear(CLAVE) != hashear(CLAVE)


@pytest.mark.parametrize("basura", ["", "oro4432", "pbkdf2_sha256:1:zz:yy", "$200000$ab"])
def test_lo_que_no_es_una_huella_no_vale(basura):
    assert not es_valida(basura)
    assert not coincide(CLAVE, basura)


# --------------------------------------------------------------------------
# Preguntarla
# --------------------------------------------------------------------------


def respuestas(*textos):
    pendientes = list(textos)

    def entrada(_prompt):
        return pendientes.pop(0)
    return entrada


def test_bien_a_la_primera():
    ok = pedir_y_verificar(hashear(CLAVE), "REAL", entrada=respuestas(CLAVE),
                           es_interactivo=lambda: True, salida=lambda _t: None)
    assert ok is True


def test_bien_al_tercer_intento():
    ok = pedir_y_verificar(hashear(CLAVE), "REAL", entrada=respuestas("a", "b", CLAVE),
                           es_interactivo=lambda: True, salida=lambda _t: None)
    assert ok is True


def test_tres_veces_mal_no_arranca():
    dichos = []
    ok = pedir_y_verificar(hashear(CLAVE), "REAL", entrada=respuestas("a", "b", "c"),
                           es_interactivo=lambda: True, salida=dichos.append)
    assert ok is False
    assert "NO arranca" in dichos[-1]


def test_sin_ventana_donde_escribir_no_arranca_y_no_pregunta():
    """Corriendo sin consola no se puede preguntar. Arrancar igual seria
    justo lo que la clave existe para impedir."""
    def no_deberia_preguntar(_p):
        raise AssertionError("pregunto sin tener donde")

    ok = pedir_y_verificar(hashear(CLAVE), "REAL", entrada=no_deberia_preguntar,
                           es_interactivo=lambda: False, salida=lambda _t: None)
    assert ok is False


def test_cortar_con_control_c_no_arranca():
    def corta(_p):
        raise KeyboardInterrupt

    ok = pedir_y_verificar(hashear(CLAVE), "REAL", entrada=corta,
                           es_interactivo=lambda: True, salida=lambda _t: None)
    assert ok is False


# --------------------------------------------------------------------------
# Guardarla en el .env
# --------------------------------------------------------------------------


def test_se_agrega_sin_tocar_lo_demas(tmp_path):
    env = tmp_path / ".env.real"
    original = "TRADING_MODE=LIVE\r\nMT5_PASSWORD=secreta\r\n# un comentario\r\n"
    env.write_bytes(original.encode("utf-8"))

    escribir_en_env(env, hashear(CLAVE))

    texto = env.read_bytes().decode("utf-8")
    assert texto.startswith(original), "toco las lineas que ya estaban"
    assert f"{VARIABLE}=pbkdf2_sha256:" in texto
    assert "\r\n" in texto.split(VARIABLE)[1], "cambio los fines de linea de Windows"
    assert CLAVE not in texto


def test_cambiarla_reemplaza_la_linea_y_no_duplica(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    escribir_en_env(env, hashear("vieja1"))
    escribir_en_env(env, hashear("nueva1"))

    texto = env.read_text(encoding="utf-8")
    assert texto.count(f"{VARIABLE}=") == 1, "quedaron dos claves"
    huella = texto.split(f"{VARIABLE}=")[1].strip()
    assert coincide("nueva1", huella)
    assert not coincide("vieja1", huella)


def test_escribir_algo_que_no_es_huella_se_niega(tmp_path):
    with pytest.raises(ValueError):
        escribir_en_env(tmp_path / ".env", CLAVE)


# --------------------------------------------------------------------------
# Leerla de la configuracion
# --------------------------------------------------------------------------

BASE = ("TELEGRAM_API_ID=1\nTELEGRAM_API_HASH=x\n"
        "TELEGRAM_SESSION_NAME=s\nTELEGRAM_SOURCE_CHATS=-100\nTRADING_MODE=PAPER_ONLY\n")


def test_una_clave_escrita_a_mano_no_carga(tmp_path):
    """Si alguien pone la clave en texto en el .env, el bot no la puede
    verificar nunca. Mejor decirlo al cargar que esconderlo detras de 'clave
    incorrecta' cada vez que arranca."""
    (tmp_path / ".env").write_text(BASE + f"{VARIABLE}=oro4432\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="tct clave"):
        load_settings(tmp_path / ".env")


def test_una_huella_buena_carga(tmp_path):
    huella = hashear(CLAVE)
    (tmp_path / ".env").write_text(BASE + f"{VARIABLE}={huella}\n", encoding="utf-8")

    assert load_settings(tmp_path / ".env").clave_de_arranque == huella


def test_la_huella_no_sale_en_la_descripcion(tmp_path):
    huella = hashear(CLAVE)
    (tmp_path / ".env").write_text(BASE + f"{VARIABLE}={huella}\n", encoding="utf-8")

    assert huella not in load_settings(tmp_path / ".env").describe()


# --------------------------------------------------------------------------
# Lo que importa: con la clave mal, el bot NO hace nada
# --------------------------------------------------------------------------


def armar_run(monkeypatch, settings, escritas):
    """cmd_run con todo lo de afuera reemplazado. Devuelve lo que llego a pasar."""
    paso = {"arranco": False, "candado": False}

    async def run_falso(_settings, _esperar=0):
        paso["arranco"] = True

    class Candado:
        def tomar(self):
            paso["candado"] = True

        def soltar(self):
            pass

    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr(cli, "_run_async", run_falso)
    monkeypatch.setattr("tct.lockfile.lock_para", lambda _s: Candado())
    monkeypatch.setattr("getpass.getpass", respuestas(*escritas))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    return paso


def correr_run():
    return cli.cmd_run(argparse.Namespace(env_file=".env.real", verbose=False))


def test_con_la_clave_mal_no_toma_el_candado_ni_conecta(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, clave_de_arranque=hashear(CLAVE))
    paso = armar_run(monkeypatch, settings, ["a", "b", "c"])

    assert correr_run() == 1
    assert paso == {"arranco": False, "candado": False}, "hizo algo sin la clave"


def test_con_la_clave_bien_arranca(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, clave_de_arranque=hashear(CLAVE))
    paso = armar_run(monkeypatch, settings, [CLAVE])

    assert correr_run() == 0
    assert paso["arranco"] is True


def test_una_demo_sin_clave_arranca_sin_preguntar(tmp_path, monkeypatch):
    """Lo que no hay que romper: la demo de MetaQuotes no la pidio."""
    settings = build_settings(tmp_path)
    paso = armar_run(monkeypatch, settings, [])  # si pregunta, revienta: no hay respuestas

    assert correr_run() == 0
    assert paso["arranco"] is True


def test_el_bot_real_sin_clave_no_arranca(tmp_path, monkeypatch, capsys):
    """Con dinero real es obligatoria: si se olvido de ponerla, no arranca."""
    settings = build_settings(
        tmp_path, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="x", mt5_server="FxPro-MT5",
    )
    paso = armar_run(monkeypatch, settings, [])

    assert correr_run() == 1
    assert paso == {"arranco": False, "candado": False}
    assert "tct clave --env-file .env.real" in capsys.readouterr().out, "no dice como ponerla"


def test_la_orden_de_prueba_tambien_la_pide(tmp_path, monkeypatch):
    """`probar --operar` abre una orden de verdad: en una cuenta protegida es
    lo mismo que arrancar."""
    settings = build_settings(
        tmp_path, trading_mode="LIVE", allow_live_trading=True,
        mt5_login="555", mt5_password="x", mt5_server="FxPro-MT5",
        clave_de_arranque=hashear(CLAVE),
    )
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr("getpass.getpass", respuestas("a", "b", "c"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def no_deberia_probar(*_a, **_k):
        raise AssertionError("llego a conectarse sin la clave")

    monkeypatch.setattr(cli, "_probar_async", no_deberia_probar)

    codigo = cli.cmd_probar(argparse.Namespace(
        env_file=".env.real", verbose=False, operar=True, simbolo="XAUUSD"))

    assert codigo == 1


# --------------------------------------------------------------------------
# El comando que la pone
# --------------------------------------------------------------------------


def correr_clave(monkeypatch, env, *escritas):
    monkeypatch.setattr("getpass.getpass", respuestas(*escritas))
    return cli.cmd_clave(argparse.Namespace(env_file=str(env)))


def test_tct_clave_la_guarda(tmp_path, monkeypatch):
    env = tmp_path / ".env.real"
    env.write_text("TRADING_MODE=LIVE\n", encoding="utf-8")

    assert correr_clave(monkeypatch, env, CLAVE, CLAVE) == 0

    texto = env.read_text(encoding="utf-8")
    huella = texto.split(f"{VARIABLE}=")[1].strip()
    assert coincide(CLAVE, huella)
    assert CLAVE not in texto


def test_si_no_coinciden_no_cambia_nada(tmp_path, monkeypatch):
    env = tmp_path / ".env.real"
    env.write_text("TRADING_MODE=LIVE\n", encoding="utf-8")

    assert correr_clave(monkeypatch, env, CLAVE, "otra123") == 1
    assert env.read_text(encoding="utf-8") == "TRADING_MODE=LIVE\n"


def test_una_clave_demasiado_corta_no_se_acepta(tmp_path, monkeypatch):
    env = tmp_path / ".env.real"
    env.write_text("A=1\n", encoding="utf-8")

    assert correr_clave(monkeypatch, env, "123", "123") == 1
    assert VARIABLE not in env.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Lo que encontro la revision del 19/09
# --------------------------------------------------------------------------


class ArgsSimular:
    horas = 24
    limite = None
    ejecutar = True
    con_precios = False
    todos = False
    verbose = False
    env_file = ".env.segunda"


def test_simular_ejecutar_en_la_demo_con_clave_la_pide(tmp_path, monkeypatch):
    """El agujero: `run` y `probar --operar` pedian la clave y `simular
    --ejecutar` no, y con la demo de FxPro protegida mandaba ordenes igual."""
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO",
                              clave_de_arranque=hashear(CLAVE))
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    monkeypatch.setattr("getpass.getpass", respuestas("a", "b", "c"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def no_deberia_simular(*_a, **_k):
        raise AssertionError("ejecuto la simulacion sin la clave")

    monkeypatch.setattr(cli, "_simular_async", no_deberia_simular)

    assert cli.cmd_simular(ArgsSimular()) == 1


def test_simular_sin_ejecutar_no_pide_nada(tmp_path, monkeypatch):
    """Sin --ejecutar solo mira: no manda ordenes, no hace falta la clave."""
    settings = build_settings(tmp_path, trading_mode="PAPER_AND_MT5_DEMO",
                              clave_de_arranque=hashear(CLAVE))
    monkeypatch.setattr(cli, "load_settings", lambda _ruta: settings)
    corridas = []

    async def simular_falso(_s, _a):
        corridas.append(True)
        return 0

    monkeypatch.setattr(cli, "_simular_async", simular_falso)
    args = ArgsSimular()
    args.ejecutar = False

    assert cli.cmd_simular(args) == 0
    assert corridas, "no llego a simular"


def test_la_marca_del_bloc_de_notas_no_duplica_la_clave(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(("\ufeff" + f"{VARIABLE}={hashear('vieja1')}\nA=1\n").encode("utf-8"))

    escribir_en_env(env, hashear("nueva1"))

    texto = env.read_bytes().decode("utf-8")
    assert texto.count(f"{VARIABLE}=") == 1, "quedo duplicada"
    assert texto.startswith("\ufeff"), "se perdio la marca del archivo"


def test_un_caracter_raro_en_otro_valor_no_mueve_la_clave(tmp_path):
    """`splitlines` cortaba en U+2028; python-dotenv no. La clave terminaba
    escrita dentro del valor de otra variable."""
    env = tmp_path / ".env"
    env.write_text("NOTA=hola\u2028CLAVE_DE_ARRANQUE=trampa\nA=1\n", encoding="utf-8")

    escribir_en_env(env, hashear(CLAVE))

    lineas = env.read_text(encoding="utf-8").split("\n")
    assert any(l.startswith(f"{VARIABLE}=pbkdf2") for l in lineas), "la clave no quedo en su linea"
    assert lineas[0] == "NOTA=hola\u2028CLAVE_DE_ARRANQUE=trampa", "toco otro valor"


def test_no_deja_archivos_temporales(tmp_path):
    env = tmp_path / ".env.real"
    env.write_text("A=1\n", encoding="utf-8")

    escribir_en_env(env, hashear(CLAVE))

    assert sorted(p.name for p in tmp_path.iterdir()) == [".env.real"]


def test_un_env_que_no_es_utf8_avisa_antes_de_pedir_la_clave(tmp_path, monkeypatch, capsys):
    """Antes se escribia la clave dos veces y recien ahi salia un error crudo."""
    env = tmp_path / ".env.real"
    original = "MT5_PASSWORD=contrase\xf1a\n".encode("cp1252")
    env.write_bytes(original)

    def no_deberia_preguntar(_p):
        raise AssertionError("pidio la clave sin poder escribir el archivo")

    monkeypatch.setattr("getpass.getpass", no_deberia_preguntar)

    assert cli.cmd_clave(argparse.Namespace(env_file=str(env))) == 1
    assert env.read_bytes() == original, "toco el archivo"
    assert "UTF-8" in capsys.readouterr().out, "no dice que hacer"


def test_si_no_se_puede_escribir_lo_dice_sin_error_crudo(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env.real"
    env.write_text("A=1\n", encoding="utf-8")

    def bloqueado(*_a, **_k):
        raise PermissionError("bloqueado")

    monkeypatch.setattr("tct.clave.escribir_en_env", bloqueado)

    assert correr_clave(monkeypatch, env, CLAVE, CLAVE) == 1
    assert "solo lectura" in capsys.readouterr().out
