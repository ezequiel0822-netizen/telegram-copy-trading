"""`tct cambiar`: cambiar valores del .env desde la consola, sin romper nada.

Lo pidio el usuario, que no programa: "para eso no hay un comando que se pueda
poner en la consola para cambiarlo solo?". Cambiar una linea es facil; lo que
importa probar es todo lo que NO tiene que hacer:

- tocar otra cosa del archivo (credenciales, comentarios, fines de linea);
- escribir algo que el bot lea distinto de lo que se pidio;
- dejar un archivo que andaba en uno que no arranca;
- aceptar un nombre mal escrito y decir "listo" sin que el bot lo lea nunca;
- mover las dos llaves del dinero real o la clave de arranque.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from tct import cli
from tct.archivo_env import (
    VALORES_NO,
    VARIABLES_DEL_ENV,
    CambioRechazado,
    cambiar_variables,
    es_env_de_un_bot,
    partir_en_lineas,
    poner_linea,
)
from tct.clave import VARIABLE, coincide, escribir_en_env, hashear
from tct.config import VALORES_SI, VARIABLES_OBSOLETAS, _Env, load_settings

BOM = chr(0xFEFF)
RUTA_MT5 = r"C:\Program Files\FxPro - MetaTrader 5\terminal64.exe"

# Como el .env.segunda del usuario el 2026-09-19, con credenciales inventadas.
SEGUNDA = (
    "# Segunda instancia: FxPro demo\r\n"
    "INSTANCE_NAMES=demo,fxpro\r\n"
    "INSTANCE_NAME=fxpro\r\n"
    "DATA_DIR=data/fxpro\r\n"
    "TRADING_MODE=AUTO\r\n"
    "TELEGRAM_API_ID=123\r\n"
    "TELEGRAM_API_HASH=abc\r\n"
    "TELEGRAM_SOURCE_CHATS=-100\r\n"
    "MT5_LOGIN=5550001\r\n"
    "MT5_PASSWORD=Secreta#1\r\n"
    "MT5_SERVER=FxPro-MT5 Demo\r\n"
    f"MT5_PATH={RUTA_MT5}\r\n"
    "DEFAULT_LOT=0.01\r\n"
    "MAX_LOT=0.01\r\n"
    "MAX_OPEN_TRADES=20\r\n"
    "MAX_SIGNALS_PER_DAY=35\r\n"
    "MAX_SPREAD_FROM_ENTRY_PCT=0.05\r\n"
    "MAX_DAILY_LOSS_PCT=0\r\n"
    "# MAX_OPEN_TRADES=99  <- un comentario no es una asignacion\r\n"
    "POSITIONS_PER_SIGNAL=1\r\n"
    "MAX_POSITIONS_PER_SYMBOL=10\r\n"
)

# Lo que el usuario tenia que cambiar a mano ese dia.
LOS_CINCO = [
    "MAX_POSITIONS_PER_SYMBOL=2",
    "MAX_OPEN_TRADES=2",
    "MAX_SIGNALS_PER_DAY=10",
    "MAX_DAILY_LOSS_PCT=5",
    "INSTANCE_NAMES=demo,fxpro,real",
]


@pytest.fixture(autouse=True)
def _sin_variables_del_entorno(monkeypatch):
    """Una variable del entorno le gana al archivo: que ninguna de la maquina
    que corre los tests se meta en el medio."""
    for nombre in VARIABLES_DEL_ENV:
        monkeypatch.delenv(nombre, raising=False)


def archivo(tmp_path: Path, texto: str = SEGUNDA, nombre: str = ".env.segunda") -> Path:
    ruta = tmp_path / nombre
    ruta.write_bytes(texto.encode("utf-8"))
    return ruta


def rechaza(ruta: Path, *asignaciones: str) -> str:
    """Corre el cambio, exige que se rechace SIN tocar el archivo, y devuelve el motivo."""
    original = ruta.read_bytes()
    with pytest.raises(CambioRechazado) as exc:
        cambiar_variables(ruta, list(asignaciones))
    assert ruta.read_bytes() == original, "rechazo el cambio pero toco el archivo"
    return str(exc.value)


# --------------------------------------------------------------------------
# Cambia lo pedido, y nada mas
# --------------------------------------------------------------------------


def test_cambia_esas_lineas_y_ni_un_byte_mas(tmp_path):
    ruta = archivo(tmp_path)

    resultado = cambiar_variables(ruta, LOS_CINCO)

    esperado = (SEGUNDA
                .replace("INSTANCE_NAMES=demo,fxpro\r\n", "INSTANCE_NAMES=demo,fxpro,real\r\n")
                .replace("\r\nMAX_OPEN_TRADES=20\r\n", "\r\nMAX_OPEN_TRADES=2\r\n")
                .replace("MAX_SIGNALS_PER_DAY=35", "MAX_SIGNALS_PER_DAY=10")
                .replace("MAX_DAILY_LOSS_PCT=0", "MAX_DAILY_LOSS_PCT=5")
                .replace("MAX_POSITIONS_PER_SYMBOL=10", "MAX_POSITIONS_PER_SYMBOL=2"))
    assert ruta.read_bytes().decode("utf-8") == esperado
    assert resultado.guardado
    assert [(c.nombre, c.antes, c.despues) for c in resultado.cambios] == [
        ("MAX_POSITIONS_PER_SYMBOL", "10", "2"),
        ("MAX_OPEN_TRADES", "20", "2"),
        ("MAX_SIGNALS_PER_DAY", "35", "10"),
        ("MAX_DAILY_LOSS_PCT", "0", "5"),
        ("INSTANCE_NAMES", "demo,fxpro", "demo,fxpro,real"),
    ]


def test_el_bot_arranca_con_lo_nuevo(tmp_path):
    ruta = archivo(tmp_path)

    cambiar_variables(ruta, LOS_CINCO)

    settings = load_settings(ruta)
    assert settings.max_positions_per_symbol == 2
    assert settings.max_open_trades == 2
    assert settings.max_signals_per_day == 10
    assert settings.max_daily_loss_pct == 5.0
    assert settings.instance_names == ("demo", "fxpro", "real")
    assert settings.mt5_path == RUTA_MT5, "rompio la ruta de MetaTrader"
    assert settings.mt5_password == "Secreta#1", "toco la password"


def test_una_variable_que_no_estaba_se_agrega_al_final(tmp_path):
    ruta = archivo(tmp_path, SEGUNDA.replace("MAX_DAILY_LOSS_PCT=0\r\n", ""))
    original = ruta.read_bytes().decode("utf-8")

    resultado = cambiar_variables(ruta, ["MAX_DAILY_LOSS_PCT=5"])

    assert ruta.read_bytes().decode("utf-8") == original + "MAX_DAILY_LOSS_PCT=5\r\n"
    assert resultado.cambios[0].antes is None
    assert load_settings(ruta).max_daily_loss_pct == 5.0


def test_sin_salto_de_linea_al_final_no_pega_dos_variables(tmp_path):
    ruta = archivo(tmp_path, "INSTANCE_NAME=demo\nMAX_LOT=0.01")

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert ruta.read_text(encoding="utf-8") == "INSTANCE_NAME=demo\nMAX_LOT=0.01\nMAX_OPEN_TRADES=2\n"


def test_si_esta_dos_veces_cambian_las_dos(tmp_path):
    """python-dotenv se queda con la ULTIMA. Cambiar solo la primera dejaba
    vigente el valor viejo, con el comando diciendo que lo cambio."""
    ruta = archivo(tmp_path, "MAX_OPEN_TRADES=20\nMAX_LOT=0.01\nMAX_OPEN_TRADES=30\n")

    resultado = cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert ruta.read_text(encoding="utf-8") == "MAX_OPEN_TRADES=2\nMAX_LOT=0.01\nMAX_OPEN_TRADES=2\n"
    assert resultado.cambios[0].antes == "30", "mostro el valor que el bot NO usaba"


def test_export_y_espacios_alrededor_del_igual(tmp_path):
    ruta = archivo(tmp_path, "export MAX_OPEN_TRADES = 20\n  MAX_LOT=0.01\n")

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2", "MAX_LOT=0.02"])

    assert ruta.read_text(encoding="utf-8") == "MAX_OPEN_TRADES=2\nMAX_LOT=0.02\n"


def test_un_comentario_no_se_toca(tmp_path):
    ruta = archivo(tmp_path)

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert "# MAX_OPEN_TRADES=99  <- un comentario" in ruta.read_text(encoding="utf-8")


def test_un_nombre_que_empieza_igual_no_es_el_mismo(tmp_path):
    ruta = archivo(tmp_path, "MAX_LOTS_VIEJO=9\nMAX_LOT=0.01\n")

    cambiar_variables(ruta, ["MAX_LOT=0.02"])

    assert ruta.read_text(encoding="utf-8") == "MAX_LOTS_VIEJO=9\nMAX_LOT=0.02\n"


def test_la_marca_del_bloc_de_notas_se_conserva(tmp_path):
    ruta = archivo(tmp_path, BOM + "MAX_OPEN_TRADES=20\nMAX_LOT=0.01\n")

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert ruta.read_text(encoding="utf-8") == BOM + "MAX_OPEN_TRADES=2\nMAX_LOT=0.01\n"
    assert load_settings(ruta).max_open_trades == 2


def test_un_caracter_raro_en_otro_valor_no_mueve_nada(tmp_path):
    """U+2028 no es fin de linea para python-dotenv: todo lo que sigue es parte
    del valor de NOTA, aunque parezca otra variable."""
    texto = "NOTA=hola" + chr(0x2028) + "MAX_OPEN_TRADES=99\nMAX_OPEN_TRADES=20\n"
    ruta = archivo(tmp_path, texto)

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert ruta.read_text(encoding="utf-8") == texto.replace("TRADES=20", "TRADES=2")


def test_el_comentario_del_final_de_la_linea_se_conserva(tmp_path):
    ruta = archivo(tmp_path, "MAX_DAILY_LOSS_PCT=0   # en la real poner 5\r\n"
                             "MT5_SERVER='a #b'  # el de la demo\r\n"
                             "MAX_LOT=0.01#pegado no es comentario\r\n")

    cambiar_variables(ruta, ["MAX_DAILY_LOSS_PCT=5", "MT5_SERVER=Otro", "MAX_LOT=0.02"])

    assert ruta.read_bytes().decode("utf-8") == (
        "MAX_DAILY_LOSS_PCT=5   # en la real poner 5\r\n"
        "MT5_SERVER=Otro  # el de la demo\r\n"
        "MAX_LOT=0.02\r\n")


def test_un_valor_con_comilla_simple_y_numeral_va_entre_dobles(tmp_path):
    ruta = archivo(tmp_path, "MAX_LOT=0.01\n")

    cambiar_variables(ruta, ["MT5_SERVER=Broker's Server #2"])

    assert load_settings(ruta).mt5_server == "Broker's Server #2"


def test_un_valor_de_varias_lineas_en_otra_variable_no_frena_el_cambio(tmp_path):
    """Con CRLF: leido del texto, el valor traia \\r\\n; leido del archivo,
    como lo lee el bot, \\n. Parecia que el cambio lo habia movido."""
    ruta = archivo(tmp_path, 'TELEGRAM_SOURCE_CHATS="-1001,\r\n-1002"\r\nMAX_OPEN_TRADES=20\r\n')

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert load_settings(ruta).telegram_source_chats == ["-1001", "-1002"]
    assert load_settings(ruta).max_open_trades == 2


def test_cambiar_un_valor_de_varias_lineas_no_deja_pedazos_sueltos(tmp_path):
    """Se reemplaza la primera linea fisica y el resto del valor quedaba como
    una 'variable' sin valor, que la red no veia. Ahora cuenta como otra
    variable que aparecio, y no se guarda."""
    ruta = archivo(tmp_path, 'TELEGRAM_SOURCE_CHATS="-1001,\r\n-1002"\r\nMAX_LOT=0.01\r\n')

    rechaza(ruta, "TELEGRAM_SOURCE_CHATS=-1003")


def test_una_linea_que_empieza_con_un_cr_suelto_tambien_se_cambia(tmp_path):
    """python-dotenv corta en un CR suelto: lo que sigue es una linea, y la
    asignacion que hay ahi es la que vale."""
    ruta = archivo(tmp_path, "MAX_LOT=0.01\r\nMAX_OPEN_TRADES=5\r\n\rMAX_OPEN_TRADES=20\r\n")

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert load_settings(ruta).max_open_trades == 2


def test_tct_clave_con_un_cr_suelto_deja_la_huella_nueva(tmp_path):
    ruta = archivo(tmp_path, f"MT5_LOGIN=123\r\n{VARIABLE}=\r\n\r{VARIABLE}={hashear('vieja1')}\r\n")

    escribir_en_env(ruta, hashear("nueva1"))

    assert coincide("nueva1", load_settings(ruta).clave_de_arranque)


def test_tct_clave_tiene_la_misma_ultima_red(tmp_path, monkeypatch, capsys):
    """Sin ella, un 'Listo' podia dejar vigente la huella vieja o tocar otra
    variable. Ahora no guarda y lo dice."""
    ruta = archivo(tmp_path)
    from tct import archivo_env

    real = archivo_env.poner_linea
    monkeypatch.setattr("tct.archivo_env.poner_linea",
                        lambda *a, **k: real(*a, **k).replace("MAX_LOT=0.01", "MAX_LOT=1"))
    contestar(monkeypatch, "oro4432", "oro4432")

    assert cli.cmd_clave(argparse.Namespace(env_file=str(ruta))) == 1

    assert "MAX_LOT" in capsys.readouterr().out
    assert ruta.read_bytes() == SEGUNDA.encode("utf-8")


def test_si_el_archivo_cambia_mientras_se_guarda_no_lo_pisa(tmp_path, monkeypatch):
    """El Bloc de notas no bloquea el archivo: si alguien guarda justo en ese
    momento, reemplazarlo borraria lo que guardo."""
    ruta = archivo(tmp_path)
    from tct import archivo_env

    real = archivo_env._error_al_cargar

    def mientras_tanto(archivo, ruta_real):
        if archivo != ruta_real:  # ya se esta revisando el temporal
            ruta.write_bytes(SEGUNDA.replace("MAX_LOT=0.01", "MAX_LOT=0.05").encode("utf-8"))
        return real(archivo, ruta_real)

    monkeypatch.setattr("tct.archivo_env._error_al_cargar", mientras_tanto)

    with pytest.raises(CambioRechazado, match="cambio mientras se guardaba"):
        cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])
    assert load_settings(ruta).max_lot == 0.05, "piso lo que guardo la otra persona"


def test_partir_en_lineas_no_pierde_ni_agrega_nada():
    import random

    azar = random.Random(4432)
    piezas = ["\n", "\r", "\r\n", "A=1", " ", "#", chr(0x2028), chr(0x85), BOM, "="]
    for _ in range(3000):
        texto = "".join(azar.choice(piezas) for _ in range(azar.randint(0, 12)))
        lineas = partir_en_lineas(texto)
        assert "".join(lineas) == texto
        assert all(not re.search(r"\r\n|\n|\r", l[:-1].rstrip("\r")) for l in lineas if l)


@pytest.mark.parametrize("nombre,es", [
    (".env", True), (".env.segunda", True), (".env.real", True), (".env.local", True),
    (".env.example", False), (".env.real.example", False), (".env.segunda.tmp", False),
    (".env.tmp", False), (".env.segunda.bak", False), (".env.txt", False), ("env", False),
])
def test_cuales_son_archivos_de_un_bot(nombre, es):
    assert es_env_de_un_bot(nombre) is es


def test_si_no_hay_nada_que_cambiar_no_reescribe(tmp_path):
    ruta = archivo(tmp_path)
    antes = ruta.stat().st_mtime_ns

    resultado = cambiar_variables(ruta, ["MAX_OPEN_TRADES=20", "MAX_LOT=0.01"])

    assert not resultado.guardado
    assert not any(c.cambia for c in resultado.cambios)
    assert ruta.read_bytes() == SEGUNDA.encode("utf-8")
    assert ruta.stat().st_mtime_ns == antes


def test_no_deja_archivos_temporales(tmp_path):
    ruta = archivo(tmp_path)

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])
    with pytest.raises(CambioRechazado):
        cambiar_variables(ruta, ["DEFAULT_LOT=0.5"])

    assert sorted(p.name for p in tmp_path.iterdir()) == [".env.segunda"]


# --------------------------------------------------------------------------
# Escribe lo que el bot va a leer
# --------------------------------------------------------------------------


def test_la_ruta_de_metatrader_va_sin_comillas(tmp_path):
    """Con comillas dobles, el \\t de terminal64.exe se vuelve un tabulador."""
    ruta = archivo(tmp_path, "MAX_LOT=0.01\n")
    nueva = r"C:\Program Files\MetaTrader 5\terminal64.exe"

    cambiar_variables(ruta, [f"MT5_PATH={nueva}"])

    assert f"MT5_PATH={nueva}\n" in ruta.read_text(encoding="utf-8")
    assert load_settings(ruta).mt5_path == nueva


def test_las_comillas_que_pone_la_consola_se_sacan(tmp_path):
    ruta = archivo(tmp_path, "MAX_LOT=0.01\n")

    cambiar_variables(ruta, ['MT5_SERVER="FxPro-MT5 Live"', "MT5_LOGIN='777'"])

    texto = ruta.read_text(encoding="utf-8")
    assert "MT5_SERVER=FxPro-MT5 Live\n" in texto
    assert "MT5_LOGIN=777\n" in texto


def test_un_valor_con_numeral_se_escribe_para_que_no_sea_comentario(tmp_path):
    """Pelado, python-dotenv leeria 'FxPro' y tiraria ' #2' como comentario."""
    ruta = archivo(tmp_path, "MAX_LOT=0.01\n")

    cambiar_variables(ruta, ["MT5_SERVER=FxPro #2"])

    assert load_settings(ruta).mt5_server == "FxPro #2"
    # Comillas SIMPLES: las dobles obligan a escapar las barras, y el archivo
    # lo va a volver a leer una persona.
    assert "MT5_SERVER='FxPro #2'\n" in ruta.read_text(encoding="utf-8")


def test_una_comilla_doble_suelta_en_el_valor_se_rechaza(tmp_path):
    """Lo que deja la consola cuando la comilla de cierre se escapa sola."""
    motivo = rechaza(archivo(tmp_path), 'MT5_SERVER=FxPro-MT5"')

    assert "comilla doble" in motivo


def test_un_valor_que_el_bot_leeria_distinto_se_rechaza(tmp_path):
    """`${...}` lo reemplaza python-dotenv por otra variable, con o sin comillas."""
    ruta = archivo(tmp_path, "MAX_LOT=0.01\n")

    motivo = rechaza(ruta, "MT5_SERVER=${MAX_LOT}")

    assert "MT5_SERVER" in motivo


def test_la_ultima_red_ataja_un_valor_mal_escrito(tmp_path, monkeypatch):
    """Lo que atrapa la relectura del archivo, forzado: si algun dia la forma de
    escribir un valor se equivoca -comillas dobles en MT5_PATH, la trampa de
    §5-, lo que el bot leeria no es lo pedido y no se guarda."""
    ruta = archivo(tmp_path)
    monkeypatch.setattr("tct.archivo_env._como_se_escribe", lambda _n, v: f'"{v}"')

    motivo = rechaza(ruta, r"MT5_PATH=C:\MT5\terminal64.exe")

    assert "MT5_PATH" in motivo


def test_la_ultima_red_ataja_un_valor_que_igual_cargaria(tmp_path, monkeypatch):
    """El caso que SOLO la relectura atrapa: el bot arrancaria igual, con 20 en
    vez del 2 pedido, y el comando habria dicho '20 -> 2'."""
    ruta = archivo(tmp_path)
    monkeypatch.setattr("tct.archivo_env._como_se_escribe", lambda _n, v: f"{v}0")

    motivo = rechaza(ruta, "MAX_OPEN_TRADES=2")

    assert "MAX_OPEN_TRADES no quedaria como se pidio" in motivo


def test_la_ultima_red_ataja_una_variable_que_no_se_pidio(tmp_path, monkeypatch):
    ruta = archivo(tmp_path)
    from tct import archivo_env

    real = archivo_env.poner_linea

    def pisa_tambien_el_lote(texto, nombre, linea, **kw):
        return real(texto, nombre, linea, **kw).replace("MAX_LOT=0.01", "MAX_LOT=1")

    monkeypatch.setattr("tct.archivo_env.poner_linea", pisa_tambien_el_lote)

    motivo = rechaza(ruta, "MAX_OPEN_TRADES=2")

    assert "MAX_LOT" in motivo


def test_un_vacio_vuelve_al_valor_por_defecto(tmp_path):
    ruta = archivo(tmp_path)

    cambiar_variables(ruta, ["MAX_DAILY_LOSS_PCT="])

    assert "MAX_DAILY_LOSS_PCT=\r\n" in ruta.read_bytes().decode("utf-8")
    assert load_settings(ruta).max_daily_loss_pct == 0.0


def test_minusculas_en_el_nombre_valen(tmp_path):
    ruta = archivo(tmp_path)

    cambiar_variables(ruta, ["max_open_trades=2"])

    assert load_settings(ruta).max_open_trades == 2


# --------------------------------------------------------------------------
# Lo que se rechaza, sin tocar el archivo
# --------------------------------------------------------------------------


def test_un_nombre_mal_escrito_no_se_agrega(tmp_path):
    """Si se agregara, el bot lo ignoraria y el comando habria dicho "listo"."""
    motivo = rechaza(archivo(tmp_path), "MAX_OPEN_TRADE=2")

    assert "Quisiste decir MAX_OPEN_TRADES" in motivo


def test_dice_todos_los_errores_de_una_vez(tmp_path):
    motivo = rechaza(archivo(tmp_path), "MAX_OPEN_TRADE=2", "MAX_OPEN_TRADES=2", "MAX_LOTE=1")

    assert "MAX_OPEN_TRADE " in motivo and "MAX_LOTE" in motivo


@pytest.mark.parametrize("asignacion", [
    "MAX_OPEN_TRADES=dos",
    "MAX_OPEN_TRADES=2.5",
    "MAX_DAILY_LOSS_PCT=cinco",
    "REQUIRE_STOP_LOSS=ture",
    "ENABLE_OLLAMA=s\u00ed",
])
def test_un_valor_que_no_es_del_tipo_se_rechaza(tmp_path, asignacion):
    motivo = rechaza(archivo(tmp_path), asignacion)

    assert asignacion.split("=")[0] in motivo


@pytest.mark.parametrize("asignacion", [
    "MAX_DAILY_LOSS_PCT=-5",
    "MAX_DAILY_LOSS_PCT=nan",
    "MAX_DAILY_LOSS_PCT=inf",
    "MAX_LOT=nan",
    "MAX_LOT=1e999",
    "MAX_SPREAD_FROM_ENTRY_PCT=-0.05",
    "MAX_OPEN_TRADES=-1",
])
def test_un_numero_que_apaga_una_proteccion_se_rechaza(tmp_path, asignacion):
    """config.py los acepta: el freno diario en -5 o en nan queda APAGADO
    mientras el arranque sigue mostrando 'Tope perdida dia: -5.0%'."""
    rechaza(archivo(tmp_path), asignacion)


def test_el_freno_en_negativo_dice_como_se_escribe(tmp_path):
    motivo = rechaza(archivo(tmp_path), "MAX_DAILY_LOSS_PCT=-5")

    assert "sin signo" in motivo


@pytest.mark.parametrize("asignacion", [
    "TRADING_MODE=LIVE",
    "ALLOW_LIVE_TRADING=true",
])
def test_las_dos_llaves_del_dinero_real_se_cambian_a_mano(tmp_path, asignacion):
    motivo = rechaza(archivo(tmp_path), asignacion)

    assert "notepad" in motivo


def test_la_clave_se_pone_con_tct_clave(tmp_path):
    motivo = rechaza(archivo(tmp_path), f"{VARIABLE}={hashear('oro4432')}")

    assert "tct clave" in motivo


@pytest.mark.parametrize("nombre", VARIABLES_OBSOLETAS)
def test_las_variables_de_los_avisos_ya_no_existen(tmp_path, nombre):
    motivo = rechaza(archivo(tmp_path), f"{nombre}=algo")

    assert "ya no existe" in motivo


@pytest.mark.parametrize("asignacion", ["MAX_OPEN_TRADES", "=2", "MAX_OPEN_TRADES 2"])
def test_lo_que_no_es_nombre_igual_valor_se_rechaza(tmp_path, asignacion):
    rechaza(archivo(tmp_path), asignacion)


@pytest.mark.parametrize("asignaciones", [
    ["MT5_PASSWORD", "=", "Fxpro2024Nueva"],    # espacios alrededor del =
    ["MT5_PASSWORD", "=Fxpro2024Nueva"],
    ["MT5_PASSWORD=", "Fxpro2024Nueva"],        # espacio despues del =
    ["MT5_PASSWORD=Fxpro2024Nueva"],            # en la linea: no se acepta
    ["MT5_PASSWORD=Fxpro2024", "Nueva"],        # y partida por un espacio
    ["MAX_OPEN_TRADES=2", "Fxpro2024Nueva"],    # una palabra suelta cualquiera
])
def test_una_password_mal_escrita_no_se_repite_en_pantalla(tmp_path, asignaciones):
    """Solo letras y numeros tiene pinta de nombre de variable: igual no se
    repite, porque tambien puede ser una password."""
    motivo = rechaza(archivo(tmp_path), *asignaciones)

    assert "Fxpro2024" not in motivo and "Nueva" not in motivo


def test_con_espacios_alrededor_del_igual_lo_dice(tmp_path):
    motivo = rechaza(archivo(tmp_path), "MAX_OPEN_TRADES", "=", "2")

    assert "'MAX_OPEN_TRADES' va pegado a su valor" in motivo


# --------------------------------------------------------------------------
# Lo que la consola (cmd.exe) le hace a lo que se escribe
# --------------------------------------------------------------------------


def test_una_password_en_la_linea_se_rechaza_y_dice_como_pedirla(tmp_path):
    """cmd se come los ^, corta en & y reemplaza %ALGO%: guardaba otra
    password y en pantalla salia **** -> ****."""
    ruta = archivo(tmp_path)

    motivo = rechaza(ruta, "MT5_PASSWORD=Ab1cd2")

    assert f"tct cambiar --env-file {ruta} MT5_PASSWORD" in motivo


def test_una_password_pedida_se_guarda_tal_cual_con_cualquier_caracter(tmp_path):
    ruta = archivo(tmp_path)
    rara = "Ab^1&c|d>e%OS%\"f'g #h\\"
    pedidas = []

    def pedir(nombre):
        pedidas.append(nombre)
        return rara

    resultado = cambiar_variables(ruta, ["MT5_PASSWORD"], pedir_secreto=pedir)

    assert pedidas == ["MT5_PASSWORD"]
    assert resultado.guardado
    assert load_settings(ruta).mt5_password == rara


def test_la_password_se_pide_despues_de_revisar_lo_demas(tmp_path):
    """Que nadie la escriba dos veces para enterarse de un nombre mal escrito."""
    def no_deberia_preguntar(_nombre):
        raise AssertionError("pidio la password con otro error en la linea")

    ruta = archivo(tmp_path)
    original = ruta.read_bytes()
    with pytest.raises(CambioRechazado):
        cambiar_variables(ruta, ["MT5_PASSWORD", "MAX_OPEN_TRADE=2"],
                          pedir_secreto=no_deberia_preguntar)
    assert ruta.read_bytes() == original


def test_una_password_vacia_no_se_guarda(tmp_path):
    ruta = archivo(tmp_path)
    original = ruta.read_bytes()

    with pytest.raises(CambioRechazado):
        cambiar_variables(ruta, ["MT5_PASSWORD"], pedir_secreto=lambda _n: "   ")

    assert ruta.read_bytes() == original


def test_un_valor_con_espacios_partido_por_la_consola_dice_que_van_comillas(tmp_path):
    """`tct mt5` muestra el servidor sin comillas: copiado tal cual, la
    consola lo parte en dos. El consejo viejo ('va todo junto') llevaba a
    guardar FxPro-MT5Live."""
    motivo = rechaza(archivo(tmp_path), "MT5_SERVER=FxPro-MT5", "Live", "MAX_OPEN_TRADES=2")

    assert 'MT5_SERVER="FxPro-MT5 Live"' in motivo
    assert "DOBLES" in motivo


def test_un_vacio_seguido_de_una_password_a_pedir_no_es_un_valor_partido(tmp_path):
    ruta = archivo(tmp_path)

    cambiar_variables(ruta, ["MAX_DAILY_LOSS_PCT=", "MT5_PASSWORD"],
                      pedir_secreto=lambda _n: "Nueva1")

    settings = load_settings(ruta)
    assert settings.max_daily_loss_pct == 0.0
    assert settings.mt5_password == "Nueva1"


@pytest.mark.parametrize("asignacion", [
    'DATA_DIR=data\\fxpro2" MAX_OPEN_TRADES=3',               # barra antes de la comilla
    "DATA_DIR=data/fxpro2" + chr(0xA0) + "MAX_OPEN_TRADES=3",  # espacio duro pegado
])
def test_un_valor_que_se_trago_otro_cambio_se_rechaza(tmp_path, asignacion):
    """Con una ruta nueva y valida, el bot arrancaba con una carpeta de datos
    vacia: sin las posiciones abiertas ni el cupo del dia."""
    rechaza(archivo(tmp_path), asignacion)


def test_la_misma_variable_con_dos_valores_se_rechaza(tmp_path):
    motivo = rechaza(archivo(tmp_path), "MAX_OPEN_TRADES=2", "MAX_OPEN_TRADES=3")

    assert "dos veces" in motivo


def test_la_misma_variable_con_el_mismo_valor_vale(tmp_path):
    ruta = archivo(tmp_path)

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2", "MAX_OPEN_TRADES=2"])

    assert load_settings(ruta).max_open_trades == 2


@pytest.mark.parametrize("asignaciones", [
    ["DEFAULT_LOT=0.5"],                       # mas que MAX_LOT
    ["INSTANCE_NAMES=demo,real"],              # sin la instancia de este archivo
    ["INSTANCE_NAMES=demo,fxpro,todos"],       # un nombre reservado
    ["MT5_PATH=C:\\x\tterminal64.exe"],       # un tabulador en la ruta
])
def test_un_cambio_con_el_que_el_bot_no_arrancaria_no_se_guarda(tmp_path, asignaciones):
    motivo = rechaza(archivo(tmp_path), *asignaciones)

    assert "no arrancaria" in motivo


def test_un_archivo_que_ya_no_arrancaba_se_puede_ir_completando(tmp_path):
    """El `.env.real` del usuario: LIVE sin credenciales todavia. Corregirle
    los numeros no puede esperar a tener la cuenta fondeada."""
    real = ("TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=true\nINSTANCE_NAME=real\n"
            "INSTANCE_NAMES=demo,fxpro,real\nMAX_SIGNALS_PER_DAY=5\nMAX_DAILY_LOSS_PCT=3\n")
    ruta = archivo(tmp_path, real, ".env.real")
    with pytest.raises(Exception) as ya_estaba:
        load_settings(ruta)

    resultado = cambiar_variables(ruta, ["MAX_SIGNALS_PER_DAY=10", "MAX_DAILY_LOSS_PCT=5"])

    assert resultado.guardado
    assert resultado.error_que_queda == str(ya_estaba.value)
    assert "MAX_SIGNALS_PER_DAY=10\nMAX_DAILY_LOSS_PCT=5\n" in ruta.read_text(encoding="utf-8")


REAL_SIN_CREDENCIALES = ("TRADING_MODE=LIVE\r\nALLOW_LIVE_TRADING=true\r\nINSTANCE_NAME=real\r\n"
                         "INSTANCE_NAMES=demo,fxpro,real\r\nMAX_LOT=0.01\r\n")


def test_las_credenciales_de_la_real_se_pueden_poner_de_a_una(tmp_path):
    """`tct mt5` da el login y el servidor; la password viene aparte. Con el
    error comparado letra por letra, 'Falta: MT5_PASSWORD, MT5_SERVER' era
    'otro error' y se rechazaba un cambio que acercaba el archivo a andar."""
    ruta = archivo(tmp_path, REAL_SIN_CREDENCIALES, ".env.real")

    uno = cambiar_variables(ruta, ["MT5_LOGIN=7001234"])
    dos = cambiar_variables(ruta, ['MT5_SERVER="FxPro-MT5 Live"'])
    tres = cambiar_variables(ruta, ["MT5_PASSWORD"], pedir_secreto=lambda _n: "Xy^9&k")

    assert uno.guardado and "MT5_PASSWORD" in uno.error_que_queda
    assert dos.guardado and "MT5_PASSWORD" in dos.error_que_queda
    assert tres.guardado and tres.error_que_queda is None
    settings = load_settings(ruta)
    assert (settings.mt5_login, settings.mt5_server, settings.mt5_password) == (
        "7001234", "FxPro-MT5 Live", "Xy^9&k")


def test_en_un_archivo_que_no_arrancaba_un_error_sin_nombre_es_del_cambio(tmp_path):
    """'Una instancia no se puede llamar todos' no nombra ninguna variable: no
    se puede saber de quien es, asi que se toma como de este cambio."""
    ruta = archivo(tmp_path, REAL_SIN_CREDENCIALES, ".env.real")

    motivo = rechaza(ruta, "INSTANCE_NAMES=demo,fxpro,real,todos")

    assert "no arrancaria" in motivo


def test_a_un_archivo_que_no_arrancaba_no_se_le_agrega_otro_error(tmp_path):
    real = ("TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=true\nINSTANCE_NAME=real\n"
            "INSTANCE_NAMES=demo,fxpro,real\nMAX_LOT=0.01\n")

    motivo = rechaza(archivo(tmp_path, real, ".env.real"), "DEFAULT_LOT=0.5")

    assert "MAX_LOT" in motivo


def test_un_error_viejo_no_tapa_un_valor_mal_escrito(tmp_path):
    """`load_settings` para en el PRIMER error. Si el archivo ya tenia uno que
    salta antes, el valor nuevo no llega a revisarse ahi: 'el mismo error que
    antes' dejaria pasar un MAX_OPEN_TRADES=dos. Por eso el tipo se revisa
    aparte."""
    roto = SEGUNDA.replace("TRADING_MODE=AUTO", "TRADING_MODE=BANANA")

    motivo = rechaza(archivo(tmp_path, roto), "MAX_OPEN_TRADES=dos")

    assert "numero entero" in motivo


def test_una_clave_escrita_a_mano_no_impide_cambiar_otra_cosa(tmp_path):
    """Ese error nombra el archivo ('tct clave --env-file ...'). Revisado sobre
    el temporal, nombraba al temporal, parecia un error NUEVO y se rechazaba un
    cambio que no tenia nada que ver."""
    ruta = archivo(tmp_path, SEGUNDA + f"{VARIABLE}=oro4432\r\n")

    resultado = cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert resultado.guardado
    assert f"--env-file {ruta}\n" in resultado.error_que_queda + "\n"
    assert ".tmp" not in resultado.error_que_queda, "el error habla del archivo temporal"


def test_el_mismo_error_de_antes_no_frena_un_cambio_de_esa_variable(tmp_path):
    """Si el error es palabra por palabra el que ya estaba, no lo trajo este
    cambio -aunque sea de la misma variable-, y el archivo se guarda igual."""
    ruta = archivo(tmp_path, SEGUNDA.replace("DEFAULT_LOT=0.01", "DEFAULT_LOT=0"))
    with pytest.raises(Exception) as ya_estaba:
        load_settings(ruta)

    resultado = cambiar_variables(ruta, ["DEFAULT_LOT=0,0"])

    assert resultado.guardado
    assert resultado.error_que_queda == str(ya_estaba.value)


def test_un_archivo_que_no_existe_no_se_crea(tmp_path):
    ruta = tmp_path / ".env.segunada"

    with pytest.raises(CambioRechazado):
        cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert not ruta.exists()


def test_una_plantilla_no_se_toca(tmp_path):
    """Con TAB, despues de .env.real viene .env.real.example: se editaba la
    plantilla, la salida parecia la de .env.real, y el bot real seguia sin
    freno."""
    motivo = rechaza(archivo(tmp_path, REAL_SIN_CREDENCIALES, ".env.real.example"),
                     "MAX_DAILY_LOSS_PCT=5")

    # La frase entera: pytest le pone al directorio temporal el nombre de este
    # test, que tiene la palabra "plantilla" adentro, y la ruta sale en el
    # mensaje. Buscar solo esa palabra pasaba sin que el codigo la dijera.
    assert "es una plantilla" in motivo


@pytest.mark.parametrize("nombre,texto", [
    ("README.md", "# Bot\n\nUsar tct run.\n"),
    ("iniciar_real.bat", "@echo off\r\ntct run --env-file .env.real\r\npause\r\n"),
    ("pyproject.toml", '[project]\nname = "tct"\nversion = "1.0"\n'),
])
def test_un_archivo_que_no_es_de_un_bot_no_se_toca(tmp_path, nombre, texto):
    rechaza(archivo(tmp_path, texto, nombre), "MAX_DAILY_LOSS_PCT=5")


def test_un_env_con_nombre_de_bot_pero_que_no_es_configuracion_no_se_toca(tmp_path):
    """El nombre no alcanza: `.env.notas` podria ser cualquier cosa."""
    motivo = rechaza(archivo(tmp_path, "unas notas mias\nnada=importante\n", ".env.notas"),
                     "MAX_DAILY_LOSS_PCT=5")

    assert "no parece la configuracion de un bot" in motivo


@pytest.mark.parametrize("copia", [".env.real.bak", ".env.txt", ".env.real.tmp",
                                   ".env.real - copia.txt"])
def test_una_copia_del_env_no_se_toca(tmp_path, copia):
    """El peor caso de este comando: con TAB, al lado de .env.real aparecen el
    respaldo, el .txt del Bloc de notas y el temporal de un cambio cortado.
    Editar la copia salia "Listo" y el bot real seguia con el freno en 0."""
    real = archivo(tmp_path, REAL_SIN_CREDENCIALES, ".env.real")
    ruta = archivo(tmp_path, REAL_SIN_CREDENCIALES, copia)

    motivo = rechaza(ruta, "MAX_DAILY_LOSS_PCT=5")

    assert "copia" in motivo or "respaldo" in motivo
    assert real.read_bytes() == REAL_SIN_CREDENCIALES.encode("utf-8")


@pytest.mark.parametrize("copia,sugerido", [(".env.real.bak", ".env.real"),
                                            (".env.txt", ".env"),
                                            (".env.segunda.tmp", ".env.segunda")])
def test_al_rechazar_una_copia_dice_cual_era_el_bueno(tmp_path, copia, sugerido):
    motivo = rechaza(archivo(tmp_path, REAL_SIN_CREDENCIALES, copia), "MAX_DAILY_LOSS_PCT=5")

    assert str(tmp_path / sugerido) in motivo


def test_el_valor_partido_no_se_come_la_password_que_venia_atras(tmp_path):
    """La linea sugerida se copia tal cual: con MT5_PASSWORD adentro del valor,
    dejaba la cuenta real con un servidor inventado y sin pedir la password."""
    motivo = rechaza(archivo(tmp_path, REAL_SIN_CREDENCIALES, ".env.real"),
                     "MT5_LOGIN=7001234", "MT5_SERVER=FxPro-MT5", "Live", "MT5_PASSWORD")

    assert 'MT5_SERVER="FxPro-MT5 Live"' in motivo
    assert "MT5_PASSWORD" not in motivo.split("MT5_SERVER=\"")[1]


def test_la_red_de_los_valores_sola_ataja_el_pedazo_suelto(tmp_path, monkeypatch):
    """Son dos redes a proposito y cada una se prueba SIN la otra: si no, apagar
    una no pone en rojo ningun test y parece que sobra. Esta compara lo que el
    bot LEE."""
    monkeypatch.setattr("tct.archivo_env.verificar_asignaciones", lambda *a, **k: None)
    ruta = archivo(tmp_path, 'TELEGRAM_SOURCE_CHATS="-1001,\r\n-1002"\r\nMAX_LOT=0.01\r\n')

    rechaza(ruta, "TELEGRAM_SOURCE_CHATS=-1003")


def test_la_red_de_las_asignaciones_sola_ataja_la_linea_tapada(tmp_path, monkeypatch):
    """Esta compara asignacion por asignacion: la linea suelta queda tapada por
    otra de mas abajo, el bot lee lo mismo, y los valores no la ven."""
    monkeypatch.setattr("tct.archivo_env.verificar_lectura", lambda *a, **k: None)
    ruta = archivo(tmp_path, 'MT5_SERVER="FxPro\r\nMAX_LOT=0.5"\r\nMAX_LOT=0.01\r\n')

    rechaza(ruta, "MT5_SERVER=FxPro-MT5 Live")


def test_una_linea_suelta_que_el_bot_no_leeria_igual_no_se_guarda(tmp_path):
    """Queda tapada por otra asignacion de mas abajo, asi que el bot lee lo
    mismo: no hay plata en juego, pero el archivo queda con basura adentro."""
    ruta = archivo(tmp_path, 'MT5_SERVER="FxPro\r\nMAX_LOT=0.5"\r\nMAX_LOT=0.01\r\n')

    motivo = rechaza(ruta, "MT5_SERVER=FxPro-MT5 Live")

    assert "linea suelta" in motivo


def test_un_pedazo_de_valor_no_se_nombra_como_si_fuera_una_variable(tmp_path):
    ruta = archivo(tmp_path, 'TELEGRAM_SOURCE_CHATS="-1001,\r\n-1002"\r\nMAX_LOT=0.01\r\n')

    motivo = rechaza(ruta, "TELEGRAM_SOURCE_CHATS=-1003")

    assert "linea suelta" in motivo
    assert "-1002" not in motivo


def test_los_comandos_que_sugiere_van_entre_comillas_si_la_ruta_tiene_espacios(tmp_path):
    carpeta = tmp_path / "telegram copy trading"
    carpeta.mkdir()
    ruta = archivo(carpeta)

    motivo = rechaza(ruta, "TRADING_MODE=LIVE")

    assert f'notepad "{ruta}"' in motivo


def test_un_archivo_que_no_es_utf8_no_se_toca(tmp_path):
    ruta = tmp_path / ".env"
    original = "MT5_PASSWORD=contrase\xf1a\nMAX_OPEN_TRADES=20\n".encode("cp1252")
    ruta.write_bytes(original)

    motivo = rechaza(ruta, "MAX_OPEN_TRADES=2")

    assert "UTF-8" in motivo


# --------------------------------------------------------------------------
# Lo que avisa
# --------------------------------------------------------------------------


def test_avisa_si_una_variable_del_entorno_le_gana_al_archivo(tmp_path, monkeypatch):
    ruta = archivo(tmp_path)
    monkeypatch.setenv("MAX_OPEN_TRADES", "7")

    resultado = cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    assert resultado.pisadas_por_el_entorno == {"MAX_OPEN_TRADES": "7"}


def test_al_cambiar_el_roster_dice_como_esta_en_los_otros(tmp_path):
    archivo(tmp_path, "INSTANCE_NAME=demo\nINSTANCE_NAMES=demo,fxpro,real\n", ".env")
    archivo(tmp_path, "INSTANCE_NAME=real\nINSTANCE_NAMES=Demo, fxpro,real\n", ".env.real")
    archivo(tmp_path, "INSTANCE_NAMES=demo,real\n", ".env.real.example")
    ruta = archivo(tmp_path)

    resultado = cambiar_variables(ruta, ["INSTANCE_NAMES=demo,fxpro,real"])

    assert resultado.rosters_de_los_otros == {
        ".env": "demo,fxpro,real",
        ".env.real": "Demo, fxpro,real",
    }


# --------------------------------------------------------------------------
# La tabla de variables tiene que ser la de config.py
# --------------------------------------------------------------------------


def test_la_tabla_de_variables_es_la_que_lee_config():
    """Si alguien agrega una variable a `load_settings` y no a esta tabla,
    `tct cambiar` la rechazaria como mal escrita. Esto lo hace fallar aca."""
    fuente = (Path(__file__).resolve().parent.parent / "src" / "tct" / "config.py").read_text(
        encoding="utf-8")
    leidas = dict(
        (nombre, tipo)
        for tipo, nombre in re.findall(r"env\.(str|int|float|bool|list)\(\s*\"([A-Z0-9_]+)\"", fuente)
    )

    tabla = {n: t for n, t in VARIABLES_DEL_ENV.items() if n != VARIABLE}
    assert tabla == leidas
    assert VARIABLES_DEL_ENV[VARIABLE] == "str"


def test_si_y_no_son_los_de_config():
    for valor in VALORES_SI:
        assert _Env({"X": valor}).bool("X") is True
    for valor in VALORES_NO:
        assert _Env({"X": valor}).bool("X", default=True) is False


# --------------------------------------------------------------------------
# tct clave usa el mismo camino, y conviven
# --------------------------------------------------------------------------


def test_la_clave_y_los_cambios_conviven(tmp_path):
    ruta = archivo(tmp_path)
    escribir_en_env(ruta, hashear("oro4432"))

    cambiar_variables(ruta, ["MAX_OPEN_TRADES=2"])

    settings = load_settings(ruta)
    assert settings.max_open_trades == 2
    assert coincide("oro4432", settings.clave_de_arranque)


def test_poner_linea_con_comentario_solo_cuando_agrega():
    assert poner_linea("A=1\n", "B", "B=2", comentario="# nota") == "A=1\n\n# nota\nB=2\n"
    assert poner_linea("B=1\n", "B", "B=2", comentario="# nota") == "B=2\n"


# --------------------------------------------------------------------------
# El comando
# --------------------------------------------------------------------------


def correr(*argv: str) -> int:
    return cli.main(list(argv))


def test_el_comando_muestra_antes_y_despues(tmp_path, capsys):
    ruta = archivo(tmp_path)

    assert correr("cambiar", "--env-file", str(ruta), *LOS_CINCO) == 0

    salida = capsys.readouterr().out
    assert re.search(r"MAX_OPEN_TRADES\s+20\s+->\s+2", salida)
    assert re.search(r"INSTANCE_NAMES\s+demo,fxpro\s+->\s+demo,fxpro,real", salida)
    assert "cerralo y volvelo a abrir" in salida


@pytest.mark.parametrize("argv", [
    ["--env-file", "{ruta}", "cambiar", "MAX_OPEN_TRADES=2"],
    ["cambiar", "--env-file", "{ruta}", "MAX_OPEN_TRADES=2"],
    ["cambiar", "MAX_OPEN_TRADES=2", "--env-file", "{ruta}"],
])
def test_env_file_en_cualquier_lugar(tmp_path, argv):
    ruta = archivo(tmp_path)

    assert correr(*[a.format(ruta=ruta) for a in argv]) == 0

    assert load_settings(ruta).max_open_trades == 2


def test_env_file_en_el_medio_de_los_cambios(tmp_path):
    """argparse dejaba los de despues de la opcion como 'unrecognized
    arguments', en ingles, que es la trampa de §5."""
    ruta = archivo(tmp_path)

    assert correr("cambiar", "MAX_OPEN_TRADES=2", "--env-file", str(ruta), "MAX_LOT=0.02") == 0

    settings = load_settings(ruta)
    assert (settings.max_open_trades, settings.max_lot) == (2, 0.02)


