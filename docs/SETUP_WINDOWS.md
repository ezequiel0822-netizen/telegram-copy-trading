# Guía de instalación en Windows

Guía paso a paso, escrita para alguien que no programa. Cada paso dice
exactamente dónde hacer clic y qué esperar.

Windows es la plataforma **recomendada**: MetaTrader 5 se conecta de forma
nativa, sin intermediarios ni servicios de pago. En una Mac eso no es posible.

> **El sistema no opera con dinero real.** La protección de "solo cuentas demo"
> está dentro del ejecutor de órdenes, no en un archivo de configuración:
> aunque pongas por error los datos de una cuenta real, el bot se niega a
> arrancar y te lo dice.

---

## Índice

1. [Antes de empezar](#antes-de-empezar)
2. [Paso 1 — Instalar Python](#paso-1--instalar-python)
3. [Paso 2 — Descargar el proyecto](#paso-2--descargar-el-proyecto)
4. [Paso 3 — Instalar el bot](#paso-3--instalar-el-bot)
5. [Paso 4 — Instalar MetaTrader 5 de FxPro](#paso-4--instalar-metatrader-5-de-fxpro)
6. [Paso 5 — Crear la cuenta demo](#paso-5--crear-la-cuenta-demo)
7. [Paso 6 — Activar Algo Trading](#paso-6--activar-algo-trading)
8. [Paso 7 — Credenciales de Telegram](#paso-7--credenciales-de-telegram)
9. [Paso 8 — Completar el archivo .env](#paso-8--completar-el-archivo-env)
10. [Paso 9 — Elegir el grupo de señales](#paso-9--elegir-el-grupo-de-señales)
11. [Paso 10 — Verificar](#paso-10--verificar)
12. [Paso 11 — Arrancar](#paso-11--arrancar)
13. [La IA local](#la-ia-local-en-criollo)
14. [Uso diario](#uso-diario)
15. [Problemas frecuentes](#problemas-frecuentes)

---

## Antes de empezar

### Lo que hace falta

| | |
|---|---|
| **La PC** | Windows 10 u 11 de 64 bits. Idealmente dedicada, encendida todo el día. |
| **RAM** | 8 GB alcanza, IA local incluida (el modelo recomendado ocupa 2 GB). |
| **Internet** | Estable. El bot está conectado permanentemente a Telegram. |
| **Una cuenta de Telegram** | La tuya, ya miembro del grupo de señales. |

### ¿Hace falta instalar Telegram Desktop en esa PC?

**No es obligatorio.** El bot se conecta directo a los servidores de Telegram
por su cuenta; no usa la aplicación.

Pero **sí conviene**, por una razón práctica: cuando configures el bot,
Telegram te va a mandar un código de verificación **dentro de Telegram**. Si
tenés la app en esa misma PC, lo copiás y pegás sin moverte. Si no, lo vas a
tener que leer en el celular y tipearlo a mano. Cualquiera de las dos funciona.

Si lo instalás, bajalo de **https://desktop.telegram.org** o de la Microsoft
Store; las dos versiones sirven igual.

### Cuánto tarda todo

Entre 40 minutos y una hora, casi todo esperando descargas. Los pasos 4, 5 y 6
son de MetaTrader; los 7, 8 y 9 son de Telegram. Se pueden hacer en cualquier
orden mientras el paso 3 descarga.

---

## Paso 1 — Instalar Python

Python es el lenguaje en el que está escrito el bot. Windows no lo trae.

1. Entrá a **https://www.python.org/downloads/windows/**
2. Buscá **Python 3.13** (o cualquier 3.10 o superior).
3. Bajá el que dice **"Windows installer (64-bit)"**.
4. Abrí el archivo descargado.

> ### ⚠️ El paso que hace tropezar a todo el mundo
>
> En la **primera pantalla** del instalador, **abajo de todo**, hay una casilla
> que dice:
>
> ```
> [ ] Add python.exe to PATH
> ```
>
> **Tildala antes de darle a "Install Now".**
>
> Si no la tildás, Windows no va a encontrar Python y el instalador del bot te
> va a decir que falta — **aunque lo hayas instalado correctamente**. Es el
> error más común de esta guía y el más desconcertante, porque uno jura que lo
> hizo bien.
>
> Si ya instalaste sin tildarla: volvé a abrir el instalador de Python, elegí
> **Modify**, y activá la opción. No hace falta desinstalar nada.

5. Dale a **Install Now** y esperá.
6. Cuando termine, si aparece un botón que dice **"Disable path length limit"**,
   apretalo. Evita problemas con rutas largas.

---

## Paso 2 — Descargar el proyecto

**Sin Git, que es lo más simple:**

1. Entrá a **https://github.com/ezequiel0822-netizen/telegram-copy-trading**
2. Botón verde **"Code"** (arriba a la derecha de la lista de archivos).
3. **"Download ZIP"**.
4. Se baja un archivo `telegram-copy-trading-main.zip`.
5. Clic derecho → **Extraer todo**. Elegí una carpeta simple, por ejemplo
   `C:\bot`. Evitá rutas con espacios o acentos.

> Te va a quedar una carpeta dentro de otra:
> `C:\bot\telegram-copy-trading-main\`. Esa carpeta de adentro, la que tiene el
> archivo `README.md` y la carpeta `scripts`, **es la carpeta del proyecto**.
> Cada vez que la guía diga "la carpeta del proyecto", es esa.

**Con Git** (si lo tenés instalado):

```
git clone https://github.com/ezequiel0822-netizen/telegram-copy-trading.git
```

Esta forma tiene una ventaja: para actualizar el bot más adelante alcanza con
`git pull`, sin volver a bajar el ZIP.

---

## Paso 3 — Instalar el bot

1. Entrá a la carpeta del proyecto.
2. Entrá a la carpeta **`scripts`**.
3. **Doble clic en `instalar.bat`**.

Se abre una ventana negra con texto. Eso es normal: es el instalador
trabajando. **No la cierres.**

### Qué va a ir haciendo

| Lo que ves | Qué significa |
|---|---|
| `Buscando Python 3.10 o superior...` | Verificando el paso 1. |
| `Creando entorno virtual en .venv` | Arma una carpeta aislada para no ensuciar tu Windows. |
| `Instalando dependencias` | Descarga las librerías. **Este es el paso lento**, unos minutos. |
| `Registrando el comando 'tct'` | Instala el bot en sí. |
| `Verificando MetaTrader 5` | Chequea si ya lo tenés (todavía no, es el paso 4). |
| `Verificando Ollama` | La IA local. Te va a preguntar. |
| `Corriendo los tests` | Verifica que todo quedó bien. Tienen que dar todos OK. |

### Te va a hacer dos preguntas

**1. "¿Instalar Ollama ahora?"** — Es la IA local que interpreta mensajes que
el bot no entiende. Es opcional; el bot funciona sin ella. Respondé **S** si
querés tenerla, o **n** para hacerlo después con `scripts\instalar_ia.bat`.

**2. "¿Arrancar el bot solo al prender la PC?"** — En una PC dedicada,
respondé **S**. Así, si se corta la luz y la máquina se reinicia, el bot vuelve
solo.

Al final crea un acceso directo **"Bot de Trading"** en el escritorio.

> **¿Por qué un `.bat` y no otra cosa?** Windows bloquea por defecto los
> scripts de PowerShell descargados de internet, y el error que muestra no
> explica nada. El `.bat` saltea esa restricción **solo para esa ejecución**;
> no cambia ninguna configuración de tu Windows.

---

## Paso 4 — Instalar MetaTrader 5 de FxPro

> **Importante: bajá MetaTrader del sitio de FxPro, no de otro lado.** La
> versión que distribuye el bróker ya viene apuntando a sus servidores, y eso
> te ahorra tener que buscarlos a mano. Un MetaTrader genérico también sirve,
> pero es un paso más.

1. Entrá a **https://www.fxpro.com** (o al sitio de tu bróker).
2. Buscá en el menú la sección **"Plataformas"** o **"Platforms"**.
3. Elegí **MetaTrader 5**.
4. Descargá la versión para **Windows**.
5. Ejecutá el instalador y dale siguiente hasta el final.
6. Al terminar, MetaTrader 5 se abre solo.

La primera vez suele abrirse directamente la ventana de **abrir una cuenta**.
Si es así, saltá al paso 5. Si no, también lo hacés desde el menú.

---

## Paso 5 — Crear la cuenta demo

Dentro de MetaTrader 5:

1. Menú **Archivo** (arriba a la izquierda) → **Abrir una cuenta**.
   - En inglés: **File → Open an Account**.

2. Aparece una ventana con un buscador que dice **"Buscar compañía"** o
   **"Find your broker"**.

3. Escribí **`FxPro`** y esperá un segundo. Van a aparecer una o varias
   entradas de FxPro en la lista.

4. **Seleccioná la que corresponda y dale Siguiente.**

   > Los brókers suelen tener varios servidores: uno para cuentas reales y otro
   > para demos, a veces varios de cada tipo. Si ves más de uno, elegí el que
   > diga **Demo** en el nombre. Si ninguno lo dice, elegí el primero: en el
   > paso siguiente vas a elegir explícitamente "cuenta de demostración", y eso
   > es lo que manda.
   >
   > **No te preocupes por memorizar el nombre exacto del servidor.** Más
   > adelante el bot lo lee solo (paso 8).

5. Ahora te da tres opciones. Elegí **"Abrir una cuenta de demostración"**
   (*Open a demo account*).

6. Completá el formulario:
   - **Nombre y apellido**, **email**, **teléfono**: datos tuyos. En una demo
     no se verifican, pero poné algo real para poder recuperar la cuenta.
   - **Tipo de cuenta**: la que venga por defecto está bien.
   - **Depósito**: es dinero ficticio. 10.000 USD es un valor cómodo.
   - **Apalancamiento**: 1:100 o 1:200 está bien para probar.
   - Tildá la casilla de aceptación y dale **Siguiente**.

7. **Esta es la pantalla importante.** MetaTrader te muestra:

   ```
   Login:                12345678
   Contraseña:           AbCd1234        <- ESTA es la que necesita el bot
   Contraseña inversora: XyZw5678        <- esta NO
   ```

> ### ⚠️ Hay DOS contraseñas y no son intercambiables
>
> - La **contraseña** (a veces llamada *master* o *de trading*) permite operar.
>   **Es la que necesita el bot.**
> - La **contraseña inversora** (*investor*) es de solo lectura: deja mirar la
>   cuenta pero no operar.
>
> Si ponés la inversora en el `.env`, el bot **va a loguear bien** y después
> **toda orden va a fallar**, con un error que no menciona la contraseña por
> ningún lado. Es una tarde perdida buscando en el lugar equivocado.

8. **Anotá el login y la contraseña ahora.** Esa pantalla se muestra una sola
   vez. Sacale una foto o copiala a un archivo. También llegan por email.

9. Dale **Finalizar**. MetaTrader se conecta a la cuenta.

Para confirmar que quedó conectada: abajo a la derecha de MetaTrader tiene que
aparecer un indicador con la velocidad de conexión (algo como `28/5 kb`). Si
dice **"Sin conexión"** o **"No connection"**, la cuenta no entró.

---

## Paso 6 — Activar Algo Trading

Este paso es corto y **si te lo salteás, nada funciona**.

En la barra de herramientas de arriba de MetaTrader hay un botón que dice
**"Algo Trading"** (en versiones viejas, **"AutoTrading"**).

- Si está **verde** con un ícono de "play": está activado. Listo.
- Si está **rojo** o gris con un ícono de "stop": **apretalo**.

El atajo de teclado es **Ctrl + E**.

> **Por qué importa:** MetaTrader bloquea por defecto que un programa externo
> mande órdenes. Es una protección suya. Con el botón apagado, el bot conecta
> bien, lee la cuenta bien, y cada orden vuelve rechazada con el código 10027.
>
> El bot chequea esto al arrancar y te avisa con un mensaje claro, así que no
> vas a quedar adivinando. Pero mejor dejarlo activado desde ahora.

> **Dejá MetaTrader abierto siempre.** El bot no abre MetaTrader: le habla a la
> terminal que ya está corriendo. Si la cerrás, el bot se queda sin conexión.

---

## Paso 7 — Credenciales de Telegram

El bot entra a Telegram **como tu propia cuenta**, no como un robot.

> **¿Por qué no un bot de Telegram, que suena más apropiado?** Porque un bot
> solo puede leer los mensajes de un grupo si un **administrador lo agrega** y
> además le desactiva el modo privacidad. En un grupo de señales que no es
> tuyo, eso no va a pasar. Tu cuenta, en cambio, ya está adentro y ve todo.

1. Entrá desde el navegador a **https://my.telegram.org**
2. Poné tu número de teléfono **con código de país, sin espacios ni guiones**.
   Por ejemplo: `+5215512345678`
3. Te va a pedir un código. **Ese código llega dentro de Telegram**, no por
   SMS. Miralo en la app (celular o PC) — llega de la cuenta oficial de
   Telegram.
4. Ya adentro, entrá a **"API development tools"**.
5. Completá el formulario:
   - **App title**: `copytrading`
   - **Short name**: `copytrading`
   - **URL**: dejalo vacío.
   - **Platform**: elegí **Desktop**.
   - **Description**: vacío.
6. Dale a **Create application**.
7. Te muestra dos datos. **Copiá los dos:**
   - **App api_id** — un número, tipo `1234567`
   - **App api_hash** — un texto largo, tipo `a1b2c3d4e5f6...`

> Esta pantalla se puede volver a consultar entrando de nuevo a
> my.telegram.org, así que no es dramático si la cerrás.

---

## Paso 8 — Completar el archivo .env

El archivo `.env` es donde van todas las credenciales. Está en la carpeta del
proyecto, y el instalador ya lo creó por vos.

### Abrirlo bien

Clic derecho sobre `.env` → **Abrir con** → **Bloc de notas**.

> ### ⚠️ Cuidado al guardar con el Bloc de notas
>
> Si en algún momento usás **"Guardar como"**, el Bloc de notas le agrega
> `.txt` al final y te queda `.env.txt`, que el bot **no lee**. El archivo
> parece guardado pero nada cambia.
>
> Usá siempre **Ctrl + S** (Guardar), nunca "Guardar como". Y si te pasó,
> renombrá el archivo de vuelta a `.env` exacto.

### Los datos de MetaTrader, sin buscarlos a mano

Acá está la parte que suele costar: el **nombre exacto del servidor**. No se
adivina, cada bróker tiene varios, y escribirlo mal da un error de login que no
explica nada.

**El bot lo lee por vos.** Con MetaTrader abierto y logueado, andá a la carpeta
`scripts` y hacé **doble clic en `datos_mt5.bat`**.

Te va a mostrar algo así:

```
==========================================================
  CUENTA DETECTADA
==========================================================
  Titular    : Juan Perez
  Broker     : FxPro Financial Services Ltd
  Login      : 12345678
  Servidor   : FxPro-MT5
  Balance    : 10000.0 USD
  Tipo       : DEMO

==========================================================
  QUE PONER EN EL .env
==========================================================
  Copia estas dos lineas tal cual (la tercera es tu password):

      MT5_LOGIN=12345678
      MT5_SERVER=FxPro-MT5
      MT5_PASSWORD=<la de tu cuenta demo>

  Todo en orden: cuenta demo y Algo Trading activado.
```

Copiá esas líneas al `.env` y completá la contraseña (la **master**, no la
inversora — ver el paso 5).

Además te avisa si la cuenta es real en vez de demo, o si te olvidaste de
activar Algo Trading.

### Las credenciales de Telegram

Del paso 7:

```
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=a1b2c3d4e5f6...
```

### No toques `TRADING_MODE`

Viene en `AUTO`, que revisa el archivo en cada arranque:

- Sin los datos de MT5 → corre en **modo papel** (registra, no opera).
- Con los datos de MT5 → **opera en tu cuenta demo**.

No hay que cambiar nada más para pasar de uno a otro.

Guardá con **Ctrl + S** y cerrá.

> ⚠️ El archivo `.env` da acceso a tu Telegram y a tu cuenta de MT5. **No lo
> subas a GitHub ni se lo pases a nadie**, ni siquiera por captura de pantalla.
> El proyecto ya está configurado para que git lo ignore.

---

## Paso 9 — Elegir el grupo de señales

Falta decirle al bot **qué grupo** escuchar.

### Abrir una terminal en la carpeta correcta

1. Abrí la carpeta del proyecto en el Explorador de Windows.
2. Hacé clic en la **barra de direcciones** de arriba (donde dice la ruta).
3. Escribí `cmd` y apretá **Enter**.

Se abre una ventana negra ya parada en esa carpeta.

### Activar el entorno

```
.venv\Scripts\activate
```

Vas a ver que la línea ahora empieza con `(.venv)`. **Esto hay que hacerlo cada
vez que abrís una terminal nueva.** Si algo "no anda", casi siempre es esto.

### Listar tus grupos

```
python -m tct chats
```

**La primera vez** te va a pedir, en este orden:

1. `Please enter your phone (or bot token):` → tu número con código de país,
   igual que en el paso 7.
2. `Please enter the code you received:` → un código que llega **dentro de
   Telegram**.
3. `Please enter your password:` → **solo** si tenés verificación en dos pasos
   activada. Si no la tenés, este paso ni aparece.

> Esto pasa **una única vez**. Después queda guardado en un archivo `.session`
> y no vuelve a preguntar. Ese archivo es una credencial: no lo compartas.

Después te muestra la lista:

```
              ID  TIPO      TITULO
------------------------------------------------
 -1001234567890  canal     Gold Signals VIP
 -1009876543210  grupo     Forex Team
       123456789  privado   Juan
```

Buscá el grupo de señales por su **título** y copiá el número de la columna
**ID** — el largo, **con el signo menos adelante**.

### Ponerlo en el .env

```
TELEGRAM_SOURCE_CHATS=-1001234567890
```

Si querés escuchar varios grupos, separalos con coma y **sin espacios**:

```
TELEGRAM_SOURCE_CHATS=-1001234567890,-1009876543210
```

---

## Paso 10 — Verificar

Doble clic en **`scripts\diagnostico.bat`**.

Fijate en dos lugares.

**Uno**, el modo. Tiene que decir:

```
Modo            : AUTO -> PAPER_AND_MT5_DEMO
```

Si dice `AUTO -> PAPER_ONLY`, faltan datos de MT5 en el `.env`. Tienen que
estar **los tres**: login, contraseña y servidor.

**Dos**, el resultado final:

```
  RESULTADO: todo listo para arrancar
```

Si falta algo, el mensaje dice exactamente qué. Este comando no modifica nada,
así que podés correrlo las veces que quieras.

---

## Paso 11 — Arrancar

**Doble clic en "Bot de Trading"** del escritorio.

O desde la terminal, con el entorno activado:

```
python -m tct run
```

Al arrancar vas a ver el resumen de la configuración y después:

```
Escuchando mensajes. Ctrl+C para parar.
```

Cuando llegue una señal al grupo:

```
14:32:07 INFO  tct.engine  Senal aceptada BUY XAUUSD lote=0.01 ticket=1234567
```

Y si la rechaza, te dice por qué:

```
14:35:02 INFO  tct.engine  Senal rechazada: Simbolo GBPJPY fuera de ALLOWED_SYMBOLS
```

Para pararlo: **Ctrl + C**, o cerrá la ventana.

### La primera vez, mirá un rato

Antes de irte a dormir con el bot corriendo, quedate viendo unas cuantas
señales. Es la forma de confirmar que entiende bien a *ese* grupo en
particular.

Si querés ser más prudente todavía, poné `DRY_RUN=true` en el `.env` unos días:
anota cómo interpretó cada mensaje **sin crear ninguna operación, ni siquiera
en papel**.

---

## La IA local, en criollo

El bot lee las señales con un **parser de reglas**: rápido, gratis y
predecible. Entiende los formatos habituales, con emojis, negritas y variantes:

```
XAUUSD BUY
Entry 2345
SL 2335
TP1 2355
```

Pero un grupo real a veces escribe así:

> *"muchachos entramos largos en el oro ahora tipo 2345, cuidamos abajo de 2335
> y buscamos 2355"*

Eso no lo agarra ninguna regla. Ahí entra **Ollama**, una IA que corre en tu
propia PC: gratis, sin mandar nada a internet y sin cuenta en ningún lado.
Probado contra un modelo real, ese mensaje se convierte correctamente en
`XAUUSD BUY`, entrada 2345, SL 2335, TP 2355.

### La IA no opera

Cuando entiende algo que el parser no pudo, **te lo avisa por Telegram y ahí
termina**. Vos decidís.

La razón es concreta. Las validaciones de riesgo verifican que un precio sea
**coherente**, no que sea el **correcto**. Si el modelo lee 2345 donde decía
2355, esa señal pasa todos los controles y opera con un número inventado.
Perderse una señal es barato; operar una equivocada, no.

Hay una segunda red: **todo número que la IA devuelve se busca en el mensaje
original**. Si no aparece literalmente, se descarta la interpretación entera.
Un modelo puede inventar un precio verosímil, pero no puede hacer que aparezca
en un texto que ya está escrito.

### Velocidad: usá un modelo chico

Medido sobre un procesador de 8 núcleos **sin placa de video**, con este mismo
trabajo:

| Modelo | Tamaño | Tiempo por mensaje |
|---|---|---|
| `llama3.2:3b` | 2 GB | **~25 segundos** ← recomendado |
| `qwen2.5:3b` | 2 GB | similar, suele leer mejor el español |
| 7B / 8B | 5 GB | **varios minutos** — no es práctico |

La diferencia de velocidad es enorme y la de calidad no: la tarea es acotada
(sacar 5 datos de un mensaje corto) y el formato de salida está forzado. El
instalador ya elige un modelo chico por vos.

Si la PC tuviera una placa de video NVIDIA, ahí sí conviene un 7B.

### Revisar cuánto le acierta

Cada interpretación queda registrada como `ia_sugerencia` en
`data\events.jsonl`. Después de unas semanas, mirá cuántas veces acertó de
verdad. Recién ahí tiene sentido considerar `OLLAMA_AUTO_EXECUTE=true`. Antes,
no.

---

## Uso diario

### Ver qué pasó

```
python -m tct status
```

Muestra las posiciones abiertas y el resumen de señales.

Los archivos se abren con cualquier editor:

- `data\paper_trades.jsonl` — las operaciones registradas.
- `data\events.jsonl` — **todo**: aceptadas, rechazadas con su motivo,
  ambiguas, y las sugerencias de la IA.

Que se registren también los rechazos es lo que después permite contestar *"¿por
qué el bot no tomó esta señal?"*.

### Probar el parser sin arrancar nada

Copiá un mensaje real del grupo y fijate qué entiende:

```
python -m tct test "XAUUSD BUY
Entry 2345
SL 2335
TP1 2355"
```

No toca ningún archivo ni manda nada.

### Ajustar el riesgo

Todo en el `.env`, y todo editable:

| Variable | Qué hace |
|---|---|
| `DEFAULT_LOT` | Lote de cada operación. `0.01` es el mínimo habitual. |
| `MAX_LOT` | Techo duro. Si `DEFAULT_LOT` lo supera, el bot no arranca. |
| `ALLOWED_SYMBOLS` | Lista blanca. Lo que no esté acá se rechaza. |
| `MAX_OPEN_TRADES` | Máximo de operaciones abiertas a la vez. |
| `MAX_SIGNALS_PER_DAY` | Freno por si el grupo empieza a mandar 50 señales. |
| `REQUIRE_STOP_LOSS` | Rechazar señales sin SL. **Dejalo en true.** |

### Que arranque solo al prender la PC

El instalador te lo ofrece. Para cambiarlo después:

- **Activar**: `Win + R`, escribí `shell:startup`, Enter. Copiá ahí el acceso
  directo "Bot de Trading" del escritorio.
- **Desactivar**: borrá ese acceso directo de esa carpeta.

> **MetaTrader también tiene que arrancar solo.** En MT5:
> **Herramientas → Opciones → Servidor**, y tildá guardar la contraseña de la
> cuenta. Si no, el bot arranca y se queda sin terminal a la que hablarle.

### Actualizar el bot

Si lo bajaste con Git:

```
git pull
```

Si lo bajaste como ZIP, volvé a bajarlo y **conservá tu archivo `.env`**:
copialo aparte antes de reemplazar la carpeta, y pegalo de vuelta después.

---

## Problemas frecuentes

### Instalación

**Dice que falta Python, pero lo instalé**
No tildaste **"Add python.exe to PATH"**. Abrí de nuevo el instalador de
Python, elegí **Modify**, y activá esa opción.

**`No module named tct`**
La instalación quedó a medias. Corré de nuevo `scripts\instalar.bat`.

**El antivirus bloquea algo**
Puede pasar con los `.bat`. Agregá la carpeta del proyecto a las excepciones de
tu antivirus.

### MetaTrader

**`mt5.initialize() fallo` / `Terminal: Authorization failed`**
MetaTrader 5 no está abierto, o está abierto pero sin loguear en la cuenta.
Abrilo, entrá a la demo, y volvé a probar.

**Conecta, pero las órdenes no entran / código 10027**
El botón **Algo Trading** está apagado. Apretalo hasta que quede verde, o
`Ctrl + E`.

**Login correcto pero toda orden falla**
Casi seguro pusiste la **contraseña inversora** en vez de la master. Son dos
contraseñas distintas (ver paso 5). La inversora es de solo lectura.

**`Invalid account` o el login no entra**
El nombre del servidor está mal escrito. Corré `scripts\datos_mt5.bat` con
MetaTrader abierto y copiá el valor exacto que te muestre.

**El diagnóstico dice `AUTO -> PAPER_ONLY` y yo quiero operar en demo**
Faltan `MT5_LOGIN`, `MT5_PASSWORD` o `MT5_SERVER` en el `.env`. Tienen que
estar los tres.

**El bróker rechaza el símbolo**
El bot le pregunta a MT5 cómo se llaman los instrumentos, así que esto es raro.
Si pasa, abrí MetaTrader, apretá `Ctrl + M` para ver **Observación de mercado**,
clic derecho → **Mostrar todo**, y buscá el símbolo.

### Telegram

**No llega el código de verificación**
Llega **dentro de la app de Telegram**, no por SMS. Fijate en el chat de la
cuenta oficial de Telegram, en el celular o en la PC.

**`No se pudo resolver el chat`**
El ID de `TELEGRAM_SOURCE_CHATS` está mal, o tu cuenta ya no es miembro del
grupo. Corré `python -m tct chats` de nuevo y copiá el ID otra vez.

**Pide el código cada vez que arranca**
Se borró el archivo `.session` de la carpeta del proyecto. Se vuelve a crear
con el próximo ingreso.

**El bot corre pero no reacciona a los mensajes**
Verificá con `python -m tct status` que `DRY_RUN` no esté en `true`, y que el
ID del grupo sea el correcto.

### IA local

**La IA no responde o va lentísima**
Comprobá que Ollama esté corriendo (aparece en la bandeja del sistema, al lado
del reloj). Con `llama3.2:3b` son unos 25 segundos y es normal. Si tarda
minutos, seguro estás usando un modelo de 7B: cambialo a
`OLLAMA_MODEL=llama3.2:3b` en el `.env`.

**En el log dice que se agotó el tiempo**
Subí `OLLAMA_TIMEOUT_SECONDS` en el `.env`, o pasá a un modelo más chico.

### General

**`command not found: python`**
Falta activar el entorno. Desde la carpeta del proyecto:
`.venv\Scripts\activate`

**Se cerró la ventana del bot y no sé por qué**
Mirá `logs\tct.log`, que guarda todo lo que pasó.
