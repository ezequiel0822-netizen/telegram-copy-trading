# Telegram Copy Trading

Lee señales de trading de un grupo de Telegram, las convierte en operaciones
estructuradas, las registra siempre como *paper trade*, y opcionalmente las
ejecuta en una cuenta **MT5 demo**.

**Windows es la plataforma recomendada**: MetaTrader 5 se conecta de forma
nativa, sin intermediarios. También corre en macOS y Linux, con la salvedad de
más abajo.

```
Telegram  ->  parser  ->  control de riesgo  ->  paper trade  ->  broker (opcional)
                                    |
                                    +--> todo queda en data/events.jsonl
```

---

## Instalación

| | |
|---|---|
| **Windows** (recomendado) | Doble clic en `scripts\instalar.bat`. Guía: **[docs/SETUP_WINDOWS.md](docs/SETUP_WINDOWS.md)** |
| **macOS** | `bash scripts/setup_mac.sh`. Guía: **[docs/SETUP_MAC.md](docs/SETUP_MAC.md)** |

Un solo comando en ambos casos. Después no hay que instalar nada más: lo único
que queda es completar el `.env`.

---

## Por qué Windows: MetaTrader5 no existe para Mac

El paquete `MetaTrader5` de PyPI publica **únicamente wheels `win_amd64`** y no
tiene *source distribution*. En una Mac, `pip install MetaTrader5` no falla al
ejecutarse: **falla al instalarse**, con `Could not find a version that
satisfies the requirement`. Y el terminal MT5 para macOS es un envoltorio de
Wine que la API de Python no alcanza.

Por eso el `requirements.txt` lleva un marcador de plataforma:

```
MetaTrader5>=5.0.45,<6.0.0; sys_platform == "win32"
```

Con eso pip **saltea** el paquete en la Mac en lugar de abortar la instalación
entera. **No borres ese marcador.**

Consecuencia práctica: en la Mac, la lectura de Telegram, el parser y el paper
trading funcionan **100% nativo**, pero la ejecución en MT5 necesita un puente
de pago (MetaApi). En Windows se habla directo con la terminal instalada: menos
latencia, menos piezas que puedan fallar y nada que pagar.

---

## Modos de operación

| `TRADING_MODE` | Qué hace | ¿Corre en Mac? |
|---|---|---|
| **`AUTO`** *(por defecto)* | Decide solo: MT5 demo si hay credenciales de MetaApi en el `.env`, papel si no. | Sí |
| `PAPER_ONLY` | Solo simula, aunque haya credenciales cargadas. | Sí |
| `PAPER_AND_METAAPI_DEMO` | Fuerza la ejecución en MT5 demo vía MetaApi Cloud. | Sí |
| `PAPER_AND_MT5_DEMO` | Ejecuta con el MT5 instalado localmente. **Lo recomendado.** | **No.** Solo Windows |
| `LIVE` | Dinero real. Requiere además `ALLOW_LIVE_TRADING=true`. | Solo Windows |

### MT5 demo está disponible desde el primer arranque

No hay una segunda instalación ni un cambio de modo. El puente a MetaApi se
instala junto con todo lo demás, y `AUTO` mira el `.env` en cada arranque:

```
METAAPI_TOKEN=          ->  corre en papel
METAAPI_ACCOUNT_ID=

METAAPI_TOKEN=abc...    ->  ejecuta en tu cuenta MT5 demo
METAAPI_ACCOUNT_ID=123
```

Completar esas dos líneas y reiniciar es **todo** lo que separa el modo papel
de la cuenta demo. `python -m tct check` dice en qué estado está y qué falta.

Volver atrás es igual de simple: `TRADING_MODE=PAPER_ONLY` fuerza el modo papel
sin borrar las credenciales.

---

## Instalación en la Mac

```bash
git clone https://github.com/ezequiel0822-netizen/telegram-copy-trading.git
cd telegram-copy-trading
bash scripts/setup_mac.sh
```

Un solo comando, sin preguntas. Busca Python 3.10+, crea un entorno virtual en
`.venv`, instala **todo** (incluidos el puente a MT5 demo y el OCR), instala
Tesseract si encuentra Homebrew, prepara el `.env`, corre los tests y termina
con un diagnóstico.

Después de eso no hay que instalar nada más nunca: lo único que queda es
completar el `.env`.

Guía paso a paso, pensada para alguien que no programa: **[docs/SETUP_MAC.md](docs/SETUP_MAC.md)**

