# Guía de instalación en Windows

Guía paso a paso, escrita para alguien que no programa.

Windows es la plataforma **recomendada** para este sistema: MetaTrader 5 se
conecta de forma nativa, sin intermediarios ni servicios de terceros. En una
Mac eso no es posible.

> **El sistema arranca sin operar con dinero real.** La protección de "solo
> cuentas demo" está en el ejecutor de órdenes, no en la configuración: aunque
> pongas por error los datos de una cuenta real, el bot se niega a arrancar.

---

## Lo que vas a necesitar

| | |
|---|---|
| **La PC** | Windows 10 u 11 de 64 bits. Idealmente dedicada, encendida todo el día. |
| **RAM** | 8 GB alcanza. 16 GB si querés usar la IA local. |
| **MetaTrader 5** | Instalado, con una cuenta **demo** de tu bróker. |
| **Telegram** | Tu cuenta, ya miembro del grupo de señales. |

---

## Paso 1 — Instalar Python

El sistema necesita Python 3.10 o superior. Windows no lo trae.

1. Entrá a **https://www.python.org/downloads/windows/**
2. Descargá el **"Windows installer (64-bit)"** de **Python 3.13**.
3. Abrí el archivo descargado.

> ### ⚠️ El paso que hace tropezar a todo el mundo
>
> En la primera pantalla del instalador, abajo de todo, hay una casilla que
> dice **"Add python.exe to PATH"**.
>
> **Tildala antes de darle a "Install Now".**
>
> Si no la tildás, Windows no va a encontrar Python y el instalador del bot te
> va a decir que falta, aunque lo hayas instalado. Es el error más común y el
> más confuso, porque uno jura que lo instaló bien.

4. Dale a **Install Now** y esperá a que termine.

---

## Paso 2 — Descargar el proyecto

**Opción A — con Git** (si lo tenés instalado), en una carpeta a elección:

```
git clone https://github.com/ezequiel0822-netizen/telegram-copy-trading.git
```

**Opción B — sin Git, más simple:**

1. Entrá a **https://github.com/ezequiel0822-netizen/telegram-copy-trading**
2. Botón verde **"Code"** → **"Download ZIP"**.
3. Descomprimí el ZIP donde quieras, por ejemplo en `C:\bot`.

---

## Paso 3 — Instalar

Entrá a la carpeta del proyecto, después a la carpeta **`scripts`**, y hacé
**doble clic en `instalar.bat`**.

Eso es todo. No hace falta abrir ninguna terminal.

El instalador:

- Busca Python y crea un entorno aislado.
- Instala todo lo necesario, incluido MetaTrader 5.
- Detecta si ya tenés MetaTrader y Ollama instalados.
- Corre los tests para verificar que quedó bien.
- Crea un acceso directo **"Bot de Trading"** en el escritorio.
- Te pregunta si querés que arranque solo al prender la PC.

> **¿Por qué un `.bat` y no el `.ps1` directamente?** Windows bloquea por
> defecto los scripts de PowerShell descargados de internet, y el error que
> muestra no explica nada. El `.bat` lo ejecuta salteando esa restricción solo
> para esa vez, sin cambiar ninguna configuración de tu Windows.

### Te va a preguntar por la IA local

Si no tenés Ollama, te ofrece instalarlo. Si ya tenés algún modelo descargado,
**lo reutiliza** en vez de bajar otro. Podés decir que no y hacerlo después
con `scripts\instalar_ia.bat`: el bot funciona igual sin eso.

---

## Paso 4 — La cuenta demo de MetaTrader 5

1. Abrí **MetaTrader 5**.
2. Si no tenés cuenta demo: **Archivo → Abrir una cuenta**, elegí tu bróker
   (FxPro, por ejemplo) y creá una **cuenta de demostración**.
3. Anotá los tres datos que te da: **login** (un número), **contraseña** y
   **servidor** (algo como `FxPro-MT5`).

### ⚠️ Activá el botón "Algo Trading"

En la barra de arriba de MetaTrader hay un botón que dice **"Algo Trading"**
(o "AutoTrading"). **Tiene que estar verde.** Si está en rojo o gris, MT5
rechaza toda orden automática.

Si te olvidás, el bot te lo va a avisar al arrancar con un mensaje claro en
vez de fallar recién cuando llegue la primera señal.

> **Dejá MetaTrader abierto.** El bot le habla a la terminal que está
> corriendo; si la cerrás, se queda sin conexión.