def test_los_otros_comandos_siguen_rechazando_lo_que_sobra():
    with pytest.raises(SystemExit) as salida:
        correr("status", "de_mas")
    assert salida.value.code == 2


def test_una_opcion_desconocida_en_cambiar_se_rechaza(tmp_path):
    ruta = archivo(tmp_path)

    with pytest.raises(SystemExit):
        correr("cambiar", "MAX_OPEN_TRADES=2", "--env-file", str(ruta), "--forzar")
    assert ruta.read_bytes() == SEGUNDA.encode("utf-8")


def test_la_ayuda_dice_lo_de_las_comillas_y_las_passwords(capsys):
    with pytest.raises(SystemExit):
        correr("cambiar", "--help")

    ayuda = capsys.readouterr().out
    assert "comillas DOBLES" in ayuda
    assert "MT5_PASSWORD" in ayuda and "TRADING_MODE" in ayuda


def test_con_la_salida_a_un_archivo_un_emoji_no_revienta_despues_de_guardar(tmp_path, monkeypatch):
    """`tct cambiar ... > salida.txt` escribe en cp1252: un emoji en un valor
    viejo reventaba con el archivo ya cambiado."""
    import io
    import sys

    ruta = archivo(tmp_path, SEGUNDA.replace("MT5_SERVER=FxPro-MT5 Demo",
                                             "MT5_SERVER=FxPro " + chr(0x1F525)))
    salida = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", salida)

    assert correr("cambiar", "--env-file", str(ruta), "MT5_SERVER=FxPro-MT5 Live") == 0
    salida.flush()
    assert b"FxPro-MT5 Live" in salida.buffer.getvalue()


