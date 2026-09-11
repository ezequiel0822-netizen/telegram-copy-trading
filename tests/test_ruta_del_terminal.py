"""`tct mt5` tiene que decir tambien la ruta de la terminal.

POR QUE
-------
Con UNA cuenta, MT5_PATH vacio es lo mejor: el bot se engancha a la terminal
que este abierta y no hay que acertarle a ninguna ruta.

Con DOS cuentas a la vez deja de ser opcional. "Engancharse a la que
encuentre" no tiene una respuesta correcta con dos MetaTrader abiertos: los
dos bots pueden ir a la misma cuenta, o cada uno a la del otro, y nadie se
entera hasta ver las operaciones en la cuenta equivocada.

Y es el dato mas dificil de conseguir a mano: hay que encontrar el acceso
directo del broker y mirar sus propiedades. La terminal lo sabe, asi que se lo
preguntamos en vez de mandar a la persona a buscarlo.
"""

from __future__ import annotations

from tct.cli import _ruta_del_terminal


class TerminalFalsa:
    def __init__(self, path):
        self.path = path


def test_devuelve_el_ejecutable_y_no_la_carpeta(tmp_path):
    """`terminal_info().path` da la CARPETA; MT5_PATH quiere el .exe."""
    (tmp_path / "terminal64.exe").write_text("", encoding="utf-8")

    ruta = _ruta_del_terminal(TerminalFalsa(str(tmp_path)))

    assert ruta == str(tmp_path / "terminal64.exe")


def test_sin_el_ejecutable_no_inventa_una_ruta(tmp_path):
    """Una ruta mal escrita en el .env falla con un error de IPC que no explica
    nada. Es mejor no poner la linea que ponerla mal."""
    assert _ruta_del_terminal(TerminalFalsa(str(tmp_path))) is None


def test_sin_terminal_no_rompe():
    """`terminal_info()` puede devolver None."""
    assert _ruta_del_terminal(None) is None


def test_una_terminal_sin_path_no_rompe():
    """Y puede devolver algo sin el atributo, segun la version del paquete."""
    assert _ruta_del_terminal(object()) is None
    assert _ruta_del_terminal(TerminalFalsa("")) is None