### A mano

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # todo, en una sola instalación
cp .env.example .env
```

---

## Comandos

```bash
python -m tct check     # diagnóstico: Python, dependencias, .env, plataforma
python -m tct chats     # lista tus grupos de Telegram con sus IDs
python -m tct test      # prueba el parser con un mensaje, sin tocar nada
python -m tct status    # posiciones abiertas y estadísticas
python -m tct run       # arranca el bot
```

`check` es el primero que hay que correr en una máquina nueva: dice qué falta
antes de que falte.

`test` sirve para pegar un mensaje real del grupo y ver exactamente qué
entendió el parser:

```bash
python -m tct test "GOLD SELL LIMIT 2345-2347
SL: 2355
TP: 2335 / 2325 / 2315"
```

---

## Qué entiende el parser

**Aperturas** — símbolo, dirección, tipo de orden, entrada (o rango) y todos los TPs:

```
XAUUSD BUY              🔴 GOLD SELL LIMIT 2345-2347      **BUY NAS100 NOW**
Entry 2345              SL: 2355                          Entry: 18,500
SL 2335                 TP: 2335 / 2325 / 2315            Stop Loss: 18,400
TP1 2355                                                  Take Profit 1: 18,700
TP2 2365
```

Maneja emojis, markdown, `BUY LIMIT` / `SELL STOP` / `BUY NOW`, alias
(`GOLD`→`XAUUSD`, `NAS`→`NAS100`, `DOW`→`US30`), comas de miles (`18,500`),
coma decimal española (`2345,50`), rangos de entrada y mensajes editados.

**Gestión** — `Close 50% XAUUSD`, `Close half`, `Move SL to BE`, `Cerrar todo`.

**Descarte** — la charla del grupo (`Buenos días`, `Gracias maestro`) se ignora
sin generar nada.

**Stickers y otros adjuntos** — los grupos de señales mandan stickers todo el
tiempo (festejos de TP, reacciones). Se descartan explícitamente, junto con
GIFs, audios, encuestas, contactos y ubicaciones.

Esto importa más de lo que parece: en Telegram **un sticker es una imagen**
(un `Document` con atributo de sticker). Mientras el OCR esté apagado da igual,
pero apenas se encienda, pasar un sticker por Tesseract produce texto basura
—`TP`, `BUY`, números sueltos del dibujo— que el parser podría llegar a leer
como una señal real. Por eso se filtran **antes** de la rama de OCR, no después.
Si un sticker viene con texto, el texto igual se lee: no se pierde una señal.

Como contrapartida, sí se reconocen las capturas mandadas **como archivo** (sin
comprimir), que llegan como `document` con mime `image/*` y no como `photo`.

---

## IA local para los mensajes raros (opcional)

El parser de reglas es rápido, gratis y predecible, pero un grupo real a veces
escribe así:

> *"muchachos entramos largos en el oro ahora tipo 2345, cuidamos abajo de 2335
> y buscamos 2355"*

Eso no lo agarra ninguna regla. Ahí entra **[Ollama](https://ollama.com)**, que
corre en la propia PC: gratis, sin mandar nada a internet y sin cuenta en
ningún lado. Se activa con `ENABLE_OLLAMA=true`.

Probado contra un modelo real, ese mensaje se convierte en
`XAUUSD BUY, entrada 2345, SL 2335, TP 2355`.

**La IA no opera.** Cuando entiende algo que el parser no pudo, avisa por
Telegram y ahí termina. El motivo es concreto: las validaciones de riesgo
verifican que un precio sea *coherente*, no que sea el *correcto*. Si el modelo
lee 2345 donde decía 2355, esa señal pasa todos los controles y opera con un
número inventado. Perderse una señal es barato; operar una equivocada, no.

Hay una segunda red: **todo número que devuelve la IA se busca en el mensaje
original**, y si no aparece literalmente se descarta la interpretación entera.
Un modelo puede inventar un precio verosímil, pero no puede hacer que aparezca
en un texto que ya está escrito.

Solo se la consulta cuando el parser falla, así que en un grupo con formato
consistente casi nunca se activa.

---

## Capas de seguridad

Todas viven en [`src/tct/risk.py`](src/tct/risk.py) y son configurables desde
el `.env`, tal como pide el CONTEXTO MAESTRO:

- **Lista blanca** de símbolos (`ALLOWED_SYMBOLS`).
- **Techo de lote** (`MAX_LOT`): si `DEFAULT_LOT` lo supera, el bot no arranca.
- **SL y TP obligatorios** (`REQUIRE_STOP_LOSS`, `REQUIRE_TAKE_PROFIT`).
- **Coherencia geométrica**: rechaza un BUY con el SL por encima de la entrada.
  Eso no es una señal conservadora, es una señal rota.
- **Tope de posiciones abiertas** y **una sola posición por símbolo**.
- **Cupo diario** de señales (`MAX_SIGNALS_PER_DAY`).
- **Solo cuentas demo**: la barrera real está en el ejecutor, no en la config.
  `ALLOW_LIVE_TRADING=false` hace que se rechace cualquier cuenta que el broker
  no reporte como demo.
- **Dos llaves para dinero real**: `TRADING_MODE=LIVE` **y** `ALLOW_LIVE_TRADING=true`.

Un mensaje ambiguo se registra como evento y **no ejecuta nada**.
Un paper trade se escribe **siempre**, aunque el broker esté apagado o falle.

---

## Archivos que genera

| Archivo | Contenido |
|---|---|
| `data/events.jsonl` | Todo lo que pasó: aceptadas, **rechazadas con su motivo**, ambiguas, errores |
| `data/paper_trades.jsonl` | Operaciones simuladas: aperturas, cierres, parciales, movimientos de SL |
| `data/state.json` | Posiciones abiertas y mensajes ya procesados (sobrevive a reinicios) |
| `logs/tct.log` | Log de ejecución |

Que se registren también los rechazos es lo que después permite contestar
*"¿por qué el bot no tomó esta señal?"*.

---

## Estructura

```
src/tct/
├── config.py           configuración y validación del .env
├── engine.py           orquestador: parser -> riesgo -> paper -> broker
├── risk.py             todas las capas de seguridad
├── store.py            persistencia JSONL + estado
├── cli.py              comandos
├── signals/
│   ├── models.py       SignalEvent, EventType, OrderType
│   ├── parser.py       mensaje -> señal estructurada
│   └── ocr.py          hook de OCR (apagado por defecto)
├── brokers/
│   ├── base.py         interfaz común + selector
│   ├── paper.py        simulado (default, multiplataforma)
│   ├── metaapi.py      MT5 demo desde macOS
│   ├── mt5_native.py   MT5 local (solo Windows)
│   └── symbol_map.py   traducción de símbolos por bróker
└── telegram/
    ├── reader.py       lectura del grupo con Telethon
    └── notifier.py     avisos por Bot API
```

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

112 tests, sin red y sin credenciales. Cubren el parser (39 casos con mensajes
reales), el ciclo completo del motor con el broker de papel, las capas de
riesgo, la resolución del modo `AUTO`, la configuración, la persistencia y la
clasificación de adjuntos (stickers, fotos, archivos).

---

## Qué se reutilizó de `tradingalertaIA`

- La técnica del marcador `sys_platform` en `requirements.txt` — es exactamente
  el fix del problema de instalación en Mac.
- La arquitectura *soft-fail* (todo degrada en vez de reventar cuando falta un
  SDK opcional), que resulta ideal para una máquina sin MT5.
- De `app/brokers/mt5_demo_trader.py`: la negociación de *filling mode* (la
  causa clásica del retcode 10030), la normalización de volumen al paso del
  bróker, y la validación de cuenta demo. Portado a `brokers/mt5_native.py`.
- De `app/brokers/mt5_symbol_map.py`: el enfoque de perfiles por bróker.
- De `app/alerts/telegram_notifier.py`: el partido de mensajes en 4096 chars.

Lo que **no** estaba ahí y hubo que construir: la lectura de un grupo ajeno con
Telethon (tu repo solo usa la Bot API para su propio bot), el parser de señales
de terceros y toda la capa de eventos de gestión.

---

## Estado y límites

**Probado:** parser, motor, riesgo, persistencia, configuración, CLI, filtrado
de adjuntos y el broker de papel — 103 tests verdes, y la instalación completa verificada en un
entorno virtual limpio.

**Sin probar contra un servicio real:** `brokers/metaapi.py` (necesita un token
y una cuenta MT5 demo conectada) y `telegram/reader.py` (necesita credenciales
de Telegram). Ambos están escritos contra la API documentada y verificados a
nivel de firma, pero el primer contacto real puede necesitar ajustes.

**Pendiente:** OCR está preparado pero apagado (`ENABLE_OCR=false`); conviene
encenderlo recién después de medir cuántas señales del grupo son solo imagen.