---

## Paso 5 — Credenciales de Telegram

El bot entra a Telegram **como tu propia cuenta**, no como un robot. Es
necesario: un robot solo puede leer un grupo si un administrador lo agrega, y
en un grupo de señales ajeno eso no va a pasar.

1. Entrá desde el navegador a **https://my.telegram.org**
2. Poné tu número con código de país (ej. `+5215512345678`). El código de
   acceso llega **por Telegram**, no por SMS.
3. Entrá a **API development tools**.
4. Completá el formulario. En *App title* y *Short name* poné `copytrading`;
   en **Platform** elegí **Desktop**; el resto se puede dejar vacío.
5. Copiá los dos datos: **App api_id** (un número) y **App api_hash** (un
   texto largo).

---

## Paso 6 — Completar la configuración

En la carpeta del proyecto hay un archivo llamado **`.env`**. Abrilo con el
**Bloc de notas** (clic derecho → Abrir con → Bloc de notas).

Completá estas líneas:

```
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=a1b2c3d4e5f6...

MT5_LOGIN=12345678
MT5_PASSWORD=tu_password_demo
MT5_SERVER=FxPro-MT5
```

Guardá con `Ctrl` + `S` y cerrá.

> ⚠️ El archivo `.env` tiene tus credenciales. **Nunca** lo subas a GitHub ni
> se lo pases a nadie, ni por captura de pantalla. Ya está configurado para
> que git lo ignore.

### No hace falta tocar `TRADING_MODE`

Viene en `AUTO`, que revisa el `.env` en cada arranque. Apenas encuentre los
datos de MT5, empieza a operar en tu cuenta demo. Mientras estén vacíos, corre
solo en papel.

---

## Paso 7 — Elegir el grupo de señales

Abrí una terminal en la carpeta del proyecto. La forma fácil: entrá a la
carpeta en el Explorador, escribí `cmd` en la barra de direcciones de arriba y
apretá Enter.

Activá el entorno:

```
.venv\Scripts\activate
```

Vas a ver que aparece `(.venv)` al principio de la línea. Ahora:

```
python -m tct chats
```

**La primera vez** te pide el teléfono (con código de país, sin espacios),
después un código que llega **por Telegram**, y la contraseña solo si tenés
verificación en dos pasos. Eso pasa una única vez.

Después te muestra una lista así:

```
              ID  TIPO      TITULO
------------------------------------------------
 -1001234567890  canal     Gold Signals VIP
 -1009876543210  grupo     Forex Team
       123456789  privado   Juan
```

Copiá el **ID del grupo de señales** (el número largo, con el signo menos
adelante) y pegalo en el `.env`:

```
TELEGRAM_SOURCE_CHATS=-1001234567890
```

Si querés escuchar varios grupos, separalos con coma y sin espacios.

---

## Paso 8 — Verificar

Doble clic en **`scripts\diagnostico.bat`**, o desde la terminal:

```
python -m tct check
```

Tiene que terminar con:

```
  RESULTADO: todo listo para arrancar
```

Y en la sección **Ejecución** vas a ver a dónde van a ir las órdenes:

```
Modo            : AUTO -> PAPER_AND_MT5_DEMO
```

Si dice `AUTO -> PAPER_ONLY`, faltan los datos de MT5 en el `.env`.

---

## Paso 9 — Arrancar

Doble clic en **"Bot de Trading"** del escritorio. O desde la terminal:

```
python -m tct run
```

Cuando llegue una señal al grupo vas a ver algo así:

```
14:32:07 INFO  tct.engine  Senal aceptada BUY XAUUSD lote=0.01 ticket=1234567
```

Para pararlo: `Ctrl` + `C`, o cerrá la ventana.

---

## La IA local, en criollo

El bot lee las señales con un **parser de reglas**: rápido, gratis y
predecible. Entiende los formatos habituales (`XAUUSD BUY / Entry 2345 / SL
2335 / TP 2355`), con emojis, negritas y variantes.

Pero un grupo real a veces escribe así:

> *"muchachos entramos largos en el oro ahora tipo 2345, cuidamos abajo de
> 2335 y buscamos 2355"*

Eso no lo agarra ninguna regla. Ahí entra **Ollama**, una IA que corre en tu
propia PC: es gratis, no manda nada a internet y no necesita cuenta en ningún
lado. Lee el mensaje y extrae los datos.

