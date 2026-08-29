# Guía de instalación en Mac

Guía paso a paso, escrita para alguien que no programa. Todo se hace desde la
aplicación **Terminal** de la Mac.

Para abrir Terminal: `Cmd` + `Espacio`, escribí `Terminal`, `Enter`.

> **Nada de esto opera con dinero real.** El sistema arranca en modo papel:
> registra operaciones simuladas en un archivo y no manda nada a ningún lado.
> Operar en una cuenta MT5 **demo** ya viene instalado y listo, pero hay que
> activarlo a mano completando el `.env` (último capítulo de esta guía).

---

## Paso 0 — Descargar el proyecto

**Si te lo pasaron por GitHub:**

```bash
cd ~/Documents
git clone https://github.com/USUARIO/telegram-copy-trading.git
cd telegram-copy-trading
```

**Si te lo pasaron en una carpeta (ZIP):** descomprimila en `Documentos` y
entrá con:

```bash
cd ~/Documents/telegram-copy-trading
```

> Tip: en vez de escribir la ruta, podés escribir `cd ` (con el espacio) y
> arrastrar la carpeta desde el Finder a la ventana de Terminal.

---

## Paso 1 — Instalar

```bash
bash scripts/setup_mac.sh
```

Un solo comando, sin preguntas. Busca Python, crea el entorno, instala **todo**
(incluido lo necesario para operar en MT5 demo más adelante), corre los tests y
muestra un diagnóstico. Tarda unos minutos.

Después de esto **no hay que instalar nada más nunca**. Lo único que queda es
completar el archivo de configuración.

### Si dice que falta Python

macOS trae Python 3.9, que es demasiado viejo. Instalá uno nuevo:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Cuando termine, seguí las instrucciones que imprime en pantalla (te va a pedir
correr dos comandos con `eval "$(/opt/homebrew/bin/brew shellenv)"`), y después:

```bash
brew install python@3.12
bash scripts/setup_mac.sh
```

---

## Paso 2 — Credenciales de Telegram

El bot entra a Telegram **como tu propia cuenta**, no como un robot. Eso es
necesario porque un robot solo puede leer un grupo si un administrador lo
agrega, y en un grupo de señales ajeno eso no va a pasar.

1. Entrá desde el navegador a **https://my.telegram.org**
2. Poné tu número de teléfono (con código de país, ej. `+54911...`).
   Te llega un código **por Telegram**, no por SMS.
3. Entrá a **API development tools**.
4. Completá el formulario:
   - *App title*: `copytrading` (cualquier nombre sirve)
   - *Short name*: `copytrading`
   - El resto se puede dejar vacío.
5. Te va a mostrar dos datos. Copiá los dos:
   - **App api_id** — un número, ej. `1234567`
   - **App api_hash** — un texto largo, ej. `a1b2c3d4e5f6...`

### Ponerlos en el archivo de configuración

```bash
open -e .env
```

Eso abre el archivo en TextEdit. Buscá estas dos líneas y completalas:

```
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=a1b2c3d4e5f6...
```

Guardá con `Cmd` + `S` y cerrá.

> ⚠️ El archivo `.env` tiene tus credenciales. **Nunca** lo subas a GitHub ni
> se lo pases a nadie. Ya está configurado para que git lo ignore.

---

## Paso 3 — Encontrar el grupo de señales

Cada vez que abras una Terminal nueva, primero hay que activar el entorno:

```bash
cd ~/Documents/telegram-copy-trading
source .venv/bin/activate
```

Vas a ver que aparece `(.venv)` al principio de la línea. Ahora:

```bash
python -m tct chats
```

**La primera vez** te va a pedir:

- `Please enter your phone (or bot token):` → tu número con código de país
- `Please enter the code you received:` → el código que llega **por Telegram**
- `Please enter your password:` → solo si tenés verificación en dos pasos

Después te muestra una lista así:

```
              ID  TIPO      TITULO
------------------------------------------------------------
 -1001234567890  canal     Gold Signals VIP
 -1009876543210  grupo     Forex Team
       123456789  privado   Juan
```

**Copiá el ID del grupo de señales** (el número largo, con el signo menos).

Abrí el `.env` de nuevo (`open -e .env`) y pegalo:

```
TELEGRAM_SOURCE_CHATS=-1001234567890
```

Si querés escuchar varios grupos, separalos con coma y sin espacios.

---

## Paso 4 — Verificar

```bash
python -m tct check
```

Tiene que terminar con:

```
  RESULTADO: todo listo para arrancar
```

