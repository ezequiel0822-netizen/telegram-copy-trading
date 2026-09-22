"""La clave de arranque: que el bot no opere una cuenta sin que alguien lo decida.

POR QUE EXISTE
--------------
El usuario lo pidio asi: "cada que quiera iniciar el bot real, quiero que me
pida contrasena antes de iniciarlo, tambien en la demo de fxpro". Un doble clic
en el `.bat` equivocado alcanzaba para poner a operar la cuenta real.

QUE PROTEGE Y QUE NO
--------------------
Protege contra arrancar por error, o contra alguien que se sienta en la PC y no
sabe la clave. NO es una caja fuerte: quien puede editar el `.env` puede borrar
la linea de la clave. Lo que si garantiza es que la clave no se puede LEER del
archivo: se guarda solo una huella (PBKDF2 con sal), nunca el texto.

COMO SE USA
-----------
    tct clave --env-file .env.real      pide la clave dos veces y la guarda

Desde ahi, `tct run` con ese `.env` la pide antes de conectar nada. Con dinero
real es obligatoria: sin clave puesta, el bot real no arranca.

El formato usa ':' y no '$' a proposito: python-dotenv expande variables con '$'
y una huella con '$' adentro llegaba cambiada.
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import re
import secrets
import sys
from collections.abc import Callable
from pathlib import Path

ALGORITMO = "pbkdf2_sha256"
ITERACIONES = 200_000
INTENTOS = 3
LARGO_MINIMO = 4
VARIABLE = "CLAVE_DE_ARRANQUE"

_FORMATO = re.compile(rf"^{ALGORITMO}:(\d+):([0-9a-f]{{32}}):([0-9a-f]{{64}})$")


def hashear(clave: str, sal: bytes | None = None, iteraciones: int = ITERACIONES) -> str:
    """La huella que se guarda en el .env. Nunca se guarda la clave."""
    sal = sal if sal is not None else secrets.token_bytes(16)
    huella = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, iteraciones)
    return f"{ALGORITMO}:{iteraciones}:{sal.hex()}:{huella.hex()}"


def es_valida(guardada: str) -> bool:
    """Si lo que hay en el .env tiene la forma de una huella de `tct clave`."""
    return bool(_FORMATO.match(guardada or ""))


def coincide(clave: str, guardada: str) -> bool:
    """Si la clave escrita corresponde a la huella guardada.

    La comparacion es de tiempo constante (`hmac.compare_digest`): no deja
    adivinar la huella midiendo cuanto tarda en decir que no.
    """
    encontrado = _FORMATO.match(guardada or "")
    if not encontrado:
        return False
    iteraciones = int(encontrado.group(1))
    sal = bytes.fromhex(encontrado.group(2))
    return hmac.compare_digest(hashear(clave, sal, iteraciones), guardada)


def pedir_y_verificar(
    guardada: str,
    instancia: str,
    *,
    entrada: Callable[[str], str] | None = None,
    es_interactivo: Callable[[], bool] | None = None,
    salida: Callable[[str], None] = print,
) -> bool:
    """Pide la clave hasta INTENTOS veces. True si la escribio bien.

    Sin una consola donde escribir -el bot corriendo como servicio, o con la
    entrada redirigida- no se puede preguntar, y NO se arranca: arrancar sin
    preguntar seria justo lo que la clave existe para impedir.
    """
    # Se resuelven al llamar, no al importar: si no, reemplazarlos en una
    # prueba no tendria efecto y la prueba pasaria por el motivo equivocado.
    entrada = entrada or getpass.getpass
    interactivo = es_interactivo() if es_interactivo else sys.stdin.isatty()
    if not interactivo:
        salida(f"[{instancia}] Este bot pide clave para arrancar, y no hay una "
               "ventana donde escribirla. No se arranca.")
        return False

    for intento in range(1, INTENTOS + 1):
        try:
            escrita = entrada(f"Clave de arranque [{instancia}]: ")
        except (EOFError, KeyboardInterrupt):
            salida("\nNo se escribio la clave. No se arranca.")
            return False
        if coincide(escrita, guardada):
            return True
        quedan = INTENTOS - intento
        if quedan:
            salida(f"Clave incorrecta. Te quedan {quedan} intento(s).")
    salida("Clave incorrecta tres veces. El bot NO arranca.")
    return False


def escribir_en_env(ruta: Path, huella: str) -> None:
    """Pone la huella en el .env: reemplaza la linea si existe, o la agrega.

    Toca SOLO esa linea. El resto del archivo -credenciales, comentarios, el
    orden, los fines de linea de Windows- queda exactamente como estaba. El
    como (cortar donde python-dotenv corta, respetar la marca BOM, escribir
    atomico) esta en `archivo_env`, el mismo que usa `tct cambiar`, y tambien
    su ultima red: antes de reemplazar, el archivo nuevo se lee como lo lee el
    bot, y si la clave no quedo o se movio otra variable, lanza
    CambioRechazado sin tocar nada. Sin eso, "Listo" podia dejar vigente la
    huella VIEJA.
    """
    from tct.archivo_env import escribir_atomico, leer_archivo, poner_linea, verificar_lectura

    if not es_valida(huella):
        raise ValueError("no es una huella de tct clave")
    ruta = Path(ruta)
    crudo = ruta.read_bytes().decode("utf-8") if ruta.exists() else ""
    antes = leer_archivo(ruta) if ruta.exists() else {}
    nuevo = poner_linea(
        crudo, VARIABLE, f"{VARIABLE}={huella}",
        comentario="# Clave de arranque (la pone 'tct clave'; no es la clave, es su huella)",
    )
    consejo = (f"El archivo tiene alguna linea rara. Abrilo con  notepad {ruta}, borra\n"
               f"    las lineas de {VARIABLE} y volve a correr tct clave.")
    escribir_atomico(ruta, nuevo, antes_de_reemplazar=lambda temporal: verificar_lectura(
        antes, temporal, {VARIABLE: huella}, consejo))
