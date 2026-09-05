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

> ### 🔶 Sobre los avisos "esto puede variar"
>
> A lo largo de la guía vas a ver bloques marcados así. Señalan los puntos donde
> lo que ves en pantalla **puede no coincidir exactamente** con lo que dice acá:
> porque el bróker cambió su web, porque MetaTrader usa otras palabras en tu
> versión, o porque es una parte del sistema que todavía no se pudo probar
> contra una cuenta real.
>
> No son errores. Son los lugares donde conviene leer con atención en vez de ir
> en piloto automático. Cada uno dice **qué podría verse distinto** y **cómo
> darte cuenta de que igual vas bien**.

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
15. [Dos cuentas a la vez](#dos-cuentas-de-metatrader-al-mismo-tiempo)
16. [Problemas frecuentes](#problemas-frecuentes)

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

> ### 🔶 Esto puede variar
>
> **La instalación automática de Ollama no se pudo probar.** La máquina donde se
> desarrolló ya lo tenía instalado, así que esa rama del instalador nunca se
> ejecutó de verdad. (Sí se verificó que el paquete existe en el catálogo de
> Windows con el nombre correcto.)
>
> **Si falla:** instalalo a mano desde **https://ollama.com/download**, y después
> corré `scripts\instalar_ia.bat`. El bot funciona perfecto sin la IA, así que
> esto nunca te va a bloquear la instalación.

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

> ### 🔶 Esto puede variar
>
> **Qué podría verse distinto:** los sitios de los brókers se rediseñan seguido.
> Puede que "Plataformas" esté en otro lado, se llame "Trading Platforms", o
> quede escondido en un menú desplegable.
>
> **Qué hacer:** buscá `MetaTrader 5` en el buscador del propio sitio de FxPro.
> Si no aparece por ningún lado, descargá el MetaTrader genérico de
> **metatrader5.com** — funciona igual, solo que en el paso 5 vas a tener que
> buscar el servidor de FxPro a mano en vez de que ya venga cargado.

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

> ### 🔶 Esto puede variar — es el paso más propenso a verse distinto
>
> Describí este asistente por cómo funciona en general, pero **MetaTrader cambia
> los textos entre versiones e idiomas, y cada bróker arma su propio
> formulario**.
>
> **Qué podría verse distinto:**
> - "Abrir cuenta" en vez de "Abrir una cuenta".
> - Que aparezcan más servidores de FxPro de los que esperabas, o uno solo.
> - Que el formulario pida otros campos, u ofrezca tipos de cuenta con nombres
>   raros (Standard, Raw Spread, Elite...). Para una demo, cualquiera sirve.
> - Que el orden de las pantallas no sea exactamente este.
>
> **Cómo saber que igual vas bien.** Dos cosas no cambian nunca:
> 1. En algún momento vas a elegir explícitamente **"demo"** o
>    **"demostración"**. Si no viste esa opción, parate y volvé atrás: podrías
>    estar abriendo una cuenta real.
> 2. Al final te muestra **un login y dos contraseñas**. Si llegaste a esa
>    pantalla, el paso salió bien, sin importar cómo se veía el camino.
>
> Si te perdés en el medio, sacá una captura de pantalla y mandámela.

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

> ### 🔶 Esto puede variar
>
> **Qué podría verse distinto:** el botón se llama **"Algo Trading"** en las
> versiones nuevas, **"AutoTrading"** en las viejas, y en algunas traducciones
> aparece como **"Trading algorítmico"**. También cambia el ícono.
>
> **Cómo encontrarlo igual:** es siempre el mismo botón, en la barra de
> herramientas de arriba, y **el atajo `Ctrl + E` funciona en todas las
> versiones**. Apretalo y fijate si el botón cambia de color: si pasa de rojo a
> verde, era ese.

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

> ### 🔶 Esto puede variar — es código nuevo, sin probar contra una cuenta viva
>
> Este comando se probó **solo con MetaTrader cerrado**, donde da el mensaje de
> error correcto. **Leer una cuenta real y conectada lo vas a estrenar vos.**
>
> **Qué podría salir distinto:** que algún campo salga vacío, que el nombre del
> servidor venga con un formato inesperado, o que tire un error que no está
> contemplado.
>
> **Si pasa eso**, copiame lo que imprima y lo corrijo. Mientras tanto podés
> sacar los datos a mano desde MetaTrader:
> **Herramientas → Opciones → pestaña "Servidor"**. Ahí figuran el servidor y el
> login. (En inglés: Tools → Options → Server.)

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

### Activar el entorno — ojo, depende de la terminal

Windows tiene dos terminales y **el comando no es el mismo**. Si copiás el de
una en la otra, no funciona.

**Si abriste `cmd`** (la ventana negra clásica):

```
.venv\Scripts\activate
```

**Si estás en PowerShell** (la ventana azul, o si escribiste `powershell`):

```powershell
.\.venv\Scripts\Activate.ps1
```

En los dos casos, cuando funciona, la línea pasa a empezar con `(.venv)`.
**Hay que hacerlo cada vez que abrís una terminal nueva.** Si algo "no anda",
casi siempre es esto.

> ### La forma que funciona siempre
>
> Si PowerShell te dice que **no puede cargar el archivo porque la ejecución de
> scripts está deshabilitada**, o si simplemente no querés acordarte de cuál
> comando va en cuál terminal, hay una alternativa que **no necesita activar
> nada**: llamar directamente al Python del proyecto.
>
> ```
> .\.venv\Scripts\python.exe -m tct chats
> ```
>
> Funciona igual en `cmd` y en PowerShell, y no depende de ninguna política de
> Windows. Es más largo de escribir, pero nunca falla. En el resto de la guía,
> donde diga `python -m tct algo`, podés usar
> `.\.venv\Scripts\python.exe -m tct algo` sin activar el entorno.

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

Este comando **no modifica nada**, así que podés correrlo las veces que quieras.
Es la forma de saber en qué punto estás.

### Cómo leer lo que sale

El diagnóstico imprime bastante. Estas son las líneas que importan:

| Línea | Qué significa |
|---|---|
| `Telethon : configurado` | Ya pusiste `TELEGRAM_API_ID` y `TELEGRAM_API_HASH`. |
| `Telethon : FALTA` | Faltan esos dos datos (paso 7). |
| `Chats fuente : (ninguno)` | Todavía no elegiste el grupo (paso 9). |
| `IA local : llama3.2:3b (solo avisa)` | Ollama funcionando. El "solo avisa" es lo correcto. |
| `IA local : apagada` | Sin IA. El bot funciona igual, solo pierde los mensajes raros. |
| `Modo : AUTO -> PAPER_ONLY` | Sin datos de MT5: registra pero no opera. |
| `Modo : AUTO -> PAPER_AND_MT5_DEMO` | Con MT5 conectado: **opera en tu cuenta demo**. |

Abajo de todo, cada línea que empieza con `[FALTA]` es una cosa pendiente, y
dice cuál.

### Un ejemplo a mitad de camino

Es normal que el diagnóstico diga "faltan cosas" durante un rato. Por ejemplo,
esto está **bien encaminado**, no roto:

```
    Modo            : AUTO -> PAPER_ONLY
    IA local        : llama3.2:3b (solo avisa)
    Chats fuente    : (ninguno)
    Telethon        : configurado

  [FALTA]   TELEGRAM_SOURCE_CHATS

  RESULTADO: faltan cosas (ver arriba)
```

Ahí, Python, las dependencias, el `.env` y la IA ya están. Quedan dos cosas:
elegir el grupo de Telegram (paso 9) y conectar MetaTrader (pasos 4 a 6, más el
`.env` del paso 8).

### Cuando esté todo

```
    Modo            : AUTO -> PAPER_AND_MT5_DEMO
    Chats fuente    : -1001234567890
    Telethon        : configurado

  RESULTADO: todo listo para arrancar
```

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

> ### 🔶 Esto puede variar — la primera orden real es lo menos probado del sistema
>
> Todo lo que MetaTrader expone se verificó contra el paquete instalado, pero
> **una orden de verdad contra FxPro no se pudo probar**. El punto más delicado
> es el *filling mode*: cada bróker acepta un modo distinto de ejecución y no
> avisa cuál. El bot los prueba en orden hasta que uno entre, pero es la clase
> de cosa que solo se confirma operando.
>
> **Qué mirar en la primera señal aceptada:**
> - Si en el log aparece `ticket=<un número>`, la orden entró. Confirmalo en la
>   pestaña **"Operaciones"** de MetaTrader.
> - Si aparece `retcode=` seguido de un número, algo la rechazó. **Ese número
>   dice exactamente qué pasó** — mandámelo y te digo qué ajustar.
>
> Los más comunes: `10027` (Algo Trading apagado), `10030` (filling mode),
> `10019` (fondos insuficientes), `10016` (SL o TP inválidos para ese símbolo).

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
| `MAX_SPREAD_FROM_ENTRY_PCT` | Cuánto puede alejarse la entrada del mensaje del precio **real** del instrumento, en órdenes a mercado. Ataja símbolos mal leídos y mensajes viejos. |
| `MAX_PENDING_DISTANCE_PCT` | Lo mismo para órdenes pendientes, que se ponen lejos del mercado a propósito y necesitan más aire. |

Los dos últimos son los únicos que comparan la señal contra el mundo real. Si
no sabés qué número poner, no adivines: dejá que el bot te lo diga con los
mensajes de tu propio grupo (solo lee cotizaciones, no opera):

```
.\.venv\Scripts\python.exe -m tct simular --horas 2 --con-precios
```

### Si escribir esa ruta larga te cansa

Hacé doble clic en **`scripts\consola.bat`**. Abre una ventana con el entorno
del bot ya activado, y ahí los comandos se escriben cortos:

```
tct check
tct status
tct simular --horas 2 --con-precios
```

**Por qué hace falta:** `python -m tct` a secas NO funciona, y el error que da
(`No module named tct`) no explica nada. Ese `python` es el de Windows; el bot
está instalado en el Python de la carpeta `.venv` del proyecto, que es otro.
Son dos cajas de herramientas distintas y el bot está en una sola.

Al final te muestra a qué distancia del precio real quedó cada señal y, si
rechazó alguna, qué número tendrías que poner para que entrara. **Ojo:** compara
contra el precio de *ahora*, así que usá pocas horas o los números no
significan nada.

### Que arranque solo al prender la PC

Doble clic en:

```
scripts\autoarranque.bat
```

Te dice cómo está ahora y te deja activarlo o apagarlo. También busca
MetaTrader en la máquina y te ofrece ponerlo en el inicio, que hace falta
igual.

> **Por qué no alcanza con copiar el acceso directo del escritorio.** Ese apunta
> a `iniciar_bot.bat`, que aborta si MetaTrader no está listo. Al iniciar
> sesión, MetaTrader y el bot arrancan casi al mismo tiempo, pero MetaTrader
> tarda en levantar la interfaz, conectarse y loguear la cuenta — y el bot gana
> esa carrera casi siempre. `autoarranque.bat` usa `iniciar_auto.bat`, que
> **espera hasta 5 minutos** a que MetaTrader esté listo, y además vuelve a
> levantar el bot si se cae.

**Hacen falta tres cosas, no una.** El bot necesita MetaTrader abierto y
logueado, y MetaTrader es un programa de escritorio: vive en tu sesión de
Windows. Así que "al prender la PC" en realidad significa **"al iniciar
sesión"**.

| | Qué | Quién lo hace |
|---|---|---|
| 1 | El bot en el inicio | `scripts\autoarranque.bat` |
| 2 | MetaTrader en el inicio | el mismo script te lo ofrece |
| 3 | Windows entrando solo a tu usuario | **vos** |

Sin el punto 3, si la PC se reinicia sola por un corte de luz queda en la
pantalla de contraseña y no arranca nada.

Para hacerlo: `Win + R` → escribí `netplwiz` → Enter → destildá *"Los usuarios
deben escribir su nombre y contraseña"*.

> ⚠️ Hacelo **solo si esa PC está en un lugar de confianza**: cualquiera que la
> prenda entra a tu sesión sin contraseña.

**Y en MetaTrader**, para que no te pida la contraseña en cada arranque:
**Herramientas → Opciones → Servidor**, y tildá guardar la contraseña de la
cuenta. El botón **Algo Trading** también queda como lo dejaste entre
reinicios.

### Actualizar el bot

Si lo bajaste con Git:

```
git pull
```

Si lo bajaste como ZIP, volvé a bajarlo y **conservá tu archivo `.env`**:
copialo aparte antes de reemplazar la carpeta, y pegalo de vuelta después.

---

## Dos cuentas de MetaTrader al mismo tiempo

Sirve para comparar dos brókers con las mismas señales, o para tener la demo y
la real conviviendo. Son **dos bots corriendo en paralelo**, cada uno en su
ventana.

> **Por qué dos bots y no uno con dos cuentas.** MetaTrader admite **una cuenta
> por terminal**, y el paquete de Python admite **una terminal por proceso**.
> No hay forma de que un solo bot opere dos cuentas: `login()` en MT5 *cambia*
> de cuenta, no agrega. Por eso son dos MetaTrader abiertos y dos procesos.

### Paso 1 — Instalar el segundo MetaTrader

**No reinstales el que ya tenés.** Necesitás una segunda instalación, en su
propia carpeta.

La forma fácil es bajar el MetaTrader **del otro bróker**: cada uno publica el
suyo, con su marca, y se instala en una carpeta distinta sin pisar al primero.
Por ejemplo, el de FxPro suele quedar en `C:\Program Files\FxPro MetaTrader 5\`.

1. Entrá a la web del segundo bróker y bajá **su** MetaTrader 5.
2. Instalalo. Si el instalador te deja elegir carpeta, **fijate que sea
   distinta** de la del primero.
3. Abrilo y logueate en la cuenta de ese bróker.
4. Activá **Algo Trading** (el botón verde de la barra, o `Ctrl+E`).

Ahora tenés que tener **dos MetaTrader abiertos**, cada uno en su cuenta.

### Paso 2 — Anotar la ruta de cada uno

Con dos terminales, `MT5_PATH` **deja de poder estar vacío**. Vacío significa
"engancháte a la que encuentres", y con dos abiertas eso no tiene una respuesta
correcta: los dos bots podrían ir a la misma cuenta, o cada uno a la del otro.

Para encontrar cada ruta: **clic derecho en el acceso directo** de ese
MetaTrader → **Propiedades** → mirá el campo **"Destino"**.

O pedile la lista a Windows, desde `scripts\consola.bat`:

```bash
Get-ChildItem "C:\Program Files" -Filter terminal64.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
```

### Paso 3 — Armar el segundo `.env`

```bash
copy .env.segunda.example .env.segunda
```

Abrilo con el Bloc de notas: adentro está marcado con `<<< DISTINTO >>>` todo
lo que **no** puede quedar igual que en el `.env` principal.

Y **acordate del que se olvida siempre**: en tu `.env` de siempre, poné la
misma línea `INSTANCE_NAMES` que en el nuevo.

| | `.env` (el de siempre) | `.env.segunda` |
|---|---|---|
| `INSTANCE_NAMES` | `demo,fxpro` | `demo,fxpro` — **idénticos** |
| `INSTANCE_NAME` | `demo` | `fxpro` |
| `TELEGRAM_SESSION_NAME` | `telegram_copy_trading` | `telegram_copy_trading_fxpro` |
| `DATA_DIR` y sus rutas | `data/` | `data/fxpro/` |
| `LOG_PATH` | `logs/tct.log` | `logs/tct-fxpro.log` |
| `MT5_PATH` | ruta del primer MT5 | ruta del segundo |

Si dos bots comparten la carpeta de datos, el segundo **se niega a arrancar** y
te dice por qué. Si los `INSTANCE_NAMES` no coinciden, te avisa también.

### Paso 4 — Arrancar los dos

Doble clic en cada uno, en su propia ventana:

```
scripts\iniciar_bot.bat        <- el de siempre
scripts\iniciar_segunda.bat    <- el nuevo
```

**En cada ventana, mirá esta línea antes de dejarlo corriendo:**

```
MT5 listo | servidor=XXX balance=YYY
```

Esa línea dice contra qué cuenta va a operar **de verdad**. Si las dos ventanas
dicen el mismo servidor, algo está mal en `MT5_PATH`.

### Manejarlos por separado desde Telegram

Los dos escuchan tus Mensajes Guardados, así que los comandos aceptan a quién
van dirigidos:

```
/estado              los dos contestan, cada uno firmado
/pausa fxpro         solo el de FxPro
/pausa               los dos
/cerrar demo         pide confirmar solo al de la demo
```

Cada respuesta viene firmada con `[DEMO]` o `[FXPRO]`, así que se distinguen
sin esfuerzo.

> **Ojo con `/cerrar`.** La confirmación (`SI`) caduca a los 2 minutos y
> cualquier otra cosa la cancela. Si mandás `/cerrar` sin nombre, se arma en
> **las dos** instancias y el `SI` siguiente cierra todo. Nombrá siempre a cuál
> le hablás.

### Para una tercera

Igual que la segunda: copiá `scripts\iniciar_segunda.bat` cambiándole el
`.env`, y agregá el nombre nuevo a `INSTANCE_NAMES` en **todos** los archivos.

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

**`command not found: python`** / **`python no se reconoce como un comando`**
Falta activar el entorno. Desde la carpeta del proyecto:
- En `cmd`: `.venv\Scripts\activate`
- En PowerShell: `.\.venv\Scripts\Activate.ps1`

**PowerShell: "No se puede cargar el archivo... la ejecución de scripts está
deshabilitada"**
Es una protección de Windows contra scripts descargados. Dos salidas:
- **La simple**: no actives nada y llamá directo al Python del proyecto:
  `.\.venv\Scripts\python.exe -m tct check`
- **La otra**: habilitalo solo para esa ventana, sin cambiar nada permanente:
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
  y después activá normalmente.

**Se cerró la ventana del bot y no sé por qué**
Mirá `logs\tct.log`, que guarda todo lo que pasó.