Si dice que falta algo, el mensaje indica exactamente qué.

---

## Paso 5 — Arrancar

```bash
python -m tct run
```

El bot queda escuchando. Cada vez que llegue una señal al grupo, vas a ver algo
así en pantalla:

```
14:32:07 INFO    tct.engine   Senal aceptada BUY XAUUSD lote=0.01 ticket=900000001
```

Para pararlo: `Ctrl` + `C`.

> **La Mac no puede dormirse mientras el bot corre.** Si la tapa se cierra o la
> pantalla se suspende, el bot deja de recibir mensajes. Para dejarlo corriendo:
> Ajustes del Sistema → Bloqueo de pantalla → poné "Nunca" en apagar pantalla
> cuando está conectado a la corriente. (Si el objetivo es que corra 24/7, lo
> correcto es un servidor, no una Mac de escritorio.)

---

## Ver qué pasó

```bash
python -m tct status
```

Muestra las posiciones abiertas, cuántas señales se aceptaron y cuántas se
rechazaron.

Para ver el detalle de cada cosa, los archivos se pueden abrir con cualquier
editor:

- `data/paper_trades.jsonl` — las operaciones simuladas
- `data/events.jsonl` — **todo**, incluyendo cada rechazo con su motivo

---

## Probar el parser sin arrancar nada

Muy útil al principio: copiá un mensaje real del grupo y fijate qué entiende.

```bash
python -m tct test "XAUUSD BUY
Entry 2345
SL 2335
TP1 2355
TP2 2365"
```

No toca ningún archivo ni manda nada. Solo muestra la interpretación.

---

## Modo observación

Si querés que el bot mire el grupo unos días **sin registrar ni una operación**,
poné en el `.env`:

```
DRY_RUN=true
```

Va a anotar en `data/events.jsonl` cómo interpretó cada mensaje, sin crear
operaciones. Es la forma más segura de comprobar que el parser entiende bien a
ese grupo antes de darle rienda.

---

## Pasar a tu cuenta MT5 demo

Esto **ya está instalado y disponible** desde el primer día. No hace falta
instalar nada ni cambiar el modo: solo completar dos líneas en el `.env`.

El bot arranca en `TRADING_MODE=AUTO`, que revisa el `.env` en cada arranque.
Mientras esas dos líneas estén vacías corre en papel; apenas tengan valor,
manda las órdenes a tu cuenta MT5 demo.

Como `MetaTrader5` no existe para Mac, el puente es **MetaApi**, que corre el
terminal MT5 en su nube y lo expone por internet.

1. Creá una cuenta en **https://app.metaapi.cloud**
2. Generá un **token** y agregá tu cuenta **MT5 demo** (login, contraseña y
   servidor del bróker). MetaApi te devuelve un **Account ID**.
3. Abrí `open -e .env` y completá:
   ```
   METAAPI_TOKEN=el_token
   METAAPI_ACCOUNT_ID=el_account_id
   ```
4. Verificá y arrancá:
   ```bash
   python -m tct check
   python -m tct run
   ```

`check` te va a confirmar el cambio con esta línea:

```
Modo            : AUTO -> PAPER_AND_METAAPI_DEMO
```

Para volver a papel sin borrar las credenciales, poné `TRADING_MODE=PAPER_ONLY`.

El sistema **rechaza cualquier cuenta que no sea demo**, aunque la configures
por error. Esa protección está en el ejecutor de órdenes, no en la
configuración, justamente para que un error de tipeo no alcance para saltearla.

---

## Problemas frecuentes

**`command not found: python`**
Falta activar el entorno. Corré `source .venv/bin/activate` desde la carpeta
del proyecto.

**`Could not find a version that satisfies the requirement MetaTrader5`**
Alguien le sacó el marcador `; sys_platform == "win32"` al `requirements.txt`.
Hay que reponerlo.

**`externally-managed-environment`**
Estás usando el Python del sistema en vez del entorno virtual.
Corré `source .venv/bin/activate` primero.

**`No se pudo resolver el chat`**
El ID en `TELEGRAM_SOURCE_CHATS` está mal, o la cuenta ya no es miembro del
grupo. Volvé a correr `python -m tct chats`.

**El bot no reacciona a los mensajes**
Verificá con `python -m tct status` que el modo no sea `DRY_RUN=true`, y que el
ID del grupo sea el correcto.

**Pide el código de Telegram cada vez que arranca**
Se borró el archivo `telegram_copy_trading.session`. Se vuelve a crear con el
próximo login.
