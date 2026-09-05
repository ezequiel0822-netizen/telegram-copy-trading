"""Que un corte de internet no apague el bot en silencio.

Este bot esta pensado para quedarse dias escuchando en una PC dedicada que
nadie mira. Ahi un corte de conexion de madrugada es normal, y las dos formas
de fallar son igual de malas:

  - Rendirse a los seis segundos y apagarse.
  - Apagarse registrandolo como "Cerrado limpio", que es mentira.

La segunda es peor: te enteras dias despues, cuando vas a mirar los datos y
no hay.
"""

from __future__ import annotations

import inspect

from tct.telegram import reader as reader_mod


def test_los_reintentos_de_conexion_son_infinitos():
    """Telethon por defecto reintenta 5 veces con 1 segundo de espera: seis
    segundos de internet caido alcanzan para que el bot se apague."""
    fuente = inspect.getsource(reader_mod.TelegramReader.start)

    assert "connection_retries=-1" in fuente, (
        "con el default de Telethon el bot se rinde a los pocos segundos"
    )
    assert "auto_reconnect=True" in fuente


def test_un_corte_no_se_registra_como_cierre_limpio():
    """`run_forever` volviendo por su cuenta NO es un cierre pedido: Ctrl+C
    sale por KeyboardInterrupt. Registrarlo como limpio esconde el problema."""
    from tct import cli

    fuente = inspect.getsource(cli._run_async)

    assert "corte_inesperado" in fuente, "no distingue el corte del cierre pedido"
    assert "SE CORTO LA CONEXION" in fuente
    assert fuente.index("corte_inesperado = True") < fuente.index('logger.info("Cerrado limpio.")'), (
        "la marca de corte tiene que ponerse antes del finally"
    )


def test_el_corte_se_avisa_por_telegram():
    """Es el unico canal que llega al telefono. La notificacion va por la Bot
    API (HTTPS), que es un camino distinto del de Telethon: puede funcionar
    aunque el otro se haya caido."""
    from tct import cli

    fuente = inspect.getsource(cli._run_async)

    assert "SE DETUVO SOLO" in fuente


def test_el_aviso_dice_que_pasa_con_las_posiciones_abiertas():
    """Es la primera pregunta de cualquiera que lee 'se detuvo': si el bot no
    esta, quien cuida lo que quedo abierto. La respuesta es que el SL y el TP
    viven en MetaTrader, no en el bot."""
    from tct import cli

    fuente = inspect.getsource(cli._run_async)

    assert "siguen en MetaTrader" in fuente or "sigue en MetaTrader" in fuente


def test_avisar_del_corte_no_puede_tapar_el_cierre_ordenado():
    """Si el aviso falla (que es probable: se acaba de cortar la conexion), el
    bot igual tiene que guardar el estado y desconectar el broker."""
    from tct import cli

    fuente = inspect.getsource(cli._run_async)

    aviso = fuente.index("SE DETUVO SOLO")
    finally_ = fuente.index("finally:", aviso)
    assert "except Exception" in fuente[aviso:finally_], (
        "el aviso no esta protegido: si falla, se salta el guardado del estado"
    )


# --------------------------------------------------------------------------
# Arranque automatico: esperar a que MetaTrader este listo
#
# Al iniciar sesion, MetaTrader y el bot arrancan casi al mismo tiempo, pero
# MetaTrader tarda en levantar la interfaz, conectarse y loguear la cuenta. El
# bot gana esa carrera casi siempre, y como sin broker no arranca, el arranque
# automatico fallaba en silencio en casi todos los encendidos.
# --------------------------------------------------------------------------


class BrokerLento:
    """Conecta recien despues de N intentos, como MetaTrader al arrancar."""

    name = "mt5"

    def __init__(self, intentos_hasta_listo: int) -> None:
        self.faltan = intentos_hasta_listo
        self.intentos = 0

    async def connect(self) -> bool:
        self.intentos += 1
        self.faltan -= 1
        return self.faltan < 0


def test_sin_espera_se_rinde_al_primer_intento(monkeypatch):
    """El comportamiento de siempre no cambia: 0 es un solo intento."""
    import asyncio

    from tct.cli import _conectar_broker

    broker = BrokerLento(intentos_hasta_listo=3)
    assert asyncio.run(_conectar_broker(broker, 0)) is False
    assert broker.intentos == 1


def test_con_espera_reintenta_hasta_que_metatrader_aparece(monkeypatch):
    import asyncio

    from tct import cli

    # Se acorta el sleep: lo que se prueba es el bucle, no el reloj.
    dormidas = []

    async def sin_esperar(segundos):
        dormidas.append(segundos)

    monkeypatch.setattr(cli.asyncio, "sleep", sin_esperar)

    broker = BrokerLento(intentos_hasta_listo=3)
    assert asyncio.run(cli._conectar_broker(broker, 300)) is True
    assert broker.intentos == 4, "no reintento hasta que el broker estuvo listo"
    assert dormidas, "no espero entre intentos"


def test_si_nunca_aparece_se_rinde_y_no_queda_colgado(monkeypatch):
    """Rendirse tiene que seguir siendo posible: un bucle infinito dejaria el
    bot 'arrancando' para siempre sin operar ni avisar."""
    import asyncio

    from tct import cli

    reloj = {"t": 0.0}

    async def avanzar(segundos):
        reloj["t"] += segundos

    class LoopFalso:
        def time(self):
            return reloj["t"]

    monkeypatch.setattr(cli.asyncio, "sleep", avanzar)
    monkeypatch.setattr(cli.asyncio, "get_running_loop", lambda: LoopFalso())

    broker = BrokerLento(intentos_hasta_listo=10_000)
    assert asyncio.run(cli._conectar_broker(broker, 60)) is False
    assert reloj["t"] >= 60


def test_run_le_pasa_la_espera_al_broker():
    """El cableado: que el flag llegue de verdad hasta la conexion."""
    import inspect

    from tct import cli

    assert "esperar_mt5" in inspect.getsource(cli.cmd_run)
    assert "_conectar_broker(broker, esperar_segundos)" in inspect.getsource(cli._run_async)