**Importante: la IA no opera.** Cuando entiende algo que el parser no pudo, te
lo avisa por Telegram y ahí termina. Vos decidís.

La razón es concreta. Las validaciones de riesgo verifican que un precio sea
**coherente**, no que sea el **correcto**. Si el modelo lee 2345 donde decía
2355, esa señal pasa todos los controles y opera con un número inventado.
Perderse una señal es barato; operar una equivocada, no.

Hay además una segunda red: **todo número que la IA devuelve se busca en el
mensaje original**. Si no aparece literalmente, se descarta la interpretación
entera. Un modelo puede inventar un precio verosímil, pero no puede hacer que
aparezca en un texto que ya está escrito.

Tarda entre 20 y 40 segundos por mensaje, solo en los que el parser no
entendió. Los eventos quedan registrados como `ia_sugerencia` en
`data\events.jsonl`, para que puedas revisar cuánto le acierta.

Si después de unas semanas ves que acierta siempre, podés dejarla operar sola
cambiando `OLLAMA_AUTO_EXECUTE=true` en el `.env`. No lo hagas antes.

---

## Ver qué pasó

```
python -m tct status
```

Y los archivos, que se abren con cualquier editor:

- `data\paper_trades.jsonl` — las operaciones registradas.
- `data\events.jsonl` — **todo**, incluyendo cada rechazo con su motivo y cada
  sugerencia de la IA.

---

## Probar el parser sin arrancar nada

Muy útil al principio: copiá un mensaje real del grupo y fijate qué entiende.

```
python -m tct test "XAUUSD BUY
Entry 2345
SL 2335
TP1 2355"
```

No toca ningún archivo ni manda nada.

---

## Modo observación

Si querés que mire el grupo unos días **sin registrar ni una operación**, poné
en el `.env`:

```
DRY_RUN=true
```

Va a anotar en `data\events.jsonl` cómo interpretó cada mensaje, sin crear
nada. Es la forma más segura de comprobar que entiende bien a *ese* grupo
antes de darle rienda.

---

## Que arranque solo al prender la PC

El instalador te lo ofrece. Para cambiarlo después:

- **Activar**: apretá `Win` + `R`, escribí `shell:startup`, Enter. Copiá ahí
  el acceso directo "Bot de Trading" del escritorio.
- **Desactivar**: borrá ese acceso directo de esa carpeta.

Acordate de que MetaTrader 5 también tiene que arrancar y loguearse solo. En
MT5: **Herramientas → Opciones → Servidor**, y tildá guardar la contraseña.

---

## Problemas frecuentes

**El instalador dice que falta Python, pero lo instalé**
No tildaste **"Add python.exe to PATH"** durante la instalación. Volvé a
correr el instalador de Python, elegí **Modify**, y asegurate de que la opción
esté activada. O reinstalá tildando la casilla.

**`No module named tct`**
Quedó de una instalación a medias. Corré de nuevo `scripts\instalar.bat`.

**Las órdenes no entran, o el log dice retcode 10027**
El botón **"Algo Trading"** de MetaTrader está apagado. Apretalo (tiene que
quedar verde) o presioná `Ctrl` + `E`.

**`mt5.initialize() fallo` / `Terminal: Authorization failed`**
MetaTrader 5 no está abierto, o no está logueado en la cuenta. Abrilo,
logueate en la demo, y volvé a arrancar el bot.

**El diagnóstico dice `AUTO -> PAPER_ONLY` y yo quiero operar en demo**
Faltan `MT5_LOGIN`, `MT5_PASSWORD` o `MT5_SERVER` en el `.env`. Los tres.

**El bróker rechaza el símbolo**
El bot le pregunta a MT5 cómo se llaman los instrumentos, así que esto es
raro. Si pasa, abrí MetaTrader, buscá el símbolo en **Observación de mercado**
(`Ctrl` + `M`) y agregalo con clic derecho → Mostrar todo.

**No aparece el código de Telegram**
Llega **dentro de la app de Telegram**, no por SMS. Mirá los mensajes de la
cuenta oficial de Telegram.

**La IA no responde / va lentísima**
Comprobá que Ollama esté corriendo (debería aparecer en la bandeja del
sistema). Un modelo de 7B sin placa de video tarda entre 20 y 40 segundos, y
es normal. Si va peor, cambiá a uno más chico en el `.env`:
`OLLAMA_MODEL=llama3.2:3b`