def test_el_aviso_del_entorno_dice_como_sacarla(tmp_path, capsys, monkeypatch):
    ruta = archivo(tmp_path)
    monkeypatch.setenv("MAX_OPEN_TRADES", "7")

    assert correr("cambiar", "--env-file", str(ruta), "MAX_OPEN_TRADES=2") == 0

    assert "variables de entorno" in capsys.readouterr().out


def test_sin_nada_que_cambiar_dice_como_se_usa(tmp_path, capsys):
    ruta = archivo(tmp_path)

    assert correr("cambiar", "--env-file", str(ruta)) == 1

    assert "NOMBRE=VALOR" in capsys.readouterr().out
    assert ruta.read_bytes() == SEGUNDA.encode("utf-8")


def test_un_rechazo_dice_que_no_se_cambio_nada(tmp_path, capsys):
    ruta = archivo(tmp_path)

    assert correr("cambiar", "--env-file", str(ruta), "MAX_OPEN_TRADE=2") == 1

    assert "No se cambio nada" in capsys.readouterr().out


def contestar(monkeypatch, *respuestas):
    pendientes = list(respuestas)
    monkeypatch.setattr("tct.archivo_env.hay_teclado", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": pendientes.pop(0))


def test_sin_teclado_no_pide_la_password_y_lo_dice(tmp_path, monkeypatch, capsys):
    """Sin consola (con la entrada por un pipe, o sin ventana), getpass no
    falla: se queda esperando para siempre y hay que matar el proceso."""
    ruta = archivo(tmp_path)
    monkeypatch.setattr("tct.archivo_env.hay_teclado", lambda: False)
    monkeypatch.setattr("getpass.getpass", lambda _p="": pytest.fail("pregunto sin teclado"))

    assert correr("cambiar", "--env-file", str(ruta), "MT5_PASSWORD") == 1

    assert "consola.bat" in capsys.readouterr().out
    assert ruta.read_bytes() == SEGUNDA.encode("utf-8")


def test_la_password_se_pide_y_no_sale_en_pantalla(tmp_path, capsys, monkeypatch):
    ruta = archivo(tmp_path)
    contestar(monkeypatch, "Nueva#99", "Nueva#99")

    assert correr("cambiar", "--env-file", str(ruta), "MT5_PASSWORD") == 0

    salida = capsys.readouterr().out
    assert "Nueva#99" not in salida and "Secreta#1" not in salida
    assert "****" in salida
    assert load_settings(ruta).mt5_password == "Nueva#99"


def test_si_la_password_no_coincide_no_se_cambia_nada(tmp_path, capsys, monkeypatch):
    ruta = archivo(tmp_path)
    contestar(monkeypatch, "Nueva#99", "Nueva#98")

    assert correr("cambiar", "--env-file", str(ruta), "MT5_PASSWORD") == 1

    assert "no coincide" in capsys.readouterr().out
    assert ruta.read_bytes() == SEGUNDA.encode("utf-8")


def test_si_el_archivo_esta_bloqueado_lo_dice_sin_error_crudo(tmp_path, capsys, monkeypatch):
    ruta = archivo(tmp_path)

    def bloqueado(*_a, **_k):
        # El PermissionError del reemplazo nombra el TEMPORAL, que la persona
        # nunca vio y que ya no existe cuando lo va a buscar.
        raise PermissionError(13, "bloqueado", f"{ruta}.tmp")

    monkeypatch.setattr("tct.archivo_env.os.replace", bloqueado)

    assert correr("cambiar", "--env-file", str(ruta), "MAX_OPEN_TRADES=2") == 1
    salida = capsys.readouterr().out
    assert "solo lectura" in salida
    assert ".tmp" not in salida
    assert ruta.read_bytes() == SEGUNDA.encode("utf-8")


def test_el_comando_avisa_el_roster_desparejo(tmp_path, capsys, monkeypatch):
    archivo(tmp_path, "INSTANCE_NAME=demo\nINSTANCE_NAMES=demo,fxpro\n", ".env")
    ruta = archivo(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert correr("cambiar", "--env-file", ".env.segunda", "INSTANCE_NAMES=demo,fxpro,real") == 0

    salida = capsys.readouterr().out
    assert ".env dice INSTANCE_NAMES=demo,fxpro" in salida
    assert "tct cambiar --env-file .env INSTANCE_NAMES=demo,fxpro,real" in salida
    assert ruta.exists()


def test_el_archivo_que_ya_no_arrancaba_lo_avisa(tmp_path, capsys):
    ruta = archivo(tmp_path, "TRADING_MODE=LIVE\nALLOW_LIVE_TRADING=true\nMAX_SIGNALS_PER_DAY=5\n",
                   ".env.real")

    assert correr("cambiar", "--env-file", str(ruta), "MAX_SIGNALS_PER_DAY=10") == 0

    assert "todavia no deja arrancar" in capsys.readouterr().out


def test_el_comando_esta_conectado():
    """Se probo la unidad y no el cableado es la causa de dos bugs de §6."""
    assert cli.build_parser().parse_args(["cambiar", "A=1"]).command == "cambiar"
    args = argparse.Namespace(env_file=None, asignaciones=[])
    assert cli.cmd_cambiar(args) == 1
