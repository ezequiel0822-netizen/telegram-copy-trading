# Contexto Maestro — Telegram Copy Trading

**Documento de continuidad.** Si sos una IA retomando este proyecto en un chat
nuevo, leé esto entero antes de tocar código. Está escrito para que puedas
seguir sin repetir el trabajo ni volver a caer en las trampas que ya costaron
caras.

Actualizado: 2026-09-22 · v2.5.0 · 864 tests · el último commit que describe
es `f4983e6`, más este mismo cambio

**Si retomás en un chat nuevo:** leé primero **"Estado al 2026-09-22"**, al
principio de §2: es dónde quedó parado el usuario, qué tiene configurado en su
PC, qué decisiones esperan su respuesta y cuál es el próximo paso. Después §5 y
§9, que son las que evitan romper algo que costó caro.
Repositorio: https://github.com/ezequiel0822-netizen/telegram-copy-trading

---

## 1. Qué es esto

Un bot que lee señales de trading de un grupo de Telegram, las interpreta, y
las ejecuta en MetaTrader 5. Escrito en Python, corre en una **PC Windows 10
dedicada** (i5, 15 GB RAM, sin placa de video) que no es la máquina de
desarrollo.

Escalera de riesgo, en este orden y sin saltear pasos:

```
papel  →  MT5 demo  →  MT5 real
```

El usuario **no** quiere un sistema que le bloquee para siempre el paso a real.
Las protecciones tienen que ser configurables, visibles y fáciles de cambiar.
Eso viene del pedido original y sigue vigente.

---

## 2. Dónde está el usuario ahora mismo

### Estado al 2026-09-22 — leer esto primero

**El experimento ARRANCÓ.** El 22/09 a las 02:16 quedó corriendo la instancia de
FxPro con la configuración nueva, después de resolver el problema de margen que
había tenido trabado todo (abajo). Las dos instancias operan el mismo canal y
**la única diferencia que importa es el filtro de entrada tarde**: 0.05 en FxPro
contra 0.5 en MetaQuotes. La cuenta real de FxPro **todavía NO está fondeada**.

Lo que confirmó ese arranque, línea por línea: la clave de arranque se pide y
funciona, la cuenta es la de 500 (`balance=500.0`), los topes quedaron en
100/100/30 sin freno diario, el filtro sigue en 0.05, ya no aparece el aviso de
roster desparejo, y el bróker resuelve los nombres solo (`XAUUSD -> GOLD`,
`BTCUSD -> BITCOIN`, `XAGUSD -> SILVER`, `ETHUSD -> ETHEREUM`).

**Lo que tiene en su PC** (los `tct cambiar` del 20 y del 22 ya corridos; su
salida los mostró uno por uno). Recordar siempre: **el `.env` se lee solo al
arrancar**, así que cualquier cambio empieza a valer en el próximo arranque.

| | `.env` — MetaQuotes demo | `.env.segunda` — FxPro demo | `.env.real` — FxPro real |
|---|---|---|---|
| Cuenta | ~98.300 | **500**, apalancamiento **ilimitado** desde el 22/09 | #516648640, sin fondear, **sin credenciales** |
| Lote / posiciones por señal | 0.01 / 1 | 0.01 / 1 | 0.01 / 1 |
| `MAX_SPREAD_FROM_ENTRY_PCT` | **0.5** — el control | 0.05 | 0.05 |
| Topes: por símbolo / abiertas / señales día | 30 / 100 / 100 | **30 / 100 / 100** desde el 22/09 (antes 2 / 2 / 10) | **2 / 2 / 10** |
| `MAX_DAILY_LOSS_PCT` | 0 | **0** desde el 22/09 (antes 5) | **5** |
| `INSTANCE_NAMES` | `demo,fxpro,real` | `demo,fxpro,real` | `demo,fxpro,real` |
| `ALLOWED_SYMBOLS` | 11, con BTCUSD | 12, con BTCUSD y ETHUSD | solo XAUUSD |
| Clave de arranque | no (así la quiso) | **puesta y probada** | puesta, sin probar |

La pregunta de "¿solo oro en la demo?" quedó contestada por el camino: con la
demo corriendo **sin límites para experimentar**, se dejan todos los símbolos.
La real sigue con solo XAUUSD, como se decidió.

Un detalle menor que quedó: el `.env` de MetaQuotes todavía tiene
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_NOTIFY_LEVEL`, del sistema de avisos que se
sacó, y el bot lo avisa al arrancar. **Esas líneas se borran a mano**
(`notepad .env`): `tct cambiar` cambia valores, no borra líneas, y esas dos las
rechaza por obsoletas.

### El día que la demo de FxPro no pudo abrir nada, y cómo se resolvió

**Resuelto el 22/09**: era el apalancamiento de la cuenta (1:2), y él lo cambió
a **ilimitado** en esa misma cuenta desde el portal de FxPro. Queda escrito
entero porque es el mejor ejemplo de un bot que funciona perfecto y no opera
nada, y porque el mismo cheque hay que hacerlo en la real.

**El 20/09 el bot de FxPro corrió el día entero y no abrió ni una.** Todos los
intentos murieron igual, y lo dice el bróker, no el bot:

```
El broker rechazo la apertura de XAUUSD (TP1): retcode=10019 No money
```

Son 7 rechazos en el log de ese día (05:30 ×3, 06:53 ×2, 08:34 ×3, 09:05 ×2).

**El motivo, medido el 21/09 con `tct mt5 --env-file .env.segunda`: esa demo
tiene apalancamiento 1:2.** A 1:2 el bróker congela la mitad del valor de la
posición, así que 0.01 de oro (≈4.350 de exposición) pide **~2.175 de margen en
una cuenta de 500**. Y no es solo el oro: EURUSD pide 573 y GBPUSD 669. **Con
1:2 no entra nada de lo que opera este canal.** MetaQuotes sí opera porque tiene
98.000 de balance: el mismo margen le entra sin problema.

**Por qué importa más allá de la demo: es el mismo cálculo que va a hacer la
cuenta REAL de 500.** Con 1:2 una real de 500 no podría abrir ni una operación.
El apalancamiento hay que elegirlo al abrir la cuenta y **verificarlo antes de
fondear**.

Y una cosa que conviene tener clarísima, porque es contraintuitiva: **con el
lote fijo en el mínimo, subir el apalancamiento NO aumenta lo que se arriesga.**
Lo que se arriesga por operación lo fijan el lote (0.01) y la distancia del stop
(4 a 8 puntos del canal): entre 4 y 8 dólares, con cualquier apalancamiento. El
apalancamiento solo decide cuánto margen se congela mientras la operación está
abierta. Con 1:20, una sola posición ocupa el 43% de una cuenta de 500; con
1:100, el 9%. Para esta estrategia, un apalancamiento bajo no protege: impide
operar.

**Cómo terminó (22/09).** No hizo falta crear otra cuenta: el apalancamiento se
cambia desde el portal de FxPro en la cuenta que ya estaba (hace falta no tener
posiciones abiertas, y volver a loguear la terminal para que lo informe). Quedó
en **ilimitado**, que MetaTrader reporta como `1:2000000000`, y con eso el
bróker no pide margen: `tct mt5` ahora muestra *"no pide margen (apalancamiento
ilimitado)"* en todos los símbolos. La cuenta sigue siendo la misma
(#592098515), así que `.env.segunda` no se tocó.

**La cuenta REAL ya existe** (#516648640, FxPro Markets Ltd., MT5 Estándar,
Hedging), **sin fondear**, y también dice `1:Ilimitado`. **Ojo con eso**: el
ilimitado suele estar condicionado al saldo —lo dan mientras la cuenta tiene
poco dinero y vuelve a la escala normal arriba de cierto monto—, así que el
apalancamiento que va a tener con 500 adentro **no está confirmado**. Se le
pidió preguntárselo a FxPro (incluyendo el apalancamiento específico de XAUUSD,
que en muchos brókers es más bajo que el de divisas). La regla que quedó: al
fondear, **antes de arrancar el bot**, correr `tct mt5 --env-file .env.real` y
mirar el bloque del margen; si el oro dice `NO ENTRA NINGUNA`, no se arranca
nada. El margen se puede consultar incluso con la cuenta en cero: el cálculo no
necesita saldo.

**Y el experimento del filtro quedó en pausa**: la comparación necesita que
FxPro opere, y no operó nada. Los dos "rechazada por el filtro" de ese día
(06:55 y 07:11, entrada 4358 a 0.1% del mercado) **no son señales perdidas**:
son ediciones del mismo mensaje que ya había fallado por margen, reprocesadas
cuando el precio ya se había movido. Como dato del filtro, no valen.

Para que no vuelva a pasar sin avisar, `tct mt5` ahora **le pregunta al bróker
el margen de una posición y dice cuántas entran** (§3). Es el número que decide
`MAX_OPEN_TRADES`, y hasta ahora se elegía a ciegas.

**Qué están midiendo. Cambió dos veces, y lo último manda (22/09).**

El 19/09 la demo de FxPro era **el ensayo de la real**: los mismos números que
`.env.real` (2 / 2 / 10 / 5%), para ver qué haría la cuenta real antes de
fondearla. El 22/09, apenas se destrabó el margen, lo cambió: *"quiero que tome
todas las posiciones, casi casi que no tenga límite, así para experimentar a ver
si funciona o no"*. Así que **la demo de FxPro pasa a correr sin topes, igual que
MetaQuotes** (30 / 100 / 100 y sin freno diario).

Eso deja el experimento más limpio de lo que estaba: las dos instancias operan
TODO, y **la única diferencia que queda es el filtro de entrada tarde** —0.05 en
FxPro contra 0.5 en MetaQuotes—, que es justo la pregunta que se quería
contestar. Lo que se pierde es el ensayo fiel de la cuenta real; **no se pierden
los números decididos para ella**, que siguen guardados en `.env.real`
(2 / 2 / 10 / 5%) y son los que va a usar el día que se fondee.

Y de paso mide algo que antes no se podía: **cuánto habría costado o ahorrado el
freno diario del 5%**, porque ahora hay un día completo sin freno para
comparar.

**Lo que NO cambió, y se le preguntó expresamente el 22/09: sigue una posición
por señal, la del TP1** (*"no, lo dejamos que agarre el primero"*). Se le ofreció
retomar los tres objetivos ahora que el apalancamiento ilimitado hace barata la
exposición triple, y dijo que no. El motivo que se le dio, y que vale para
cuando se retome: cambiarlo ahora metería una segunda diferencia entre las dos
instancias y ninguna de las dos preguntas quedaría contestada. **Una pregunta a
la vez**, y la que está corriendo es la del filtro.

**MetaQuotes queda como está, a propósito**: sin topes que muerdan y sin
filtro, opera TODAS las señales. Cualquier señal que FxPro saltee —por el
filtro, por el tope de 2 o por el freno del 5%— se busca en el informe de
MetaQuotes y se ve cómo terminó. Antes se le habían ofrecido dos opciones
(igualar MetaQuotes a 10/20/35, o poner los números de la real en las dos);
las dos quedaron descartadas: con topes en MetaQuotes, esa instancia también
saltearía señales y se perdería justo el dato que se quiere mirar.

**El próximo paso es esperar. Lo pendiente:**

1. **Dejar correr los dos bots y juntar datos.** Son ~3 señales por día, así que
   antes de una semana no hay nada que mirar. Cuando haya, los dos informes:

   ```
   tct informe --horas 336 --con-resultados
   tct informe --horas 336 --con-resultados --env-file .env.segunda
   ```

   La pregunta: cada señal que FxPro saltee por *"La entrada estaba lejos del
   precio real"* se busca en el informe de MetaQuotes y se ve cómo terminó. Con
   eso se decide el filtro de la cuenta real. **Ojo al leer**: en el informe de
   FxPro ahora hay también señales de BTC, plata y divisas que MetaQuotes no
   opera; para la comparación del filtro solo cuentan las de oro.
2. **Confirmarle a FxPro el apalancamiento de la cuenta REAL con saldo** (arriba,
   "La cuenta REAL ya existe"). Es lo único que puede volver a trabar todo, y se
   pregunta en el chat de soporte sin fondear nada.
3. **Que confirme que el bot de MetaQuotes también quedó corriendo.** Sin el
   control no hay comparación: se le preguntó el 22/09 y no contestó todavía.

**La CLAVE DE ARRANQUE: puesta y PROBADA.** Pidió que el bot real y la demo de
FxPro le pidan una contraseña antes de arrancar (commits `3f7c82a` y `829292c`).
En el arranque del 20/09 el bot de FxPro la pidió, él le erró una vez
(*"Clave incorrecta. Te quedan 2 intento(s)"*) y con la buena arrancó: el camino
funciona de punta a punta. La de `.env.real` está puesta pero **sin probar**: ese
bot corta antes de pedirla, porque le faltan las credenciales. Lo que hizo fue,
una vez por archivo:

```
tct clave --env-file .env.real
tct clave --env-file .env.segunda
```

Desde ahí, `iniciar_real.bat` e `iniciar_segunda.bat` la piden: tres intentos,
y con la clave mal el bot no toma el candado ni conecta nada. **El bot real no
arranca sin clave puesta** —es obligatoria con dinero real—; MetaQuotes sigue
sin pedirla, como quiso. `probar --operar` y `simular --ejecutar` (en demo)
también la piden, porque mandan órdenes. En el `.env` queda una huella, no la
clave. Se le explicó que no es una caja fuerte: protege de arrancar el bot
equivocado o de alguien en la PC sin la clave, no de quien edita el `.env`.
El detalle y la regla, en §9.

**Decisiones que esperan su respuesta** (no volver a plantearlas desde cero):

- **Verificar la cuenta antes de CADA orden, no solo al conectar.** Hoy la
  verificación de que la cuenta sea la del `.env` corre una vez, en
  `connect()`. Si con el bot andando alguien cambia la cuenta de la terminal a
  mano, el bot opera la otra. Se le ofreció tres veces; el 19/09 pidió un
  ejemplo y se le mostró corriendo el código: el bot demo verificó la cuenta
  111 al arrancar, la terminal pasó a la 222 (real), llegó una señal y **la
  orden entró en la REAL** con la configuración de la demo, sin freno diario.
  Para rehacerlo: una subclase de `tests/fake_mt5.FakeMT5` con `initialize`,
  `login` (que cambia la cuenta activa), `account_info` (que devuelve la
  activa) y un `order_send` que anota en qué cuenta entró cada orden; se la
  pone en `sys.modules["MetaTrader5"]`, se llama a `connect()`, se cambia la
  cuenta activa y se manda una señal. **No está implementada** hasta que diga
  que sí; el lugar natural es `mt5_native` antes de cada `order_send`.
  Importa porque su plan pasa las dos cuentas de FxPro por la misma terminal.
- **Filtro que mire el lado.** El filtro de entrada mide la distancia sin
  mirar si el precio se movió a favor o en contra, así que un número apretado
  también saltea entradas MEJORES. Se le ofreció hacer que solo rechace cuando
  se movió en contra. Sin respuesta.
- **`MAX_SPREAD_FROM_ENTRY_PCT` en la real: 0.05, igual que la demo de FxPro**
  (decidido el 19/09, al pedir que la real sea igual a la segunda). Se revisa
  en los DOS archivos con lo que salga de la comparación, en unas dos semanas.

**`.env.real` existe, y NO se puede arrancar todavía** (tampoco hay que): tiene
`TRADING_MODE=LIVE` y `ALLOW_LIVE_TRADING=true` pero **ninguna credencial de
MT5**, y `tct check` lo rechaza con el error nuevo de §6 — que es lo correcto:
con el código anterior ese mismo archivo habría arrancado y operado la cuenta
que encontrara. **Se copió de la plantilla VIEJA**, así que tiene números que
ya no son los decididos: `MAX_DAILY_LOSS_PCT=3` (lo decidido es **5**) y
`MAX_SIGNALS_PER_DAY=5` (lo decidido es **10**). El `INSTANCE_NAMES` ya lo
corrigió él (`demo,fxpro,real`). Los dos números los corrige el `tct cambiar`
del punto 1 de arriba.

**El plan para pasar a real, tal como lo entendió el usuario:** hoy MetaQuotes
demo + FxPro demo. Cuando fondee:

1. Cerrar el bot de FxPro demo (`iniciar_segunda.bat`).
2. **Con ese bot cerrado**, loguear MetaTrader de FxPro en la cuenta real y
   correr `tct mt5` para sacar login, servidor y apalancamiento. **Ahí mismo se
   mira el bloque "CUANTO ENTRA EN ESTA CUENTA": si el oro dice NO ENTRA
   NINGUNA, no se fondea nada hasta arreglar el apalancamiento** (§2).
3. Completar `.env.real`, en una sola línea, con la password al final y **sin
   `=`** (el comando la pide sin mostrarla; escrita en la línea, la consola le
   cambia caracteres sin avisar — §5):

   ```
   tct cambiar --env-file .env.real MT5_LOGIN=<login> "MT5_SERVER=<servidor>" "MT5_PATH=<ruta a terminal64.exe>" MT5_PASSWORD
   ```

   Se puede de a una: un `.env.real` que todavía no arranca igual se guarda, y
   el comando avisa qué le falta. Lo que **no** deja tocar es `TRADING_MODE` ni
   `ALLOW_LIVE_TRADING`: las dos llaves se cambian a mano, a propósito.
4. Poner la clave, si todavía no la puso: `tct clave --env-file .env.real`.
5. `tct check --env-file .env.real` y `tct probar --operar --env-file .env.real`
   (este último pide la clave: abre y cierra 0.01 de verdad).
6. Arrancar con `iniciar_real.bat`. `iniciar_segunda.bat` no se abre más.

La regla que se le dejó, porque con una sola terminal es LA forma de perder
plata: **primero se cierra el bot, después se toca la cuenta.** Si quisiera
FxPro demo y FxPro real al mismo tiempo, hace falta una segunda instalación de
MetaTrader de FxPro en otra carpeta, con su `MT5_PATH` en cada `.env`.

**Lo que se hizo en esta tanda** (del 15 al 20/09), en §6 y §5 el detalle:
credenciales obligatorias con dinero real y la cuenta verificada contra el
`.env`; el breakeven que le alejaba el stop a la otra posición de oro; "mover
TP" con varias candidatas no mueve ninguna; `tct informe` arreglado de punta a
punta; `tct status` no toca un estado corrupto; **el sistema de avisos por
Telegram se sacó del proyecto** a pedido suyo —lo que decía va al log—; la
**clave de arranque** para el bot real y la demo de FxPro; **`tct cambiar`**,
para que los cambios de configuración no dependan de editar el `.env` a mano; y
**el margen en `tct mt5`**, que es lo que explicó por qué la demo de FxPro no
abría nada.

---

**El bot está operando señales reales del canal, en demo, y funciona.** Ya no
es un sistema que se está montando: es uno que corre y del que hay datos.

### Lo que ya pasó

- **2026-09-04**: primera vez de punta a punta (MT5 + Telegram + control +
  Ollama), y primera orden real (`tct probar --operar` abrió y cerró 0.01 de
  XAUUSD sin tropiezos). El *filling mode* funcionó a la primera.
- **2026-09-05 al 07**: el bot operó **4 señales reales del canal**, sin
  intervención. Una de ellas —SELL 4467— se puede seguir entera en el
  historial de MT5: entró en 4467.57, el `MOVER SL A 4467` le movió el stop a
  breakeven, y cerró ahí en **+0.57**.
- **2026-09-11**: **segunda instancia contra FxPro demo, funcionando.** La
  cadena completa se probó con una orden real (`GOLD` en 4345.74, abrir, mover
  el stop dos veces, cerrar). Dos datos que salieron de ahí:
  - **FxPro sí tiene cripto**, y el bot lo resolvió solo: llama `BITCOIN` a
    BTCUSD, `ETHEREUM` a ETHUSD, `GOLD` a XAUUSD y `SILVER` a XAGUSD. Nada de
    eso está en la tabla de `symbol_map.py` — sale de preguntarle a la
    terminal, que es el camino principal y por eso funciona sin configurar.
  - **El spread del oro es 35% más chico**: 0.15 contra 0.23 de
    MetaQuotes-Demo, medidos con minutos de diferencia. Importa directo para
    el breakeven (§5): menos spread es menos distancia entre la entrada del
    mensaje y el precio real de llenado.

### Cómo estaban hasta el 18/09 (historia: lo vigente está arriba)

Desde el 2026-09-13 corren **dos instancias en paralelo**, sobre el mismo
canal y con configuraciones distintas a propósito. **Esta tabla ya no es la
configuración actual** —la de hoy está en "Estado al 2026-09-22"—; se deja
porque explica de dónde salen los datos de la primera semana.

| | `.env` — instancia DEMO | `.env.segunda` — instancia FXPRO |
|---|---|---|
| Cuenta | MetaQuotes-Demo (~98.600) | FxPro-MT5 Demo (~109.600) |
| Lote | **0.1** | **0.01** |
| `POSITIONS_PER_SIGNAL` | **1** desde el 2026-09-18 (antes 3) | **1** (solo el TP1) |
| `MAX_POSITIONS_PER_SYMBOL` | 30 | 10 |
| `MAX_OPEN_TRADES` / señales día | 100 / 100 | 20 / 35 |
| `MAX_DAILY_LOSS_PCT` | sin tope | sin tope |
| `MT5_PATH` | puesto | puesto |
| Avisos | apagados (falta el chat id) | apagados (falta el token) |
| Datos | `data/` | `data/fxpro/` |

**El experimento cambió el 2026-09-18.** Era doble —MetaQuotes con los tres TP
contra FxPro con el TP1— para contestar a la vez *"¿los tres objetivos rinden
más?"* y *"¿cuánto cambia el bróker?"*. Con los datos de §2 el usuario dio por
contestada la primera y puso **las dos en un solo TP**, así que ahora las dos
instancias son la misma estrategia y lo único que queda a prueba es el bróker
—y, de paso, MetaQuotes pasa a ser un ensayo fiel de lo que va a hacer la
cuenta real—. La diferencia de lote (0.1 contra 0.01) sigue, así que los
números en plata no se comparan; las proporciones sí.

Cuatro cosas de esa tabla que hay que tener presentes:

- **Ninguna de las dos tiene freno diario.** En demo es deliberado. Antes de
  real, no.
- **Ninguna manda avisos**: el sistema se sacó del proyecto (ver abajo). Lo
  que el bot tenga que decir —el freno diario, una apertura a medias— queda en
  el log de cada instancia; y lo que pasó con cada señal, en `tct informe`.
- **El lote de MetaQuotes es 0.1, diez veces el de los datos viejos.** Los
  números en plata no son comparables con las 12 operaciones de la primera
  semana; las proporciones (TP1/TP2/TP3) sí.
- **El arranque automático NO está activado.** Los dos se arrancan a mano, con
  `iniciar_bot.bat` y `iniciar_segunda.bat`.

### Decisiones tomadas que no hay que revisar

- **BTCUSD se queda en `ALLOWED_SYMBOLS`.** MetaQuotes no lo tiene y esas
  señales quedan como paper trade; FxPro **sí** lo opera (lo llama `BITCOIN`).
- **La IA local se queda como está.** Ver §4: subirle el nivel no ayudaría.
- **El bot NO escribe nada, y el sistema de avisos YA NO EXISTE.** Lo pidió
  tres veces, la última así: *"no quiero que ningún bot me avise si abrió o no,
  solo quiero que lea los mensajes del telegram y lo haga"*. **No volver a
  proponerle avisos.** El 2026-09-18 se le ofreció `problems` para la real,
  eligió eso, y al ver los pasos del token lo corrigió: la respuesta es no.
  El 2026-09-19 pidió además sacar el código, y se sacó (commit `72556c4`):
  `notifier.py`, `tct chatid` y las tres variables `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_NOTIFY_CHAT_ID` y `TELEGRAM_NOTIFY_LEVEL`. Lo que esos avisos
  DECÍAN no se perdió: va al log (§5). Si un `.env` todavía tiene esas
  variables con valor, el arranque avisa que se pueden borrar.
  **El control por Telegram (`/pausa`, `/estado`, `/cerrar`) se quedó**: se le
  ofreció sacarlo también y eligió conservarlo, porque nunca escribe salvo que
  él escriba primero. En su `.env.real` lo tiene apagado
  (`ENABLE_TELEGRAM_CONTROL=false`), así que ahí **no hay freno desde el
  teléfono**: se para cerrando la ventana, y el arranque lo dice. Eso ya se le
  dijo una vez y está en `.env.real.example`; no hace falta repetírselo.

### El paso a dinero real: decidido, a medio hacer

**El 2026-09-15 el usuario decidió poner una cuenta REAL de FxPro con unos
500** (dólares o euros, da igual: nada en el código supone una moneda). La idea
es **reemplazar la demo de FxPro**, no agregar una tercera instancia.

**Lo que ya está listo:**

- El agujero de las dos llaves, cerrado (§9). Era crítico y estaba **en el
  camino exacto** que el usuario iba a tomar.
- `.env.real.example` al día: instancia `real`, carpeta `data/real/`, sesión de
  Telegram propia, perfil `fxpro`, una posición por señal, avisos en
  `problems`, solo XAUUSD, y las tablas de margen y de freno diario para 500.
  Verificado cargándolo de verdad: da `is_live=True`, ejecutor `mt5`, modo
  `LIVE`.
- `tct mt5` muestra ahora el **apalancamiento**, que es lo que decide cuántas
  posiciones entran en una cuenta chica.

**Las decisiones, tomadas el 2026-09-15.** Ya están en `.env.real.example`:

| | Elegido | Por qué |
|---|---|---|
| Freno diario | **5%** (25 sobre 500) | Él lo pidió como *"que a partir del 4to-5to stop loss ya tenga freno"*. Con 0.01 de oro, 1 punto = 1 dólar y cada stop cuesta 4 a 8: 5% frena en el 4º stop grande o el 6º chico. Había marcado 10%, que frena recién en el 6º al 12º —o sea casi nunca con un bot que abre 7 por día—; se le mostró la cuenta y eligió el número que hace lo que había descrito. |
| Señales/día | **10** | Medido son ~3. Con los 5 de la plantilla vieja, la 6ª se rechazaba sin haber perdido nada: el día lo tiene que cortar el freno de plata, no un contador. |
| Avisos | **apagados**, y el control también | Lo pidió así. El 18/09 había elegido `problems`, y al ver que eso implicaba token y chat id lo corrigió: no quiere que ningún bot le escriba. Sin control no hay `/pausa` desde el teléfono. |
| Símbolos | **solo XAUUSD** | BTCUSD espera a ver su margen en la cuenta real. |
| Autoarranque | **no** | Arranca a mano, como las demos. |

**La única que sigue abierta es `MAX_OPEN_TRADES`**, porque depende del
apalancamiento y ese dato está en la máquina de él: con 1:20 una posición de
oro de 0.01 pide ~217 de margen y en 500 entran 2; con 1:100, ~43; con 1:500,
~9; **con 1:2 pide ~2.175 y no entra ninguna, que es lo que pasó en la demo**
(arriba). `tct mt5 --env-file <el archivo>` lo dice con los números del bróker,
y hay que correrlo **antes de fondear**, no después.

**Y ojo con `autoarranque.ps1`:** solo conoce `.env` y `.env.segunda`. **No
agregar la real sin que lo pida explícitamente:** es plata real corriendo sin
que nadie mire. Verificado además que si el autoarranque estuvo prendido con
dos instancias y después se jubila `.env.segunda`, el acceso directo de la
segunda **sobrevive** en la carpeta de inicio: el script solo maneja las
instancias cuyo `.env` existe, así que no puede borrar el que quedó huérfano.
No hace daño —`iniciar_auto.bat` corta diciendo que el archivo no existe— pero
si el `.env.segunda` sigue ahí, arranca la demo de FxPro sola y se pelea con la
real por la terminal.

**Y una advertencia que ya se le dio una vez**, para no repetirla como si fuera
nueva: los datos de esta configuración son de pocos días, y un stop de 8 puntos
en 0.01 cuesta unos 8, el 1,6% de 500. **La decisión está tomada y es suya**;
el trabajo de acá en más es que salga bien, no volver a discutirla.

### La decisión de los tres TP: se probó y se dio de baja

**El 2026-09-18 el usuario volvió a UNA posición por señal en las dos
instancias.** El experimento corrió una semana, dejó 4 señales con tres
objetivos y los números están abajo: solo 1 de esas 4 llegó al TP2 y al TP3, y
las posiciones de más restaron ~100 contra abrir solo la del TP1. No es una
muestra para cerrar el tema, pero alcanzó para que dejara de tener sentido
pagar exposición triple por el dato, justo cuando la cuenta real va a operar un
solo objetivo igual. **Si algún día se quiere retomar, es una línea**
(`POSITIONS_PER_SIGNAL=3`), y lo que hay que volver a leer es esto de acá abajo.

**Lo que se había decidido el 2026-09-11.** Con una semana de datos reales
sobre la mesa, el usuario eligió perseguir los tres objetivos. El motivo era
recolectar datos: la cuenta es demo, así que triplicar el tamaño no costaba
nada, y era la única forma de saber cuántas veces el precio llega al TP2 y al
TP3 en vez de suponerlo.

Lo que decían los datos que había:

| De 12 operaciones | |
|---|---|
| llegaron al TP1 | **8** |
| murieron en breakeven | 3 |
| la cerró el bot | 1 |
| tocaron el stop de verdad | **0** |

O sea: el canal llega al primer objetivo dos de cada tres veces y **nunca**
llegó al stop. Eso es lo que hace que la pregunta valga la pena — si el precio
sigue de largo hasta el TP3 con alguna frecuencia, el TP1 está dejando plata
arriba de la mesa. Pero eso no se sabía, porque los TP2 y TP3 nunca se habían
mandado al bróker.

**Lo que dijeron los datos después (2026-09-17)**, con
`tct informe --horas 300 --con-resultados` sobre MetaQuotes: 20 mensajes de
apertura, 15 operados. **La premisa de arriba se cayó: el canal SÍ toca el
stop.** Dos de 15 señales fueron a stop de verdad.

| Señal | Qué pasó | Resultado |
|---|---|---|
| 11 señales en 0.01 × 1 posición | 9 en TP1, 2 en breakeven | +23.30 |
| 12:13 BUY 4295, en 0.1 × 3 | stop, las tres | −158.10 |
| 14:20 BUY 4274, en 0.1 × 3 | stop, las tres | −213.80 |
| 11:25 SELL 4284, en 0.1 × 3 | breakeven, las tres | 0.00 |
| 11:39 SELL 4281, en 0.1 × 3 | TP1, TP2 y TP3 | +188.70 |

El −159.90 total no dice nada del canal: lo arman dos señales con 30 veces la
exposición de las anteriores (lote 0.1 contra 0.01, y tres posiciones). Lo que
sí dice:

- **Con la configuración de la cuenta real** (0.01, solo el TP1) esas 15 señales
  habrían dado **cerca de +15** sobre 500. Estimado dividiendo por 10 la
  posición del TP1 de las últimas cuatro, y sin comisiones: el informe de ese
  día todavía no las descontaba.
- **Los tres TP, por ahora, no rinden.** De 4 señales con tres posiciones, 1
  llegó al TP2 y al TP3. Contra abrir solo la del TP1 con el mismo lote, las
  tres terminaron unos 100 peor: TP2+TP3 sumaron +145 en la que salió bien y
  restaron −248 en los dos stops. Cuatro señales no deciden nada.
- **Una entrada tarde se come el TP1.** Dos operadas ganaron +0.86 y +1.14:
  el mensaje decía 4386 y llenó cerca de 4389, con el TP1 en 4390. Con el stop
  a 8 puntos de la entrada del mensaje, arriesgaban ~11 para ganar ~1. El límite
  que tenía `.env.real.example` (0.3%, ~13 puntos en oro) es más de tres veces
  el TP1. **El 19/09 el usuario lo bajó a 0.05 en la real**, igual que en la
  demo de FxPro (§2, "Estado al 2026-09-22"), y la plantilla ya lo trae.
- **El arreglo del breakeven funciona en producción:** las de antes cerraban en
  −0.42 y −1.08; la de 11:25, después, cerró en **+0.00 exacto** en las tres.

**Cómo quedó implementado.** `POSITIONS_PER_SIGNAL=3` abre tres posiciones, una
por objetivo, todas con el mismo SL. MT5 admite un solo TP por posición, así
que no hay otra forma de expresarlo. Y como el lote mínimo (0.01) no se puede
partir, **cada señal pasa a valer 0.03**: el triple. Eso se imprime al arrancar
en la línea `Por senal`, para que el número esté a la vista y no en el estado
de cuenta del día siguiente.

**La consecuencia que no era obvia**, y por la que hubo que tocar otra cosa: la
posición del TP más lejano puede quedar viva horas. Con la regla vieja de *"ya
hay una posición abierta en XAUUSD"*, esa posición colgada bloquearía **todas**
las señales siguientes de un canal que opera un solo instrumento. Por eso ahora
el tope es `MAX_POSITIONS_PER_SYMBOL`: hoy **30** en la instancia demo y **10**
en la de FxPro. Antes de dinero real hay que bajarlo.

### Lo que sigue esperando datos

La pregunta de los tres TP tiene 4 señales de datos (arriba) y hacen falta
muchas más. **Antes de sacar conclusiones, el informe tiene que estar al día:**
hasta el 2026-09-17 contaba cada edición como una señal, no descontaba
comisiones y podía contar un breakeven como stop (§5). Los números de arriba se
revisaron a mano contra esos errores y aguantan, pero los siguientes tienen que
salir del informe arreglado (`git pull` en la PC de trading).

### Fricciones recurrentes que va a tener de nuevo

1. **Escribe `python -m tct` en vez de `.\.venv\Scripts\python.exe -m tct`.**
   Le pasó seis veces. El `python` a secas usa el Python del sistema, que no
   tiene el paquete. Si reporta `No module named tct`, es esto.
   → Existe `scripts\consola.bat`: doble clic y abre una ventana con el entorno
   activado, donde `tct check` funciona escrito corto. **Mandalo ahí en vez de
   volver a dictarle la ruta larga**, que es lo que no se le queda pegado.
2. **Bajó el proyecto como ZIP, no clonado.** Ya se convirtió a repo git, pero
   si vuelve a bajar un ZIP hay que repetir la conversión (`git init` +
   `remote add` + `fetch` + `reset --hard origin/main`). Verificado que
   conserva `.env`, `.session` y `data/`.
3. **Suele quedar en un commit viejo.** Cuando reporte un comportamiento ya
   arreglado, lo primero es pedirle `git pull` y confirmar el commit.

### Cómo escribe el canal (medido, no supuesto)

Un `tct simular --horas 23` sobre **David 💵 Forex | PRO** el 2026-09-04 dio
15 mensajes, 14 con texto, y **7 interpretados como evento de trading** (así lo
cuenta `cmd_simular`; son 3 aperturas más su gestión, no 7 señales). El formato es
consistente:

```
DEAL | GOLD (XAU/USD) BUY XAUUSD 4432 Parameters: 🟢TP1: 4436 ...
```

y el parser lo lee bien: símbolo, lado, entrada, SL y **tres** TPs. Las tres
señales de esas 23 horas fueron:

| | Entrada | SL | TPs |
|---|---|---|---|
| BUY | 4432 | 4424 | 4436 / 4438 / 4440 |
| BUY | 4496 | 4488 | 4500 / 4502 / 4504 |
| SELL | 4478 | 4482 | 4474 / 4472 / 4470 |

**Patrón: scalping de oro, TPs siempre a 4 / 6 / 8 puntos.** Eso corrige la
sospecha vieja de "2 puntos de stop": son 8 en los BUY y 4 en el SELL.

Vale mirar la relación riesgo/beneficio que sale de esos números, porque no es
simétrica y el objetivo de todo esto es decidir si el canal sirve:

| | Riesgo | TP1 | En TP1 |
|---|---|---|---|
| Los dos BUY | 8 | +4 | arriesga **el doble** de lo que busca |
| El SELL | 4 | +4 | 1:1 |

Con tres TPs, cuánto se cierra en cada uno cambia el resultado por completo, y
el canal no lo dice: el bot manda el TP más cercano a MT5 y los demás quedan
para los mensajes de cierre parcial. **Esto no se decide mirando la geometría,
se decide con el resultado de las operaciones** —que es la decisión pendiente de
arriba y el punto 1 de §8. La herramienta para medirlo ya existe
(`tct informe --con-resultados`); lo que falta es dejarla juntar datos.

**Detrás de cada señal viene un `MOVER SL A <la entrada>`.** O sea: el canal
manda a breakeven, pero escribiendo el número en vez de decir "BE". El parser
lo lee como `MOVE_SL` con precio explícito, que es correcto.

**Ese `MOVER SL` NO nombra instrumento**, así que aplica a todas las posiciones
abiertas. En estas 23 horas el canal operó **solo oro**, con lo cual no hizo
daño. Pero el usuario confirmó que **también opera BTCUSD**, y ahí sí importa:
con una posición de oro y una de BTC abiertas, un `MOVER SL A 4432` iría a las
dos. Lo ataja el chequeo de escala de §5 —4432 contra un BTC de seis cifras
queda fuera del factor 2— y esa es exactamente la situación para la que se
escribió.

Un mensaje narrativo (*"La línea blanca que ves es nuestro SL 4424"*) se
clasificó como `UPDATE`. No ejecuta nada, así que es inofensivo, pero genera
una notificación por Telegram cada vez. **No lo agarra `_NARRATIVA_RE`**
—comprobado: `es_descarte_deliberado()` da `False`— sino la última regla de
`_classify`: *"sin lado y sin gestión, pero con un SL nuevo: es una
modificación"*. Vale anotarlo porque manda al lugar correcto: si algún día
molesta el ruido, se toca esa regla o `_handle_update`, no el regex.

### Los 7 mensajes descartados: el parser acertó los 14

`--todos` mostró los descartes, y **ninguno era una señal**. Cuatro de ellos
tienen precios adentro, que es la familia de mensajes que costó los bugs de §6:

| Mensaje descartado | Por qué no se ejecutó |
|---|---|
| *"aquí están nuestros resultados de la oper…"* | **`_RESULTADO_RE`**: descarte deliberado |
| *"Abrí un par de operaciones de prueba…"* | no hay palabra de lado (`ABRÍ` no es `COMPRA`) |
| *"Si hubieran comprado en 4428 (captura…"* | ídem (`COMPRADO` no es `COMPRA`) |
| *"¿Pero por qué no compramos en 4428?"* | ídem (`COMPRAMOS` no es `COMPRA`) |

**Esa distinción importa y conviene no perderla.** Corrido contra el código,
`es_descarte_deliberado()` da `True` **solo para el recap**. Los otros tres no
los frena ninguna guarda: se caen porque `_SIDE_RE` no reconoce esas formas
verbales, o sea que el parser **no los entendió**, no que los descartó. Y como
no son descarte deliberado, **sí se le mandan a la IA local** (§5). Hoy eso es
inofensivo —`OLLAMA_AUTO_EXECUTE` está en `false` y la IA solo avisa— pero es
justo el escenario para el que existe esa guarda: si algún día se enciende la
ejecución automática, un *"si hubieran comprado en 4428"* llega a un modelo de
3B sin que ninguna regla lo haya frenado antes.

Los otros tres son charla (*"ya estoy en línea"*, *"intenté explicarlo"*,
*"esperemos por ahora"*).

**14 de 14: siete mensajes interpretados como evento de trading —3 aperturas,
3 `MOVER SL` y 1 `UPDATE`—, siete descartes correctos, cero falsos positivos y
cero señales perdidas.** Ojo con el 7: son *eventos*, no señales. Las señales
completas de esas 23 horas fueron **3**, las de la tabla de arriba.

Es la primera validación del parser contra datos reales de este canal. Lo que
confirma es el orden de `_classify` y `_RESULTADO_RE`, que es el que atajó el
recap. `_NARRATIVA_RE` **no se activó ni una vez** en esta corrida: lo que lo
justifica sigue siendo el caso viejo (*"pudimos cerrar otra operación"*), no
estos catorce mensajes.

Volumen: **3 señales en 23 horas**. El usuario subió el cupo diario a 100, así
que el freno de cantidad no se va a activar nunca con este canal.

### El episodio de "hubo nueve señales y leyó cuatro"

Vale entero porque la respuesta no era un bug y encontrar eso llevó tiempo.
El usuario contó nueve señales en el grupo y el bot había operado cuatro.
`tct informe --horas 24` mostró qué pasó de verdad:

- **En el grupo había 5 mensajes de apertura, no 9.** El canal **edita** sus
  mensajes —les agrega el resultado, corrige un número— y cada edición entra
  como un evento más. Cinco mensajes producían nueve eventos. Contar eventos
  en vez de mensajes infla el número. Por eso el informe agrupa por
  `message_id`.
- De esos 5: **4 se operaron** y **1 era BTCUSD**, que este bróker no tiene.

O sea: el bot no perdió ninguna señal operable. **La lección es de método:**
cuando el usuario reporta un número que no cierra, el primer paso es
`tct informe`, no teorizar. Fue construido exactamente para esto.

### Preguntas abiertas

- Ninguna sobre el canal. `--con-precios` con el mercado abierto midió las
  entradas reales contra la cotización de MT5: **entre 0.02% y 0.07%**,
  contra un límite de 0.5%. Hay diez veces de margen, así que apretar el
  número es posible, pero no urgente.
- La que sí queda es la de los tres TP, arriba, y espera resultados.

---

## 3. Arquitectura, en una pantalla

```
Telegram (Telethon, sesión de usuario)
   ↓  reader.py         descarta stickers/media, distingue texto de caption
   ↓  parser.py         reglas: rápido, gratis, determinista
   ↓  [si falla] ollama.py    IA local, SOLO avisa, nunca opera
   ↓  engine.py         orquesta; serializa con un Lock
   ↓  risk.py           todas las validaciones, cada una con su motivo
   ↑  broker.market_price()   el dato de afuera de la validacion de precio
                               (aperturas y tambien MOVE_SL)
   ↑  broker.account_equity() el del freno diario
   ↑  broker.posicion_existe() el de la exposicion (sincroniza antes de abrir)
   ↓  brokers/          paper | mt5_native (Windows) | metaapi (macOS)
   →  store.py          JSONL + estado atómico

lockfile.py   candado del SO sobre la carpeta de datos: dos instancias
              no pueden pisarse el estado (§9)
informe.py    lee lo que store.py escribió y lo explica. Fuera del camino
              de la señal, y de solo lectura (§5)
```

Módulos en `src/tct/`, salvo tres que viven en subpaquetes: `parser.py` en
`signals/`, `reader.py` en `telegram/` y `ollama.py` en `intelligence/`.
La CLI (`cli.py`) expone:

| Comando | Para qué |
|---|---|
| `check` | Diagnóstico. Lo primero en una máquina nueva. |
| `mt5` | Lee la cuenta MT5 abierta y dice qué poner en el `.env`. Con `--env-file` usa **la terminal de ese archivo** (con dos MetaTrader instalados, "la que encuentre" no tiene respuesta correcta) y agrega **cuánto margen pide una posición del lote configurado y cuántas entran en la cuenta**, preguntándoselo al bróker (`order_calc_margin`), no estimándolo. Si no entra ninguna, lo dice y nombra el `No money` que va a devolver el bróker. Anda incluso con un `.env.real` a medio llenar, que es justo cuando se necesita. **Y no le cree ciegamente al bróker**: ver §5. |
| `clave` | Pone o cambia la clave de arranque de un `.env`. La pide dos veces sin mostrarla y guarda su huella. |
| `cambiar` | **Cambia valores de un `.env` sin abrirlo**: `tct cambiar --env-file .env.segunda MAX_OPEN_TRADES=2 MAX_DAILY_LOSS_PCT=5`. Muestra antes → después, no toca otra línea, y se niega —sin guardar nada— ante un nombre mal escrito, un valor que no es del tipo o un cambio con el que el bot no arrancaría. No toca la clave ni las dos llaves del dinero real. El detalle, en §5. |
| `simular` | **Reproduce los mensajes reales del grupo.** Sin `--ejecutar` no toca nada. Con `--con-precios` compara cada entrada contra el precio real de MT5 y sugiere el límite, sin operar. |
| `probar` | Verifica la cadena contra MT5. Con `--operar` abre y cierra una posición mínima. |
| `informe` | **Qué pasó con lo que llegó.** Agrupa por mensaje (no por evento, ver §2), separa operadas de descartadas y dice el motivo de cada descarte. Con `--con-resultados` va al historial de MT5 y agrega cómo terminó cada una: TP, SL, breakeven o cierre a mano. Es de solo lectura. |
| `chats` / `test` / `status` / `run` | Listar grupos / probar el parser / ver estado / arrancar. `run --esperar-mt5 SEGUNDOS` reintenta la conexión hasta ese tope en vez de morir en el primer intento: es lo que hace posible el arranque automático. |

Los `.bat` de `scripts/` envuelven todo esto para no depender de la terminal.

---

## 4. Decisiones que no hay que re-litigar

| Decisión | Por qué |
|---|---|
| **Telethon, no Bot API** | Un bot solo lee un grupo si un admin lo agrega. En un grupo ajeno eso no pasa. |
| **Windows como plataforma principal** | `MetaTrader5` de PyPI solo publica wheels `win_amd64`, sin sdist. En macOS `pip install` **aborta**, no falla en runtime. Por eso el marcador `; sys_platform == "win32"` del `requirements.txt` **no se toca**. |
| **macOS vía MetaApi** | Único camino ahí. Se mantiene aunque ya no sea el destino. |
| **Modo `AUTO` por defecto** | Mira las credenciales del `.env` y decide. Completar `MT5_LOGIN/PASSWORD/SERVER` es lo único que separa papel de demo. |
| **Un modelo de 3B, no 7B** | Medido: en CPU sin GPU un 3B tarda ~25 s por mensaje y un 7B **varios minutos**. La tarea es acotada y el schema fuerza el formato. |
| **La IA avisa, no opera** | `risk.py` valida que un precio sea *coherente*, no que sea el *correcto*. Un 2345 leído donde decía 2355 pasa todos los controles. |
| **Una instancia por cuenta = un proceso** | MT5 admite una cuenta por terminal y el paquete de Python una terminal por proceso: `login()` reemplaza, no agrega. Verificado contra la API. Cada instancia necesita su `.env`, su carpeta de datos, su sesion de Telethon y **su `MT5_PATH`**. Los nombres salen de `INSTANCE_NAMES`, que tiene que ser identico en todos los `.env`. |
| **Equity y no balance** | Para el freno diario. El balance solo ve lo cerrado; con una posición abierta perdiendo, no se movería. |

---

## 5. Trampas del código que hay que respetar

Cada una tiene tests que fallan si se rompe. **No las "simplifiques".**

**`parser.py` — el orden de `_classify` es todo.**
```
0. _NARRATIVA_RE   → None   (antes que la gestión, porque la palabra de
                             gestión ESTÁ presente pero narrando)
1. gestión pura    (solo si NO hay señal completa)
2. _RESULTADO_RE   → None   (después de la gestión, porque HIT y PIPS sí
                             aparecen en órdenes legítimas)
3. apertura
```

**`parser.py` — el índice de TP.** `\d?(?![\d.,])` separa `TP1 2355` (índice)
de `TP 1.2700` y `TP 2330` (precio). Frágil, tocar con tests delante.

**`parser.py` — `_mask_symbols`.** Borra los nombres de instrumento antes de
buscar precios. Sin eso, el `30` de `US30` se lee como entrada.

**`reader.py` — `_MEDIA_NO_ACCIONABLE` va antes del OCR.** Un sticker es un
`Document` con atributo de sticker, o sea una imagen: si llega a Tesseract
devuelve texto basura que el parser puede leer como señal.

**`ollama.py` — todos los campos en `required`.** Ollama convierte el schema
en gramática y **no genera** lo que no es obligatorio. Con solo las 4 claves
básicas, devolvía `es_senal`/`tipo`/`confianza` y omitía todos los precios.

**`control.py` — vocabulario cerrado de destinatarios.** Cerrado, pero ya no
clavado: el roster sale de `INSTANCE_NAMES` (`config.py::_resolver_roster`), y
`{demo, real, papel, paper}` quedó como default de fábrica —
`NOMBRES_DE_INSTANCIA` es el respaldo, no la lista—. Lo que no se toca es que
sea **cerrado** y el **mismo en todos los `.env`**: sin lista fija,
`/pausa mercado feo` se leía como dirigido a una instancia llamada "mercado";
y sin los nombres de las otras, una instancia no distingue un `/pausa fxpro`
que no es para ella de un motivo escrito a mano. **La validación que frena es
solo la propia**: cada `.env` valida que su `INSTANCE_NAME` esté en su propio
`INSTANCE_NAMES`. Que dos archivos declaren listas distintas **no frena
nada**; lo avisan dos cosas: `tct run` al arrancar (`_avisar_rosters_desparejos`,
un WARNING en la ventana) y `tct cambiar` cuando se le cambia `INSTANCE_NAMES`
a un archivo (dice con cuáles de los otros coincide y con cuáles no). El
19/09 el usuario tenía `.env.segunda` desparejo (`demo,fxpro` contra
`demo,fxpro,real` en los otros dos).

**`risk.py` — el contraste con el mercado son DOS límites, no uno.** Una orden
a mercado entra al precio de *ahora*, así que una entrada lejana significa que
se leyó mal algo (`MAX_SPREAD_FROM_ENTRY_PCT`, estricto). Una pendiente se pone
lejos del mercado **a propósito**: esperar a que el precio vuelva o rompa es su
razón de ser (`MAX_PENDING_DISTANCE_PCT`, ancho). Medir las dos con el número
estricto rechaza señales buenas todos los días. Unificarlos parece una
simplificación y no lo es.

**`risk.py` — con un rango de entrada se mide contra el borde más cercano.**
`Entry 4400-4480` con el mercado en 4402 da distancia **0**, no la distancia al
punto medio (4440). El rango es una banda de precios que el grupo declaró
válidos, no un punto.

**El daño de una entrada mal leída no es el precio de entrada.** Con una orden
a mercado, MT5 entra al precio actual e ignora la entrada del mensaje: lo que
queda mal es el **stop**. Leer "entrada 2345, stop 2335" con el oro en 4438 no
abre a mal precio, abre con dos mil puntos de riesgo. Por eso el control existe
aunque la entrada parseada ni siquiera se envíe.

**`risk.py` — en la gestión se mide ESCALA, no cercanía, y son cosas distintas.**
Una entrada se compara contra el mercado con una tolerancia estricta (0.5%).
Un **stop** no: se pone lejos del mercado por definición, y cuánto es "lejos"
depende del instrumento, de la estrategia y del día. Aplicarle la tolerancia de
una entrada rechazaría stops sanos todos los días. Por eso `FACTOR_ESCALA_STOP`
es un **factor de 2**, enorme a propósito: lo único que ningún stop legítimo
hace es valer el doble o la mitad que el instrumento que protege. Apretar ese
número creyendo que "más estricto es más seguro" rompe el filtro.

**`risk.py` — la escala NO separa dos posiciones del MISMO instrumento, y por
eso existe `stop_agranda_el_riesgo`.** El chequeo de escala distingue un stop
de oro de uno de EURUSD. No puede distinguir dos posiciones de oro: 4432 es un
stop plausible para cualquiera de las dos. Y este canal opera un solo
instrumento y manda un `MOVER SL A <entrada>` detrás de **cada** señal, así que
el breakeven de una le llegaba a la otra y le **alejaba** el stop:

| | entró en | SL antes | SL después de `MOVER SL A 4432` | riesgo |
|---|---|---|---|---|
| A | 4432.5 | 4424 | 4432.5 | 0 — correcto |
| B | 4460.5 | 4452 | **4432.0** | 8.5 → **28.5 puntos** |

Con 0.01 de oro son ~28 dólares en una sola operación, contra un tope diario de
25 sobre una cuenta de 500: un mensaje de gestión rutinario armaba solo una
pérdida mayor que el presupuesto del día entero. **El freno diario no lo ataja**
—solo mira aperturas— y MT5 tampoco, porque el stop sigue del lado correcto del
mercado. Con avisos en `problems` no salía **nada**.

La guarda es **estrecha a propósito**: no prohíbe alejar un stop, que es
legítimo y tiene su test (un stop de swing 5% abajo). Solo opina cuando el
mensaje aplica a **varias** posiciones, porque ahí el número casi siempre es la
entrada de una de ellas. Con una sola abierta el mensaje no es ambiguo y se
obedece. Por eso quien llama pasa `hay_varias`: el mismo número es una orden
clara en un caso y una coincidencia en el otro.

**`risk.py` — el chequeo de escala en la gestión descarta POR POSICIÓN, no
rechaza el mensaje.** Un `MOVER SL A 4430` sin símbolo va a todo lo abierto:
4430 es un stop perfecto para el oro y una barbaridad para EURUSD. Se mueve lo
que se puede y se avisa lo que quedó sin tocar. Mover algunas y callarse las
otras sería peor que no mover ninguna.

**MT5 no alcanza como red para los stops.** Rechaza los del lado equivocado del
mercado —la mitad de los desastres— pero un stop del lado correcto y
absurdamente lejos lo **acepta sin chistar**: la posición queda sin protección
real y nadie se entera. Ese hueco es el que tapa el chequeo de escala.

**`mt5_native.py` — `positions_get()` devolviendo `None` y `()` NO es lo mismo.**
`None` es un error de consulta (terminal caída, sin conexión) y `()` es "la
busqué y no está". Confundirlos cuesta caro **en las dos direcciones**: tratar
el `()` como fallo deja una fantasma eterna, y tratar el `None` como ausencia
borra del estado una posición que puede estar viva y la deja corriendo sola.
Solo el `()` lleva la marca `raw={"ausente": True}`.

**El motor RECONCILIA con esa marca: una posición ausente se saca del estado.**
Vale para cerrar, para el parcial y para mover el SL. No es un cierre —no se
cerró nada— y por eso el aviso lo dice aparte: *"ya estaban cerradas en el
broker"*.

**`mt5_native.py` — el lote que se informa es `result.volume`, no el pedido.**
MT5 devuelve en `result.volume` el volumen que el bróker **confirmó**, y puede
llenar de menos. Todo el estado del bot se arma con ese número: el lote de la
posición, la fracción que queda tras un parcial, el aviso. Volver a
`lot=volume` (el solicitado) parece equivalente y deja al bot creyendo tener
abierto más de lo que hay.

**`control.py` — CUALQUIER comando desarma la confirmación, `/cerrar` incluido.**
Y se desarma **antes** de mirar `_es_para_mi`. Exceptuar el `cerrar` parecía lo
lógico (el `/cerrar` es justo el que la arma) y era el peor bug del proyecto: con
dos instancias, dejaba a la real armada en silencio. Desarmar de más es inocuo;
desarmar de menos cierra una cuenta.

**`control.py` — el bot se escucha a sí mismo.** Sus respuestas van al mismo
chat y vuelven a entrar. Empiezan con `[NOMBRE]` y se descartan en la primera
línea de `manejar`. Esa guarda tiene que quedar **antes** de la lógica que
cancela la confirmación: si no, el propio pedido de confirmación se cancelaría
solo al volver.

**`engine.py` — el breakeven va al precio al que el bróker LLENÓ, no al del
mensaje.** Es el arreglo que salió de mirar las primeras operaciones reales, y
la diferencia es plata.

Una orden a mercado entra al precio de **ahora**. El número que el canal
escribe es el que él vio al mandar la señal, y cuando la orden llega ya no es
el mismo: medido, de 0.02% a 0.07%. En oro, décimas de punto. Eso no importa
para nada... salvo para el breakeven, que es exactamente la operación de *poner
el stop donde entré*. Las tres que cerraron "en breakeven" la primera semana:

| | entrada del mensaje | llenó en | stop a | resultado |
|---|---|---|---|---|
| SELL | 4467 | 4467.745 | 4467.0 | **+0.57** |
| BUY | 4387 | 4387.315 | 4387.0 | **-0.42** |
| SELL | 4334 | 4333.025 | 4334.0 | **-1.08** |

Dos de tres perdieron, y no por slippage: el stop quedaba del lado equivocado
de la entrada real, **siempre por la distancia del spread**. Un breakeven que
pierde sistemáticamente no es un breakeven.

Hay un segundo detalle, y es cómo habla este canal: no dice *"a BE"*, escribe
`MOVER SL A 4467`, o sea el número de la entrada. Eso llega al parser como un
stop explícito, así que hay que **reconocerlo por el número**. Lo hace
`_destino_del_stop()`, y la comparación es **exacta a propósito**: los dos
números salen del mismo canal con el mismo formato. Aflojar esa tolerancia
tiene costo asimétrico — de más, se pisa un stop que el canal eligió a
propósito; de menos, se cae en el comportamiento viejo, que es obedecer el
mensaje. Errar para el lado de obedecer es el lado barato.

**`store.py` — `entry` y `entry_real` son cosas distintas y las dos hacen
falta.** `entry` es el número del mensaje; `entry_real` es el precio al que el
bróker llenó. El primero sirve para saber qué pidió el canal, el segundo para
saber dónde está la posición. `entry_real` queda en `None` en paper trading y
en las posiciones abiertas antes de que el campo existiera, así que **todo el
que lo use tiene que poder caer en `entry`**.

**`engine.py` — lo que el bot "avisaba" va al LOG, y no se puede borrar.** El
sistema de avisos por Telegram se sacó (§2), pero las 18 llamadas siguen: ahora
`Engine._avisar(texto, problema=...)` las escribe en el log, **WARNING** si
`problema=True` y **INFO** si es rutina. Se ven en la ventana del bot y quedan
en el archivo de `LOG_PATH`. **No las borres "porque ya no avisan"**: varias
son la única constancia que existe de algo, y sacarlas convierte *"no me
escribas"* en *"no me entero"*. Las dos que más importan:

- **El de señal RECHAZADA es la única voz del freno por pérdida diaria.**
  Cuando ese freno salta, rechaza **todas** las señales hasta el día siguiente.
  Sin esa línea, un día entero frenado se ve exactamente igual que un día sin
  señales. `/estado` tampoco lo muestra.
- **Una apertura que entró a medias avisa aparte, y tiene que seguir así.**
  Antes esa información viajaba adentro del `SENAL ACEPTADA`, que es un aviso
  de rutina: al callar la rutina se iba con él. Con `POSITIONS_PER_SIGNAL=3`,
  si el bróker acepta dos y rechaza una, el usuario cree perseguir tres
  objetivos y persigue dos — y **el informe tampoco lo muestra**: `fallidas` se
  guarda en el evento `aceptada` y nadie lo lee. No es un problema de plata
  (entra menos exposición, no más) sino de **dato**: las tres posiciones
  existen para medir cuántas veces el precio llega al TP2 y al TP3, y un 2 de 3
  invisible hace figurar el TP3 como "no llegó" cuando nunca se mandó.

**Y ningún test protegía la entrega de un aviso**, hasta que se escribieron.
Cuando se sacó el notificador, esos tests **no se borraron**: pasaron a leer
el log con `AvisosDelLog` (en `tests/test_engine.py`), así que siguen
protegiendo lo mismo — que el bot DIGA lo que hizo y lo que no pudo hacer. Ese
ayudante se engancha al logger del motor; `tests/conftest.py` lo desengancha
entre tests, porque si no se acumulan (es la familia del test que dejaba
`cli._run_async` reemplazado para toda la corrida, §7).

**`engine.py` — "mover TP" mueve SOLO la posición del TP1, y la reconoce por
índice, no por precio.** Así lo pidió el usuario el 2026-09-14: si el canal
manda "mover TP a X", se mueve el TP de la posición que persigue el TP1, las
del TP2 y el TP3 se quedan, y queda registrado cuál se movió y por qué las
otras no (evento `mover_tp`, con `movidas` y `no_movidas`). Con MetaQuotes en
`POSITIONS_PER_SIGNAL=3` se mueve una de tres.

**Y si hay VARIAS candidatas, no se mueve ninguna** (decisión del usuario,
2026-09-16). Con `POSITIONS_PER_SIGNAL=1` —la cuenta real— todas las posiciones
persiguen el TP1, así que con dos señales abiertas "la del TP1" no identifica a
ninguna. Antes un `MOVER TP A 4470` se aplicaba a las dos, y la que buscaba +3.5
puntos pasaba a buscar +37.5: el stop quedaba intacto, pero una ganancia chica
probable se volvía una moneda al aire. Ahora queda como evento `mover_tp` con
`ambiguo: true` y avisa **como problema**, con las dos posiciones y *"hacelo a
mano en MetaTrader"*. Solo cuentan como candidatas las que de verdad podrían
recibir el TP —mismo filtro que decide cuáles se mueven, en
`_motivo_para_no_mover_tp`—: si a una le quedaría del lado equivocado o fuera
de escala, no hay ambigüedad y se mueve la otra.

Tres cosas del diseño que no hay que "simplificar":

- **Hace falta un verbo explícito** (`_MOVE_TP_RE`). Medido contra el parser:
  `TP1 4450` a secas y `nuestro TP1 era 4436` —un relato— también traían un TP
  con precio y llegaban como `UPDATE`. Si cualquier TP con precio moviera
  posiciones, una crónica del canal llevaría el objetivo a un precio viejo.
  Los verbos que describen al *precio* (sube, baja, lleva, toca) quedan
  afuera, y también SET/UPDATE (`Update: TP1 4436 hit` es un resultado).
- **`tp_indice` va separado de `tp_objetivo`.** El segundo cambia cuando se
  mueve el TP; el primero no. Deducir "cuál es la del TP1" comparando precios
  deja de funcionar después del primer movimiento. Las posiciones abiertas
  antes de este campo tienen `tp_indice=None` y **no se mueven**: adivinar
  podría mover la del TP3.
- **Mover el TP conserva el stop** (`_modify_tp_sync` relee la posición y
  manda su SL). MT5 no tiene un pedido para cambiar solo el TP: el SLTP lleva
  los dos, y un 0 en el que no se quiere tocar lo borra.

**Límite conocido, a propósito:** `Mover SL a 4432 y TP a 4450` mueve el stop
pero NO el TP, porque entre el verbo y el TP hay un SL. `Mover TP a 4450 y SL a
4432` sí mueve los dos. El caso que se quiere evitar es `Mover SL a 4432, TP se
mantiene en 4440`, que pide dejar el TP quieto.

**Y de paso apareció un bug de la v1.1.0, el de los tres TP:**
`tickets_operados` leía solo `order` —la primera posición de cada señal— así
que `tct informe --con-resultados` perdía en silencio la del TP2 y la del TP3,
que es el dato para el que se abrieron. Ahora lee `aperturas` (ticket + TP de
cada una), cae en `orders` para los eventos de los primeros días, y en `order`
para los de antes.

**`mt5_native.py` — el retcode `10025 NO_CHANGES` es ÉXITO.** MT5 lo devuelve
cuando se le pide mover el stop al precio donde el stop **ya está**. O sea:
es la confirmación de que lo pedido se cumple, no un rechazo. Tratarlo como
fallo llenaba el log de `ERROR` y avisaba *"no se pudo mover el stop"* con el
stop exactamente donde correspondía. Y con este canal pasa todo el tiempo:
cada señal trae su `MOVER SL A <entrada>`, y **cada edición del mensaje lo
repite** (§2), así que el segundo y el tercero siempre encuentran el trabajo
hecho.

**La IA se consulta cuando el parser NO ENTENDIÓ, no cuando descartó.** Son
dos cosas distintas, y confundirlas anula las guardas de acá arriba. El caso
real, del canal del usuario: *"acá están nuestros resultados de la primera
operación"* lo frena `_RESULTADO_RE` a propósito... y después se le mandaba
igual a la IA, que lo leía como un `OPEN`. El descarte deliberado no servía de
nada. Por eso existe `es_descarte_deliberado()` en `parser.py`, y por eso
`_vale_preguntarle_a_la_ia()` la consulta antes de preguntar. **La IA es una
segunda oportunidad para lo ininteligible, no una apelación contra el parser.**

Y al revés también importa: un mensaje que el parser **no entendió** sí llega a
la IA, aunque tenga precios adentro. Los tres hipotéticos de §2 son de esos.

**Y una interpretación de la IA sin símbolo o sin entrada no se usa.**
`_interpretacion_utilizable()`. Un `OPEN` al que le falta cualquiera de los
dos no es una señal a medias: es la IA rellenando un formulario que no
entendió.

**`informe.py` — con TPs solapados se elige el MÁS CERCANO, no el primero.**
Los TPs de este canal están a **2 puntos** uno de otro y la tolerancia con la
que se decide "cerró en el TP" ronda los 2.2. O sea: **las ventanas se pisan**,
y un cierre exacto en TP3 cae también adentro de la de TP2. Recorrerlos en
orden y quedarse con el primero que entra reporta TP2 sistemáticamente. Es un
error de etiqueta, no de dinero, pero corrompe justo el dato con el que se va
a decidir la pregunta de los tres TP (§2).

**`informe.py` — TODO se cuenta por MENSAJE, no solo el título.** Este canal
edita lo que manda y cada edición se reprocesa. El título ya agrupaba por
`message_id`, pero el desglose, los motivos, la lista una por una y las
distancias seguían sumando eventos: con datos reales decía *"20 mensajes"*
arriba y sumaba 30 abajo, y listaba 23 "señales operadas" donde había 15. Si
alguna edición se operó, el mensaje se operó; si no, vale la última. Los motivos
salen de todas las ediciones con ese mismo resultado, una vez por mensaje.

**`informe.py` — el paper trade se escribe ANTES de llamar al bróker**, así que
existe también para señales que el bróker no pudo abrir. Las distancias solo
cuentan mensajes con evento `aceptada`, y del mismo mensaje gana el ÚLTIMO
intento: si el primero falló y una edición abrió, medir el primero da el precio
de una orden que nunca existió.

**`informe.py` — breakeven o stop se decide contra la entrada REAL.** El bot
pone el breakeven en el precio de llenado (arriba en esta sección), así que
decidirlo contra el número del mensaje contaba un breakeven como stop con un
llenado de 3 puntos, y una señal sin número de entrada como stop siempre.
`_desenlace_sync` da `precio_entrada` —el deal de entrada— y la del mensaje
queda de respaldo. Y el TP que tocó una posición sale de su `tp_indice`, no del
precio de cierre: con TPs a 2 puntos, un llenado 1.2 puntos mejor la hacía
figurar como TP2 persiguiendo el TP1. En el formato viejo `orders` el índice se
reconstruye descontando `fallidas`; si no se entiende, no se asigna ninguno.

**`informe.py` — "neto" es neto.** MT5 trae `commission`, `swap` y `fee` en
campos aparte del `profit`, y la comisión se cobra en el deal de ENTRADA. Se
suman sobre todos los deals de la posición. A 0.01 lotes, con resultados de ±1,
los costos son del tamaño del resultado mismo.

**`store.py` — `solo_lectura=True` para todo comando que promete no tocar
nada.** Abrir un `Store` normal no es inocente: si el `state.json` está
corrupto, `_load_state` lo RENOMBRA para respaldarlo. `tct informe` y
`tct status`, corridos para diagnosticar un bot caído tras un corte de luz, le
movían el archivo de las posiciones abiertas; y `status` encima decía
*"Posiciones abiertas: 0"* como un hecho. En solo lectura el estado se lee si
se puede, no se toca nunca, `estado_ilegible` lo avisa, y cualquier escritura
revienta con `RuntimeError`.

**La lectura de desenlaces es de SOLO LECTURA, y es un requisito, no un
detalle.** El usuario lo pidió así con todas las letras: *"que no interfiera
en nada, solo que almacene data sin retrasar nada ni afectar nada"*.
`desenlace_de()` llama a `history_deals_get()` y nada más: no abre, no cierra,
no toca el estado. Y **no corre en el camino de la señal** — se consulta solo
cuando alguien pide `tct informe --con-resultados`. Meterla en el motor
"para tener el dato fresco" le agregaría una consulta al bróker a cada
mensaje: dejaría de ser gratis y dejaría de cumplir lo que se pidió.

**`cli.py` — `--env-file` se acepta ANTES y DESPUÉS del comando.** Argparse
solo da lo primero; lo segundo (`tct probar --env-file .env.segunda`) es lo que
sale solo de escribir, y es la forma que usaban la guía y la propia plantilla.
Daba `unrecognized arguments`, que no dice que haya que mover el argumento de
lugar. Se arregló agregando las opciones comunes a cada subcomando con
`default=argparse.SUPPRESS`: **el `SUPPRESS` es lo que las hace convivir**, sin
él el subcomando escribe su `None` encima del valor que puso el parser
principal y la forma que sí andaba deja de andar.

**`archivo_env.py` (`tct cambiar`) — lo que el bot LEE es lo único que cuenta.**
El comando edita el `.env` sin abrirlo, y todo lo delicado está en que el
archivo nuevo, leído por el mismo lector que usa el bot (`dotenv_values`), sea
el viejo más lo pedido. Cinco cosas que no hay que "simplificar":

- **La última red (`verificar_lectura`) relee el archivo nuevo antes de
  reemplazar el viejo**, y compara: cada valor pedido tiene que llegar tal
  cual, y ninguna otra variable puede cambiar, aparecer **ni aparecer sin
  valor** —así es como python-dotenv lee el pedazo suelto que queda cuando se
  reemplaza la primera línea de un valor de varias—. `tct clave` usa la misma
  red: sin ella, un "Listo" podía dejar vigente la huella VIEJA.
- **Se reemplazan TODAS las asignaciones de esa variable, no la primera:**
  python-dotenv se queda con la última.
- **Se corta donde corta python-dotenv** (CRLF, LF y **un CR suelto**), y en
  nada más: `splitlines` corta también en U+2028 y en el tabulador vertical,
  que para python-dotenv son parte del valor.
- **El "antes" se lee del ARCHIVO, no del texto ya cargado en memoria.** Abrir
  en modo texto convierte los CRLF de adentro de un valor de varias líneas:
  leer el antes de una forma y el después de otra hacía parecer que ese valor
  había cambiado, y rechazaba cambios buenos.
- **Una asignación que aparece o desaparece cuenta como cambio, aunque el bot
  lea lo mismo** (`verificar_asignaciones`, con el parser de python-dotenv).
  Partir un valor de varias líneas deja un pedazo suelto que puede quedar
  tapado por otra asignación de más abajo: el bot lee bien y el archivo queda
  con basura. Y un pedazo así **no se nombra como si fuera una variable** en el
  mensaje: no existe en ninguna parte y manda a buscar un fantasma.
- **Un error de configuración que ya estaba no frena el cambio; uno nuevo sí.**
  Es lo que permite completar `.env.real` de a una credencial. Se distingue por
  las variables que el error NOMBRA: si nombra alguna de las que se cambiaron
  —o ninguna, y entonces no se le puede atribuir a otra—, se rechaza.

**`tct cambiar` — las credenciales NO se aceptan en la línea del comando.**
cmd.exe procesa la línea antes de que llegue al bot: se come los `^`, corta en
`&` y `>`, reemplaza `%ALGO%` y saca las comillas dobles. Con un número no
pasa nada; con una password de broker sí, y como en pantalla sale `****`, no
había forma de darse cuenta de que se guardó otra —el bot fallaba al loguear
días después—. Por eso `MT5_PASSWORD`, `TELEGRAM_API_HASH` y `METAAPI_TOKEN`
van **sin `=`** y el comando las pide dos veces sin mostrarlas, que es texto
que cmd no toca. Por lo mismo se rechaza lo que tiene pinta de haber pasado por
ese filtro: un valor partido por un espacio, una comilla doble adentro, u otro
`NOMBRE=VALOR` pegado dentro de un valor (eso último cambiaba `DATA_DIR` a una
carpeta nueva y el bot arrancaba sin sus posiciones abiertas).

Dos detalles de esa familia que costaron un hallazgo cada uno: el consejo de
*"el valor va entre comillas dobles"* **corta en el nombre de la variable
siguiente** —si no, `MT5_SERVER=FxPro-MT5 Live MT5_PASSWORD` sugería pegar
`MT5_SERVER="FxPro-MT5 Live MT5_PASSWORD"`, que se acepta, deja la cuenta real
sin poder loguear y encima se come el pedido de la password—; y **sin consola
no se pregunta nada** (`hay_teclado()`): `getpass` lee del teclado y no de la
entrada, así que con la entrada redirigida el proceso se quedaba esperando para
siempre, sin mensaje. Los comandos que sugiere van **entre comillas si la ruta
tiene espacios**, porque la carpeta del proyecto se llama "telegram copy
trading".

**`tct cambiar` — solo edita un `.env` que algún bot lea.** Lo peor que puede
hacer este comando es editar **una copia**: con TAB, al lado de `.env.real`
aparecen el respaldo (`.env.real.bak`), el `.env.txt` que deja el "Guardar
como" del Bloc de notas y el `.env.real.tmp` de un cambio cortado por la mitad.
Editar cualquiera de esos salía *"Listo"* con los antes → después bien puestos,
y el bot real seguía leyendo el original —con el freno del día en 0 y la
persona convencida de haberlo puesto en 5—. Por eso `es_env_de_un_bot()` decide
qué archivo se puede tocar (`.env`, `.env.segunda`, `.env.real`…, y **no** los
`.example`, `.tmp`, `.bak`, `.txt`), y el rechazo dice cuál era el bueno. La
misma función filtra los avisos de roster: mandar a "arreglar" un respaldo
confunde. **Si algún día hace falta un `.env` con otro nombre, se edita a mano**
—eso es a propósito: el riesgo de la copia es peor que la incomodidad—.

**`tct mt5` — el margen que contesta el bróker puede ser 0, o absurdo, y un
número que miente es peor que ninguno.** Medido en la demo de FxPro a 1:2 el
21/09: `order_calc_margin` devolvió **0.0 para GOLD y para BITCOIN** —los dos que
importaban— mientras el bot recibía `No money` en cada apertura; y para la plata
devolvió **3.69**, donde por contrato y apalancamiento salen más de 1.300. Un
`0.00` en pantalla se lee como *"no pide margen"*, que es exactamente lo
contrario de lo que pasaba. Por eso el diagnóstico:

- si el bróker no da un número mayor que cero, **estima** con
  `contrato × precio × lote / apalancamiento` y lo marca `(estimado)`;
- si el número del bróker es menos de un tercio del calculado, lo muestra igual
  —es el que el bróker va a usar— pero con `(?)` y un aviso aparte, porque decir
  *"entran 135"* de algo que no entra ninguna es peor que no decir nada;
- si no hay con qué estimar (sin apalancamiento o sin tamaño de contrato), dice
  que no sabe. **Inventar un número acá es peor que no darlo**: con ese número se
  decide si la cuenta real sirve.

También avisa si el **lote mínimo** del símbolo es mayor que el `DEFAULT_LOT`
configurado: el ejecutor no manda un volumen por arriba de `MAX_LOT`, así que ese
instrumento no se puede operar y conviene saberlo antes de verlo fallar.

**Y el apalancamiento ilimitado no es un cero sospechoso.** MetaTrader no tiene
cómo decir "ilimitado" en un campo entero, así que lo informa como un número
enorme: FxPro manda `1:2000000000`. Ahí el margen **es** cero y el cero del
bróker está bien, así que se muestra *"no pide margen (apalancamiento
ilimitado)"* en vez de estimar y marcarlo como dudoso —hacer dudar de un dato
correcto gasta la misma confianza que un dato falso—.

**`tct cambiar` — un número que apaga una protección se rechaza.**
`MAX_DAILY_LOSS_PCT=-5` o `=nan` **apagan el freno diario** (`risk.py` lo mira
con `<= 0`) mientras el arranque sigue imprimiendo *"Tope perdida dia: -5.0%"*.
`config.py` los acepta sin decir nada —eso sigue igual, es el punto 23 de §8—,
así que el comando no deja escribirlos: negativos y `nan`/`inf` se rechazan con
el motivo ("para frenar al perder 5%, se escribe 5, sin signo").

**`.env` — las comillas dobles rompen TODA ruta de MetaTrader.** `python-dotenv`
interpreta las secuencias de escape solo cuando el valor esta entre comillas
dobles, y toda instalación de MT5 termina en `\terminal64.exe`:

| en el `.env` | resultado |
|---|---|
| `MT5_PATH="C:\...\MT5\terminal64.exe"` | **ROTO**: el `\t` se vuelve un TABULADOR |
| `MT5_PATH=C:\...\MT5\terminal64.exe` | bien |
| `MT5_PATH='C:\...\MT5\terminal64.exe'` | bien |

Lo cruel es que entrecomillar una ruta con espacios es exactamente lo que
piden cmd y PowerShell: la costumbre correcta en todos lados rompe la única
variable donde el `\t` es inevitable. Pasó en producción, montando la segunda
instancia. El síntoma era *"MT5_PATH apunta a un archivo que no existe"* con la
ruta impresa y un hueco en el medio indistinguible de un espacio.

**Y volvió a pasar escribiendo esta misma sección**: el parche que la agregaba
usaba un heredoc, y el `\t` del ejemplo se convirtió en un tabulador de verdad
adentro del documento. Es la trampa de §7 mordiendo mientras se documentaba
otra trampa. Se arregló con la herramienta de edición, que es lo que §7 dice.

`config.py::_revisar_ruta_de_mt5` lo caza al cargar -o sea que `tct check` lo
dice antes de intentar arrancar- y **no lo repara solo a proposito**: reparar
el tabulador dejaria a la persona creyendo que las comillas estan bien, y la
proxima ruta que escriba se rompe igual.

**`.gitattributes` — `.sh` en LF, `.bat`/`.ps1` en CRLF.** Un `.bat` con LF
falla en `cmd.exe` de formas difíciles de diagnosticar.

**MetaApi SDK:** `account.get_rpc_connection()` devuelve un
`RpcMetaApiConnectionInstance`, **no** un `RpcMetaApiConnection`. Los métodos
de trading viven solo en el primero.

---

## 6. Los bugs que se encontraron, y cómo

Tres revisiones independientes ejecutaron el código (no lo leyeron) y
encontraron **catorce** bugs, varios capaces de perder plata. Todos arreglados,
todos con tests de regresión. Vale la pena saber **por qué** existían:

### El punto ciego que los ocultó a todos

**Los 183 tests corrían contra el bróker de papel, que nunca devuelve
`ok=False`.** La rama de error del motor no se ejecutó una sola vez. Por eso
convivían tests en verde con bugs que dejaban plata corriendo sin registro.

Ahora existe `tests/test_broker_falla.py` con un bróker que rechaza a voluntad.
**Cualquier cambio en el camino de ejecución tiene que probarse ahí.**

### Los que ejecutaban operaciones equivocadas

- **Recaps abrían operaciones.** `"✅ CERRADA EN GANANCIA / GOLD SELL 2350 / SL
  2360 / TP 2340"` abría un SELL nuevo. Mirado como datos, un recap es
  idéntico a una señal.
- **Crónicas cerraban posiciones.** Caso real del canal del usuario: *"Hoy es
  un día mágico. Pudimos cerrar otra operación"* → CLOSE de todo.
- **Símbolo equivocado.** Ganaba el alias más largo del diccionario sin
  importar dónde apareciera: `"Mientras el gold descansa, BTC BUY 65000"` abría
  **oro**.
- **Pips como stop loss.** `"Move SL to BE, +80 pips"` ponía el SL del oro en 80.
- **`@usuario` como precio.** `"@gold2345"` al pie pisaba la entrada.
- **Dígitos del símbolo como precio.** `US30 SELL 39,500` → entrada 30.

### Los que desincronizaban estado y bróker

- **Posición fantasma:** `order.ok` no se miraba al abrir. Quedaba registrada
  una posición que en MT5 no existía, bloqueando el símbolo para siempre.
- **Operación huérfana:** al cerrar se borraba del estado aunque el bróker
  rechazara. Seguía viva en MT5 y sin registro.
- **El estado mentía sobre el stop** al fallar un `modify_stop_loss`.
- **Una edición reabría una operación cerrada.** Los canales editan el mensaje
  viejo para marcar el resultado.
- **Carrera:** el riesgo se evaluaba antes de un `await` y la posición se
  registraba después. Dos señales simultáneas se saltaban `MAX_OPEN_TRADES`.

### Los que existían solo en la pantalla

- **El control por Telegram nunca estuvo conectado.** `ControlTelegram` y
  `escuchar_comandos` no se referenciaban desde ningún lado fuera de su módulo
  y sus tests. `iniciar_real.bat` imprimía *"para pausarlo: /pausa real"* y ese
  mensaje no lo leía nadie.
- **El freno por pérdida diaria no frenaba.** `risk.py` leía
  `store.balance_actual`, que no se asignaba en ningún lado de `src/`. El
  arranque igual imprimía *"Tope perdida dia: 3.0%"*.

**Los dos comparten causa: se probó la unidad, no el cableado.** Los tests
instanciaban las clases a mano. Ahora hay tests que verifican por
introspección que `_run_async` las use.

### Segunda ronda: los handlers que nadie había revisado

Una auditoría posterior encontró seis más. Todos en código que las 230 pruebas
verdes recorrían sin ejercitar, por el mismo punto ciego de siempre.

- **`/cerrar demo` + `SI` cerraba también la cuenta REAL.** El peor del
  proyecto, y hacía falta una secuencia normalísima para dispararlo: un
  `/cerrar` a secas armaba la confirmación en **las dos** instancias; el
  `/cerrar demo` siguiente no desarmaba a la real —el reset se salteaba justo
  para el comando `cerrar`— y encima no le contestaba nada, así que quedaba
  armada **en silencio**; y el `SI`, que no tiene destinatario, disparaba a
  todas. Con una sola instancia corriendo, invisible.
- **La confirmación no caducaba nunca**, y el bot prometía *"cualquier otra
  cosa lo cancela"* siendo mentira: un "no" explícito no cancelaba nada, porque
  solo se miraba si el texto era afirmativo.
- **`_handle_partial_close` no miraba `order.ok`.** Descontaba el lote y
  borraba la posición aunque el bróker rechazara. Es la *operación huérfana* de
  más arriba, viva en el único handler que no se había revisado: un solo
  `close 99%` rechazado la borraba del estado y la dejaba corriendo en MT5.
- **Un cierre parcial sobre el lote mínimo cerraba el 100%** y el estado creía
  conservar la mitad. Con `DEFAULT_LOT=0.01`, un "close 50%" pide 0.005, el
  bróker lo sube a 0.01 y cierra todo. La posición fantasma bloqueaba el
  símbolo y ocupaba cupo de `MAX_OPEN_TRADES` para siempre.
- **`MAX_LOT` no se aplicaba al volumen que realmente se manda.**
  `_normalize_volume` sube el lote hasta el mínimo del instrumento, y `risk.py`
  solo compara `DEFAULT_LOT` contra `MAX_LOT`. Un índice con `volume_min=0.1`
  abría una posición **diez veces** más grande que el techo configurado.
- **El aviso de mover el SL mentía.** El estado ya aguantaba (eso estaba
  arreglado), pero el mensaje contaba los rechazos como movidas y decía *"SL
  movido en 1 posición(es)"* con el bróker habiendo rechazado todo. Desde el
  teléfono, eso es creerse protegido en breakeven sin estarlo.

**Causa común de los cuatro últimos: se confiaba en lo que se PIDIÓ, no en lo
que el bróker HIZO.** Ahora el estado se reconstruye con `OrderResult`: el lote
que se guarda es el que aceptó el bróker, y el descuento de un parcial se
calcula con el volumen realmente cerrado.

La otra pieza que faltaba es `tests/fake_mt5.py`: una terminal MT5 falsa que
ajusta volúmenes al mínimo del instrumento, sabe llenar de menos y sabe
rechazar. Todo lo de arriba es indetectable contra el bróker de papel.
**Cualquier cambio en el volumen o en el estado de las posiciones se prueba ahí.**

### Tercera ronda: los cuatro que dejó el arreglo anterior

Una revisión posterior encontró cuatro huecos **en los arreglos de la segunda
ronda**, que es la moraleja en sí misma: arreglar una familia de bugs no la
cierra sola.

- **Una barra pelada (`/`) reventaba con `IndexError` antes de desarmar la
  confirmación.** `partes[0]` sobre un `"/"` solo. En producción el listener se
  traga la excepción: la persona no recibía respuesta, la confirmación quedaba
  viva, y el `SI` siguiente cerraba. Un agujero justo en la propiedad que el
  arreglo anterior había establecido.
- **Cancelar la confirmación era SILENCIOSO**, y ese es el peligro simétrico:
  pedís `/cerrar todo`, mandás un `/posiciones` para chequear, contestás `SI`...
  y no pasa nada, sin un solo mensaje. Te vas creyendo que cerraste.
- **`mt5_native` informaba el volumen PEDIDO, no el ejecutado.** MT5 devuelve el
  confirmado en `result.volume` y puede llenar de menos. Como el motor ahora
  construye el estado con ese número, el arreglo anterior quedaba a medias: el
  bot creía tener abierto más de lo que hay.
- **Un breakeven sobre una posición sin entrada registrada se salteaba en
  silencio.** `evaluate_management` solo rechaza si NINGUNA la tiene; con una
  mezcla, la que no la tenía quedaba sin tocar mientras el aviso anunciaba
  éxito.

Y uno más, que venía de la primera auditoría y quedó sin atender:

- **Una posición cerrada a mano en MetaTrader quedaba imposible de limpiar.**
  *"Posición inexistente"* se trataba como un rechazo, o sea como *"no pude
  cerrarla, sigue abierta"*. Es al revés: es la única información capaz de
  resolver una fantasma. Y el escenario no tiene nada de raro — **la propia
  guía le pide al usuario que cierre a mano lo que no quiera**. Desde ese
  momento el bot tenía una posición que no podía cerrar nunca, que bloqueaba el
  símbolo por la regla de *"ya hay una posición abierta"* y ocupaba cupo de
  `MAX_OPEN_TRADES`: cada señal de ese instrumento se rechazaba, para siempre.
  Probablemente era el bug más **probable** de todos los que quedaban.

Los cuatro primeros los encontraron revisores independientes que **murieron por
límite de uso antes de poder reportar nada**. Se recuperaron de los `git worktree` que
dejaron atrás, corriendo los tests que habían escrito. Si volvés a quedarte sin
resultados de una revisión, mirá ahí antes de darla por perdida:
`git worktree list`.

### Cuarta ronda: los que solo aparecen cuando el bot ya está operando

Los de las tres rondas anteriores salieron leyendo código. Estos salieron de
**mirar el log de una máquina que estaba operando de verdad**, y ninguna
revisión de escritorio los habría encontrado, porque todos dependen de cómo
se comporta este canal en particular.

- **Una operación que cerró sola bloqueaba la señal siguiente.** El más caro
  de todos. Este canal **no manda mensajes de cierre**: las operaciones
  terminan en el TP o el SL y el bróker las cierra sin avisarle a nadie. El
  bot seguía creyéndolas abiertas, y la regla de *"ya hay una posición en
  XAUUSD"* —que es buena— rechazaba todo lo que viniera después. Con un canal
  que opera **un solo símbolo**, eso es perder casi una señal de cada dos, en
  silencio y para siempre. Se arregla sincronizando contra el bróker antes de
  evaluar una apertura (§9).
- **Un corte de internet apagaba el bot y el log decía "Cerrado limpio".** La
  peor combinación posible: se cae solo y encima te tranquiliza. Ahora
  Telethon reintenta para siempre (`connection_retries=-1`) y, si igual se
  corta, el log lo dice como lo que es.
- **El arranque automático no podía ganarle la carrera a MetaTrader.** Al
  prender la PC, el bot levantaba antes que la terminal y moría con
  `IPC initialize failed`. Un autoarranque que falla la mitad de las mañanas
  es peor que ninguno, porque no te enterás. → `run --esperar-mt5`.
- **Una señal que el bróker no podía operar igual gastaba cupo del día.** El
  contador subía al aceptar la señal, no al confirmarla el bróker: cada
  BTCUSD —que este bróker no tiene— se comía un lugar de `MAX_SIGNALS_PER_DAY`.
  Ahora sube **después** de la confirmación.
- **La capa de IA rodeaba por atrás la guarda de los recaps.** El
  *"acá están nuestros resultados de la primera operación"* de §2 lo frena
  `_RESULTADO_RE` a propósito... y después se le mandaba igual a la IA, que lo
  leía como un `OPEN`. No llegó a operar nada —la IA solo avisa— pero cada
  mensaje y cada edición costaban una notificación y ~15 segundos de CPU. La
  guarda mejor probada del proyecto tenía una puerta atrás.
- **El informe contaba eventos y decía 9 donde había 5.** Ver §2: el canal
  edita sus mensajes. No es un bug de trading, es un bug de **la herramienta
  con la que se diagnostica el trading**, que es peor de lo que suena: manda
  a buscar bugs que no existen.
- **`10025 No changes` se registraba como error.** Ver §5.
- **Dos instancias podían compartir carpeta de datos sin enterarse.** El lock
  de `lockfile.py` es del sistema operativo, no un archivo con un PID adentro,
  así que un corte de luz no deja un candado trabado.

### Quinta ronda: el que solo se ve en el estado de cuenta

Uno solo, pero costaba plata en cada operación, y ninguna revisión de código lo
habría encontrado: hacía falta mirar los **resultados**.

- **El breakeven se ponía en el número del mensaje y no donde la posición
  estaba de verdad.** El usuario lo notó como *"no pone bien los stop loss"*.
  Las tres operaciones que habían cerrado "en breakeven" daban +0.57, **-0.42**
  y **-1.08**: dos de tres perdiendo, siempre por el tamaño del spread. No era
  slippage ni mala suerte — el stop quedaba del lado equivocado del precio de
  entrada real, sistemáticamente. Ver §5, que tiene la tabla con los números.

  **Lo que lo hace interesante como lección:** el bot hacía exactamente lo que
  el mensaje decía. `MOVER SL A 4467` → stop en 4467. El bug no estaba en
  ejecutar mal una orden, sino en tomar al pie de la letra un mensaje cuya
  *intención* era otra. Esa clase de error no aparece en un test unitario ni en
  el log: aparece en el P&L, y solo si alguien lo mira.

  Y se encontró porque existía `tct informe --con-resultados`. Sin esa
  herramienta, las tres operaciones figuraban como "breakeven" y nadie iba a
  sospechar nada.

### Sexta ronda: los que solo se ven mirando el camino de la cuenta real

Salieron auditando el camino `is_live` justo antes de poner los 500 en FxPro.
Ninguno lo habría encontrado la suite: los 583 tests estaban en verde con los
tres adentro.

- **Una `.env.real` a medio llenar operaba la cuenta que encontrara.** El más
  grave, y estaba en el camino exacto de copiar la plantilla y completarla a
  mano. Eran **tres cosas apiladas**: `LIVE` no exigía ninguna credencial de
  MT5 (MetaApi sí exigía las suyas); `connect()` solo llama a `login()` con las
  TRES puestas y si falta una **se lo saltea sin decir nada**; y nadie comparaba
  jamás la cuenta conectada contra `MT5_LOGIN`. Arriba de todo eso,
  `_ensure_demo` no opina porque con las dos llaves da por autorizado todo.
  Medido con la plantilla tal cual: `tct check` contestaba
  *"Ejecución: [OK] Modo LIVE"* y `connect()` devolvía `True` enganchado a
  `MetaQuotes-Demo #98600`. Con dos MetaTrader instalados, *"la terminal que
  encuentre"* no tiene respuesta correcta.
- **`tct simular --ejecutar` operaba contra la cuenta real sin pedir nada.**
  `simular` reproduce mensajes **viejos**: ejecutarlos abre posiciones
  siguiendo señales de hace horas a precios que ya pasaron. No hay ninguna
  situación en que eso sea lo que alguien quería. Y el riesgo era concreto:
  `simular` se usa en demo desde el primer día, así que agregarle
  `--env-file .env.real` por costumbre alcanzaba. Medido contra una FxPro real
  de 500: abrió dos posiciones y cerró con *"Si operaste contra MT5 demo,
  revisalas y cerralas a mano"*.
- **El freno diario no medía contra el saldo con el que abrió el día.** Medía
  contra el equity del momento de la **primera señal**. Con la cuenta abriendo
  en 500 y bajando a 486 antes de que llegara un mensaje, tomaba 486 de
  referencia y un día que perdió 5.6% no lo frenaba un tope del 5%. Y si
  `account_equity()` lanzaba, `balance_actual` **conservaba la lectura vieja**:
  con la terminal caída mientras la cuenta bajaba, el freno comparaba contra un
  número de hace horas. *Sin dato no se rechaza nada* es correcto; seguir usando
  el dato viejo no es lo mismo que no tener dato.

**Lo que tienen en común** es de dónde salieron: no de leer el código sino de
**ejecutar el camino que nadie había ejecutado**. La suite entera corre contra
`is_live=False`. Es el mismo punto ciego de §6 —probar la unidad, no el
cableado— corrido un nivel: ahora hay un *modo* que ningún test recorría.

**Y el rescate también es una lección repetida.** Los cinco auditores murieron
por límite de uso sin reportar nada, como en la tercera ronda. Esta vez el
trabajo estaba en un tercer lugar, además de los dos de §7: **los scripts que
habían dejado en el scratchpad**. Veintiséis archivos que corrían solos y
reproducían cada hallazgo. Uno de ellos había dejado además una mutación puesta
en `cli.py` sin revertir —murió entre romper y arreglar—, así que lo primero
después de una caída es `git status`.

---

## 7. Errores de proceso que costaron tiempo

Escrito para no repetirlos.

**Heredocs de bash corrompen el código.** Tres ediciones seguidas se dañaron.
Una dejó un `\x08` literal (backspace) dentro de una expresión regular,
volviéndola imposible de satisfacer, y **ningún test lo detectaba**.
→ **Para editar código, usar la herramienta Edit o escribir un script `.py` con
Write y ejecutarlo.** Nunca heredoc con regex o escapes.

**Y volvió a pasar dos veces, con esta advertencia ya escrita acá arriba.**
Las dos veces el heredoc convirtió el `\n` de un f-string en un salto de línea
real y rompió el archivo (`SyntaxError: unterminated f-string`); las dos veces
hubo que revertir con `git checkout --` y rehacer la edición con Edit.
→ La regla no alcanza escrita: **si el texto que vas a insertar tiene una barra
invertida, comillas o llaves, no pasa por un heredoc.** Y si el entorno te
empuja a usar bash igual, el heredoc va **entrecomillado** (`<<'FIN'`) y con el
`assert viejo in t` adentro. Los scripts del scratchpad son el ejemplo.

**`str.replace()` falla en silencio.** Un reemplazo cuyo ancla no coincide
devuelve el texto intacto sin error. Así se perdió el cableado del control por
Telegram, y yo lo di por hecho en un commit.
→ **Todo script de parcheo debe hacer `assert viejo in t` antes de reemplazar.**
Los scripts en el scratchpad ya lo hacen.

**"Sin votos" no es lo mismo que "refutado".** Una revisión en paralelo contó
los hallazgos que ningún verificador había podido mirar como *descartados*, y
reportó *"0 confirmados, 14 descartados"* cuando la verdad era *"14 sin
verificar"*. Exactamente al revés, y con cara de tranquilizador.
→ **Un resultado agregado tiene que distinguir tres estados: confirmado,
refutado y sin verificar.** Y si una etapa entera no corrió, decirlo arriba de
todo.

**Un agente que muere no necesariamente perdió su trabajo.** Los cinco
revisores de la tercera ronda murieron por límite de uso sin reportar nada, y
los cuatro bugs que habían encontrado se recuperaron enteros de los `git
worktree` que dejaron: los tests que escribieron seguían ahí, y correrlos
mostraba qué habían probado.
→ Antes de dar por perdida una revisión: `git worktree list`.

**Y pasó de nuevo el 2026-09-08: 23 de 32 agentes murieron por límite de uso.**
Esa vez el rescate fue por otro lado, porque no habían escrito tests: el
`journal.jsonl` del workflow guarda **una línea por agente terminado con su
resultado completo**. Tres de los cinco verificadores habían alcanzado a
reportar 26 hallazgos antes de que se cayera todo; lo que faltaba eran los
refutadores. Se leyó el journal, se verificaron los hallazgos a mano contra el
código, y de ahí salieron las correcciones de esta versión.
→ El segundo lugar donde mirar: `journal.jsonl` en la carpeta del workflow.
Y **una revisión a medias es un resultado, no un fracaso** — pero hay que
decir cuál mitad corrió.

**Y pasó otra vez el 2026-09-20, en la mitad de una verificación.** De las dos
mitades que revisaban los arreglos de `tct cambiar`, una terminó (y encontró 7
cosas, una grave) y la otra **murió por límite de uso semanal** sin escribir una
línea. Lo que se hizo: reportar cuál mitad corrió —arriba de todo, no en una
nota al pie— y anotar en §8 lo que quedó sin revisar, en vez de decir "revisado".
→ **Una revisión a medias no se cuenta como revisión.** Decí qué mitad corrió,
qué quedó sin mirar, y dejalo escrito donde se retoma el proyecto.

**Verificar imports no es verificar comportamiento.** `import tct.cli` pasaba
con el control desconectado.
→ Verificar el efecto, no que el módulo cargue.

**Un test verde puede estar pasando por el motivo equivocado.** Los primeros
tests del `10025` pasaban... porque el MT5 falso de `tests/fake_mt5.py`
devolvía `DONE` siempre, así que el caso que decían cubrir **nunca ocurría**.
Verdes, inútiles, y peor que no tenerlos: daban por probado justo lo que no se
había probado. Se descubrió rompiendo el arreglo a propósito y viendo que solo
**un** test se ponía en rojo cuando tenían que ser varios. Con el falso
enseñado a devolver `NO_CHANGES`, la misma mutación puso cuatro.
→ **Un test nuevo no está listo hasta que lo viste fallar.** Rompé el arreglo,
mirá cuántos se ponen en rojo, y si son menos de los que escribiste, alguno no
está probando nada.

**Y la herramienta que mide las mutaciones también puede mentir.** El
2026-09-15, verificando las dos llaves del dinero real, tres mutaciones dieron
**0 en rojo**: parecía que los tests no protegían nada. Era el contador. Se le
había pasado `-rs` a pytest para ver los salteados, y `-r` **reemplaza** el
resumen por defecto: las líneas `FAILED` desaparecen de la salida, y un
contador que las busca ve cero aunque todo falle. Repetido sin `-rs`, las
mismas mutaciones dieron 3, 1 y 1.
→ **Al medir mutaciones, contá también el código de salida de pytest**, que no
depende del formato. Y si una mutación da 0, desconfiá primero de la medición
y después de los tests.

**Una aserción con `in` puede pasar por PREFIJO, y el test queda verde por el
motivo equivocado.** Escribiendo `tct cambiar`, un test comprobaba que el error
nombrara el archivo real (`f"--env-file {ruta}" in mensaje`) y no el temporal…
que se llama `{ruta}.tmp`, o sea que contiene el texto buscado. El test pasaba
igual con el bug puesto, y lo delató una mutación que sobrevivió.
→ Cuando lo que se compara es un nombre de archivo o un prefijo, **afirmá
también lo que NO tiene que estar** (`".tmp" not in mensaje`), o compará la
línea entera.

**Y la versión más traicionera: pytest le pone al directorio temporal el NOMBRE
DEL TEST.** Un test llamado `test_una_plantilla_no_se_toca` corre en
`...\test_una_plantilla_no_se_toca0\`, esa ruta sale en el mensaje de error, y
un `assert "plantilla" in motivo` pasa **sin que el código diga la palabra**.
También lo encontró una mutación que sobrevivía: se apagó el chequeo de las
plantillas y el test siguió verde.
→ Afirmá **la frase**, no la palabra (`"es una plantilla" in motivo`), sobre
todo si la palabra está en el nombre del test o en el del archivo de prueba.

**Un test nuevo puede chocar con el valor que ya estaba, y eso es un dato.**
Un test del arreglo de `tct cambiar` pedía escribir 2 donde el archivo de
prueba ya tenía 20; el "20" que el bug generaba coincidía con el original, el
texto no cambiaba y el comando cortaba por "no había nada que cambiar". No era
un test mal escrito: mostraba que la decisión estaba tomada mirando el TEXTO en
vez de lo PEDIDO. Se arregló el código, no el test.
→ Si un test nuevo falla por una coincidencia con los datos de prueba,
preguntate primero si el código no está mirando la cosa equivocada.

**Caché de bytecode.** Una vez `inspect.getsource` mostró el código nuevo
mientras corría el viejo. Si algo no tiene sentido, limpiar `__pycache__`.

**Y el primo hermano: `python -m tct` desde un worktree corre el repo
PRINCIPAL.** El `.venv` está instalado en modo editable apuntando al checkout
de siempre, así que un `tct check` lanzado desde `.claude/worktrees/...` no
ejecuta el código que acabás de editar. Pasó verificando el arreglo de las
credenciales: `tct check` seguía dando *"[OK] Modo LIVE"* con la plantilla
vacía mientras `load_settings` —importado directo— ya la rechazaba.
→ Para probar el código de un worktree:
`PYTHONPATH=<worktree>/src python -m tct ...`. Y si un arreglo "no tiene
efecto", verificá **qué copia estás corriendo** antes de tocar nada.

**Y en Git Bash, `PYTHONPATH="C:/a:C:/b"` tampoco apunta al worktree.** El
separador de Windows es `;`, y Git Bash solo traduce la lista si las rutas
están en forma `/c/...` —como `$PWD`—; con `C:/...` el `:` de la letra de
unidad la rompe, y Python cae en silencio en la copia del repo principal. Lo
encontró un agente de revisión en su primera corrida. → Usar `$PWD`, o
`sys.path.insert` dentro del script, y **verificar con `tct.__file__`** qué
copia corre.

**La herramienta de edición escribe el CARÁCTER REAL de una secuencia unicode.**
Si el texto a insertar dice `"\ufeff"` o `"\u2028"`, en el archivo no queda esa
secuencia: queda el carácter mismo, que es invisible. Pasó el 19/09 escribiendo
la clave de arranque: tres BOM en `clave.py` y cuatro caracteres invisibles en
un test. El código andaba igual —los dos significan lo mismo adentro de un
string—, así que ningún test lo iba a detectar; se descubrió porque una
mutación no encontraba su ancla. Es la misma familia que el tabulador escondido
en `MT5_PATH` (§5) y el `\x08` dentro de un regex. → Después de insertar texto
con escapes unicode, escanear:

```
python -c "import pathlib; r={0xFEFF,0x2028,0x2029,0x200B,0x0B,0x0C,0x08}; [print(p,n) for p in pathlib.Path('src').rglob('*.py') for n,l in enumerate(p.read_text(encoding='utf-8').splitlines(),1) if any(ord(c) in r for c in l)]"
```

y reemplazar lo que aparezca por la secuencia escrita, armándola con `chr(92)`
para que ningún shell la vuelva a convertir.

**Y volvió a pasar escribiendo ESTE párrafo**: las dos secuencias de ejemplo de
arriba se convirtieron en los caracteres reales adentro del documento, y una de
ellas partía la línea en dos al leerla. Igual que con el tabulador de §5, que se
metió en el documento mientras se documentaba. La regla no alcanza escrita:
**el escaneo va después de cada edición con escapes, también en los `.md`.**

**El `$?` después de un pipe es del último comando del pipe.** `... | tail -3;
echo "exit: $?"` informa el código de `tail`, que es siempre 0. Da la misma
clase de mentira tranquilizadora que el `-rs` de §7: parece que pasó y no se
midió nada. → `${PIPESTATUS[0]}`.

---

## 8. Qué falta

Ordenado por lo que más importa antes de dinero real.

1. **Juntar resultados y comparar los dos informes.** Es lo único que hoy
   bloquea una decisión de verdad, y ya no falta código:

   ```
   tct informe --horas 336 --con-resultados
   tct informe --horas 336 --con-resultados --env-file .env.segunda
   ```

   **La pregunta cambió el 18/09**: ya no es "¿rinden los tres TP?" —se dio de
   baja, ver §2— sino **"¿le conviene el filtro de entrada tarde de 0.05?"**.
   En el informe de FxPro, las salteadas por el filtro salen en *"POR QUE NO SE
   OPERARON"* como *"La entrada estaba lejos del precio real del mercado"*;
   cada una se busca en el de MetaQuotes, que no tiene filtro, y se ve cómo
   terminó. Con eso se decide el número de la real. **Correr el informe una
   vez no alcanza: son unas 3 señales por día**, y en los 15 medidos el filtro
   saltea 2 (13%, pero con esa muestra puede ser de 4% a 38%).
2. **Repetir contra FxPro lo que ya funcionó contra MetaQuotes-Demo.** ✅
   **Hecho el 2026-09-11.** `tct probar --operar --env-file .env.segunda` abrió
   `GOLD` en 4345.74 (ticket 330645574), movió el stop, lo volvió a mover al
   mismo precio —el `10025`, que cada bróker puede contestar distinto— y cerró.
   El *filling mode* de FxPro es compatible.
3. **Terminar el paso a la cuenta real de FxPro.** El código está; falta que
   el usuario fondee. Los pasos y lo que hay que corregir en su `.env.real`
   (que salió de la plantilla vieja) están en **§2, "Estado al 2026-09-22"**.

   Y lo de siempre, que es fácil de olvidar justo cuando más importa: las
   protecciones de la demo **no** se heredan a la real. `.env.real.example`
   trae los valores decididos (5%, 10 señales), pero su `.env.real` es anterior.
4. **Punto como separador de miles.** `"DAX SELL 18.500"` → 18.5. Los tres
   números escalan juntos, así que la geometría no lo nota. El contraste con
   el mercado ahora lo ataja *si el bróker cotiza ese símbolo*, pero eso es una
   red debajo del error, no el arreglo del parser.
5. **`ollama.py`: la guarda antialucinaciones tiene dos fallas.** El `0*` de
   `_aparece_en_texto` deja pasar prefijos (`3950` valida contra `39,500`), y
   rechaza números legítimos con separador de miles (el prompt le pide al
   modelo que copie las comas, y después el parseo se rompe con ellas).
6. **En la gestión solo se ataja el error de ESCALA, no el sutil.** Un
   `MOVER SL A 4438` leído como `4338` pasa: está a 2% del mercado, que es un
   stop perfectamente plausible. Distinguirlo de un stop ancho legítimo no se
   puede sin saber la intención del mensaje, así que probablemente no tenga
   arreglo por este lado. Lo que sí queda: un `MOVE_SL` sin símbolo sigue
   aplicando a **todas** las posiciones cuya escala coincida —si el canal opera
   oro y otro instrumento de precio parecido, el filtro no los separa.
7. **Órdenes pendientes no se pueden cancelar.** Solo se usa `positions_get()`.
8. **El `_turno` del motor se sostiene durante la llamada a la IA.** Con
   `OLLAMA_TIMEOUT_SECONDS=45`, un mensaje que va a la IA puede tener a los
   siguientes esperando hasta 45 segundos. **Los mensajes no se pierden** —la
   consulta corre en `asyncio.to_thread` y Telethon los sigue recibiendo—, se
   encolan. Con 3 señales por día es teórico. Soltar el lock durante la
   consulta es tentador y **no hay que hacerlo sin antes escribir los tests
   que reproduzcan la carrera** que el lock evita: el orden entre una apertura
   y su `MOVER SL` no es opcional.
9. **Calibrar los dos límites del contraste con el mercado.** ✅ a medias: con
   el mercado abierto, las entradas reales del canal midieron **0.02% a 0.07%**
   contra un límite de 0.5%. Hay diez veces de margen. Apretarlo es posible,
   pero mientras el canal siga scalpeando oro no cambia nada.

### Lo que la auditoría del camino real dejó SIN arreglar

Confirmados ejecutando el 2026-09-15, ninguno arreglado todavía. Van en orden
de cuánto importan con la cuenta real andando:

10. **Una orden PENDIENTE viva se borra del estado como "se cerró sola".**
    `posicion_existe()` solo consulta `positions_get()`, y una pendiente vive en
    `orders_get()`: la reconciliación de §9 la lee como ausente, la saca del
    registro y avisa *"se cerraron solas en el broker"*. La orden **sigue viva**
    y puede dispararse en cualquier momento, abriendo una posición real que el
    bot no gestiona (sin breakeven, sin parcial) y que no cuenta para
    `MAX_OPEN_TRADES`. Medido: el bot quedó con 2 posiciones en el estado y el
    bróker con 2 posiciones **más una pendiente** que nadie miraba. Hoy no
    dispara porque este canal manda órdenes a mercado —hace falta que escriba
    `BUY LIMIT` o `SELL STOP`—, pero es peor que el punto 7 de esta lista: no es
    que no se puedan cancelar, es que el bot cree que ya no existen. El arreglo
    es chico: preguntar también por `orders_get(ticket=...)` antes de concluir
    que no está.
11. **`ENABLE_TELEGRAM_CONTROL=false` con dinero real arranca igual, y ahora
    es lo que el usuario quiere.** La guarda de §9 vive DENTRO de
    `if enable_telegram_control:`, así que con el control apagado el bloque
    entero se salteaba y no se imprimía una línea: una instancia real sin freno
    remoto arrancaba igual que una con freno. Arrancar es lo pedido (§2), así
    que **no se bloquea**; lo que se agregó es que lo diga al arrancar
    (`_aviso_sin_freno_remoto`). Queda a propósito: con `false` no hay `/pausa`
    desde el teléfono y se para cerrando la ventana.
12. **Cruzando la medianoche con el bróker caído, la referencia de ayer queda
    pegada.** La primera señal del día nuevo no puede leer el equity, así que
    `day_start_balance` se queda con el de ayer; cuando el bróker vuelve, un día
    que no perdió nada puede aparecer como si hubiera perdido. Frena de más, que
    es el lado barato, pero deja un día muerto y solo se ve por el aviso de
    señal rechazada.
13. **El candado se ata a `state.json`, no a la carpeta.** Dos `.env` con la
    misma `DATA_DIR` y distinto `STATE_PATH` **arrancan los dos** y comparten
    `events.jsonl` y `paper_trades.jsonl`. Y nada vigila la terminal: dos
    instancias con el mismo `MT5_PATH` arrancan las dos sin que nadie avise
    —hay un `[AVISO]` en `tct check` que lo describe, pero no frena—. Ver la
    corrección de §9.
14. **Roster desparejo: `/pausa real` pausa también la demo.** Si el `.env` de
    siempre queda en `INSTANCE_NAMES=demo,fxpro` y la real declara `demo,real`,
    la demo no reconoce "real" como instancia y lo lee como **motivo**, así que
    se pausa con motivo `real`. Verificado. `/cerrar` está sano en los dos
    rosters —el peor bug del proyecto sigue arreglado, probado con roster
    correcto y desparejo—, porque `cerrar` sí tiene vocabulario cerrado y
    contesta *"No entendí 'real'"*. La asimetría entre los dos comandos es lo
    que conviene mirar si algún día se toca `control.py`.
15. **`_ensure_demo` se saltea `account.trade_allowed` cuando `is_live`.** El
    atajo `if is_live: return True` está antes del chequeo. Con una cuenta real
    que el bróker tiene deshabilitada, el bot arranca y las órdenes fallan una
    por una en vez de decirlo al inicio. `connect()` sí mira el
    `trade_allowed` de la *terminal*, que es el caso común.

23. **`config.py` acepta números que apagan protecciones, y no lo dice.**
    `MAX_DAILY_LOSS_PCT=-5`, `nan` o `inf` dejan el freno diario APAGADO
    (`risk.py` lo mira con `<= 0`) mientras el arranque imprime *"Tope perdida
    dia: -5.0%"*; `MAX_LOT=nan` deja pasar cualquier lote, porque
    `volume > max_lot` nunca es verdad. Salió de la revisión de `tct cambiar`,
    que ahora **no deja escribirlos** (§5), así que para que esto muerda hay
    que editar el `.env` a mano. El arreglo de fondo es que `load_settings`
    exija un número finito y no negativo en los límites; no se hizo todavía
    porque toca el camino de arranque de los dos bots que están operando.

24. **El sufijo de una letra no distingue una cripto de un sufijo de bróker.**
    `elegir_nombre_de_simbolo` acepta `EURUSDT` como si fuera `EURUSD`: la regla
    del "sufijo corto" deja pasar cualquier agregado de 1 o 2 caracteres, que es
    exactamente la forma de `XAUUSDm` o `XAUUSD.r` (el mismo instrumento con el
    sufijo del bróker) y también de `EURUSDT` (otra cosa: la cripto contra
    USDT). **El comentario del código decía que lo evitaba y no era cierto**;
    salió de escribirle un test a esa función al sacarla afuera. Hoy no muerde,
    porque el nombre exacto gana primero y un bróker que ofrece `EURUSDT`
    ofrece `EURUSD`; mordería en un bróker que solo tenga la cripto. Hay un
    test que fija el comportamiento actual, así que el día que se toque la
    regla se va a ver qué cambia.

### Del parser: lo que se midió el 2026-09-16 y NO se tocó

Tres variaciones de formato que el parser lee mal. **Las tres terminan en señal
RECHAZADA con aviso**, no en una operación mala: es §12 funcionando —un mensaje
que no se entiende es barato—. Se anotan porque cuestan señales, no plata:

16. **`TP1:4436` sin espacio pierde TODOS los TP y el SL.** Devuelve
    `TPs=[] SL=None`, y `REQUIRE_STOP_LOSS` la rechaza. Con espacio o sin dos
    puntos funciona bien; el único formato que falla es `etiqueta:numero` pegado.
17. **Cualquier número delante del `DEAL |` se lleva puesta la entrada.**
    *"Señal 2 de hoy. DEAL | GOLD BUY XAUUSD 4438…"* → entrada **2.0**. Lo
    atajan dos guardas a la vez: la geometría (*"BUY con SL 4430 por encima de
    la entrada 2.0"*) y el contraste con el mercado (100% de distancia contra un
    límite de 0.3%). Es exactamente el error de lectura para el que se escribió
    esa red.
18. **Una señal que escribe `Take Profit` en vez de `TP` se descarta como si
    fuera un recap**, por el `PROFITS?` de `_RESULTADO_RE`. Y al ser descarte
    *deliberado* **no se le pregunta a la IA**: desaparece sin dejar rastro.
    **Se decidió no tocarlo**, y el motivo es §12: `_RESULTADO_RE` es el filtro
    más importante del parser, y sacarle `PROFIT` deja pasar los recaps cuya
    única marca sea esa palabra. Perder una señal es más barato que abrir una
    operación que nadie pidió. Hoy no muerde porque el canal escribe `TP1:`. Si
    algún día cambia el formato, esto es lo primero a mirar.
19. **La palabra `limit` o `stop` suelta ANTES del lado convierte una orden a
    mercado en PENDIENTE.** *"Atención: hay un limit importante en 4450. GOLD
    BUY XAUUSD 4432…"* → `OrderType.LIMIT`. Encadenado con el punto 10 —una
    pendiente que el bot borra del estado creyendo que se cerró sola— es el
    único camino por el que este canal podría dejar una orden viva sin gestión.
    Requiere que el canal escriba esa palabra en inglés y suelta; no se observó
    nunca.

### Lo que quedó sin arreglar del informe y de la gestión

20. **`--con-resultados` hace `mt5.login()`.** Construye el bróker y conecta,
    y `connect()` loguea si hay credenciales: con OTRO `.env` cuyo `MT5_PATH`
    esté vacío o apunte a la terminal de otro bot, le cambia la cuenta a esa
    terminal. Con el mismo `.env` del bot no pasa nada (loguea a la cuenta que
    ya está). Es el mismo riesgo que `tct mt5` y `simular --con-precios`;
    analizado leyendo, no ejecutado. Contradice el *"Solo lectura"* que imprime.
21. **Con `--horas` que corta un mensaje por la mitad**, la fila muestra la hora
    de la edición que quedó adentro, no la del mensaje. El resultado es correcto.
22. **Sin verificar**, de la auditoría del 2026-09-16 (agentes que murieron):
    el aviso de un cierre parcial diría "50%" cuando cerró el 100%; el cierre
    parcial sería el único handler que calla una posición reconciliada; una
    edición que corrige el SL de una señal ya abierta se ignora sin avisar;
    `/estado` y `/posiciones` mentirían tras una reconciliación; `tct check`
    daría por bueno LIVE con `ENABLE_TELEGRAM_CONTROL=false`; y la verificación
    de que la cuenta sea la del `.env` corre una sola vez, en `connect()`.

### Hallazgos sin verificar, listos para levantar

Los revisores de la tercera ronda dejaron esto reportado en sus worktrees y
**nadie lo confirmó todavía**. No están arreglados. Van con el nombre del test
que los reproduce, en `.claude/worktrees/wf_5dafb77b-b43-4/tests/`:

- **`metaapi.py` no tiene nada de la segunda ronda.** Ni el techo de `MAX_LOT`,
  ni el volumen ejecutado en el resultado de un cierre, así que el parcial sobre
  lote mínimo deja la misma fantasma que se arregló en MT5. Es el camino de
  macOS, que ya no es el destino, pero sigue existiendo.
- **`metaapi.py::_to_result` toma una respuesta que no es `dict` como ÉXITO.**
  `data = {}` → `string_code = ""` → `ok = True`. Un fallo raro del SDK se
  registraría como orden ejecutada.
- **El umbral `remaining_fraction <= 0.01` borra posiciones vivas.** Con un lote
  grande, el 1% restante puede seguir siendo volumen operable.
- **Una señal sin entrada abre con `entry=None`**, y después el breakeven no
  tiene a dónde apuntar (ver el arreglo de la tercera ronda, que solo hace que
  se avise).

### Lo que sigue sin revisión independiente

Dos intentos de revisión adversarial murieron por límite de uso, uno entero y
otro a medias. Sigue sin mirar nadie más:

- **El contraste con el mercado** (§5, commits `b622a4e` y `84a1a10`). Código
  nuevo en el camino que decide si se manda una orden, escrito y verificado por
  la misma persona. Lo que sí tiene son tests de mutación: romper el cableado
  pone 11 tests en rojo, neutralizar la regla en `risk.py` otros 8, y
  desconectar el chequeo de escala otros 6.
- **El código nuevo de `tct cambiar`, o sea los ARREGLOS de su revisión.** El
  comando sí se revisó: cuatro revisores independientes lo ejecutaron el 19/09
  y encontraron 18 cosas, todas arregladas; después una segunda vuelta volvió a
  correr cada reproducción contra el código arreglado (11 de 14 arreglos
  confirmados, y 7 hallazgos nuevos que también se arreglaron — el peor:
  editaba una copia del `.env` y decía "Listo"). Lo que **no** corrió es la otra
  mitad de esa segunda vuelta: el ataque adversarial al código que se escribió
  para arreglar, que es justo donde suelen quedar los bugs nuevos (§6, tercera
  ronda: "arreglar una familia de bugs no la cierra sola"). **Murió por límite
  de uso semanal**, sin reportar nada. Lo que sí tiene: 62 mutaciones, todas
  atajadas por algún test (el guion está en el scratchpad de ese chat), y 833
  tests en verde. Si retomás, eso es lo primero para mandar a revisar: el
  recorrido de `interpretar()`, el pedido de credenciales, el atribuidor de
  errores (`_variables_que_nombra`) y `_comentario_al_final`. Y las **dos redes**
  (`verificar_lectura` y `verificar_asignaciones`) se prueban una sin la otra a
  propósito: son redundantes en casi todo, y sin eso apagar una no ponía en rojo
  ningún test.
- **La investigación del punto como separador de miles** (punto 4 de arriba).
- **Todo lo de la cuarta ronda**: `informe.py`, `lockfile.py`, la lectura de
  desenlaces, `--esperar-mt5` y la guarda `es_descarte_deliberado`. Salió de
  mirar producción, se probó con tests de mutación —romper la elección del TP
  más cercano, o el agrupado por `message_id`, pone tests en rojo— pero **no lo
  revisó nadie más**. Lo más sensible es `es_descarte_deliberado`: quedó en el
  camino de decisión de todas las guardas de §5.

**Lo que sí se revisó el 2026-09-08** fue *esta documentación*, no el código:
cinco verificadores contrastando cada afirmación contra el código real. Dos
murieron sin arrancar (§6 y §7 quedaron **sin verificar**, no verificadas), y
de los tres que terminaron salieron las correcciones de esta versión. Las más
graves eran mías, escritas ese mismo día: la tabla de descartes de §2 le
atribuía a `_NARRATIVA_RE` tres frenadas que en realidad no hace nadie, y §5
usaba ese mismo ejemplo equivocado. **Si retomás el proyecto, §6 y §7 son las
dos secciones que nadie contrastó contra el código.**

---

## 9. Reglas que el código respeta (no romperlas)

- **Antes de evaluar una apertura, el estado se sincroniza contra el bróker.**
  Este canal no manda mensajes de cierre: las operaciones terminan solas en el
  TP o en el SL y el bróker las cierra sin avisar. Sin sincronizar, la regla de
  "ya hay una posición abierta en X" —que es buena— se mide contra una posición
  que ya no existe y rechaza la señal **siguiente** de ese instrumento. Con un
  canal que opera un solo símbolo, eso es perder casi una señal de cada dos.
  Solo un `False` del bróker saca la posición del estado: un `None` significa
  "no pude preguntar", y darla por cerrada sin saberlo la soltaría del registro
  estando viva.
- El paper trade se escribe **siempre**, y **antes** de llamar al bróker.
- El estado solo cambia si el bróker **confirmó**. Vale para los cuatro
  handlers, incluido el cierre parcial, que era el que faltaba. La única
  excepción es la reconciliación: si el bróker dice que la posición **no
  existe**, se saca del estado. No existir no es un fallo del cierre.
- Y no existir se distingue de **no poder preguntar**: un error de consulta
  nunca borra una posición.

- **El estado se escribe con lo que el bróker HIZO, no con lo que se pidió.** El
  lote que se guarda es `OrderResult.lot`, y el descuento de un cierre parcial
  se calcula con el volumen realmente cerrado. Pedir la mitad y que se cierre
  todo es normal cuando el lote mínimo del instrumento manda.
- **`MAX_LOT` se verifica sobre el volumen que sale**, en el ejecutor, no sobre
  `DEFAULT_LOT` en la configuración. Al **cerrar** no se aplica nunca: negarse a
  cerrar es peor que abrir de más.
- Una confirmación de cierre **caduca** (`VENTANA_CONFIRMACION_SEG`) y
  **cualquier** mensaje que no sea afirmativo la cancela, contestando que la
  canceló. Cualquier comando la desarma, `/cerrar` incluido.
- Un mensaje ambiguo se registra y **no** ejecuta nada.
- Se registran los rechazos **con su motivo**: es lo que permite contestar
  después "¿por qué no tomó esta señal?".
- **Con dinero real hace falta la clave de arranque, y se pide antes de todo.**
  `_exigir_clave` corre en `tct run` ANTES del candado de la carpeta y de
  conectar MetaTrader o Telegram: con la clave mal, el bot no llega a tocar
  nada. También en `probar --operar` y en `simular --ejecutar` (en demo; en real
  simular ya se niega entero). Sin consola donde escribirla, no arranca. En el
  `.env` se guarda una huella PBKDF2 con `:` como separador —python-dotenv
  expande `$`—, y una clave escrita a mano falla al cargar mandando a
  `tct clave`. Lo que queda sin cubrir, a propósito: quien edita el `.env` o el
  entorno puede sacarla (`CLAVE_DE_ARRANQUE=` vacía en el entorno le gana al
  `.env` en una demo; en real no, porque ahí sin clave no arranca).
- Dinero real requiere **dos** llaves: `TRADING_MODE=LIVE` **y**
  `ALLOW_LIVE_TRADING=true`. La barrera de "solo demo" vive en el ejecutor, no
  en la configuración. **Y tienen que ser dos en las DOS direcciones:** hasta
  la v1.3.0 solo se validaba LIVE sin ALLOW. Con `TRADING_MODE=AUTO`, las
  credenciales de una cuenta real y `ALLOW_LIVE_TRADING=true`, AUTO resolvía a
  modo demo y el ejecutor salteaba el chequeo de cuenta demo porque miraba solo
  la segunda llave: **el bot operaba plata real creyendo que era demo**, sin
  cartel, sin `*** REAL ***` y sin la guarda de control por Telegram (todo eso
  mira `is_live`). Se encontró el 2026-09-15, justo antes de que el usuario
  pasara FxPro a real por ese mismo camino. Ahora `config.py` rechaza ALLOW
  sin LIVE, y `_ensure_demo` (MT5 y MetaApi) exige `is_live`.
- Si el control por Telegram no se puede activar y la instancia es real, el bot
  **no arranca**.
- La pausa **persiste**: un reinicio no reanuda solo.
- **Sin dato no se inventa un rechazo.** Vale para el equity (freno diario) y
  para la cotización (contraste con el mercado): si el bróker no responde, esa
  capa no opina y la señal sigue su curso. Un bróker lento no puede dejar al
  bot sin operar.
- **Una señal puede abrir varias posiciones, pero sigue siendo una señal.** El
  cupo diario (`MAX_SIGNALS_PER_DAY`) se descuenta **una vez**, no una por
  posición: tres posiciones persiguiendo los tres TP de un mismo mensaje son un
  solo mensaje. Y el registro escribe **un** evento `aceptada` por señal, con
  todos los tickets adentro en `orders`: escribir tres haría que un día de 4
  señales se informara como 12, que es el bug de contar eventos en vez de
  mensajes (§6) volviendo por otra puerta.
- **`MAX_OPEN_TRADES` se recorta al abrir, no solo al evaluar.** `evaluate_open`
  mira si entra UNA posición; si quedaba un solo lugar libre y la señal quiere
  abrir tres, el techo se cruzaría igual. `_objetivos_de_apertura` lo recorta.
- **No se abren más posiciones que objetivos tenga la señal.** Una posición sin
  TP propio no persigue nada: solo duplica exposición.
- **Lo que el bot deja dicho nunca puede cambiar lo que el bot HACE.**
  `_avisar` escribe en el log y nada más. Y el control (`/pausa`, `/cerrar`)
  entra por la sesión de Telethon (`control.py`), un camino aparte: cuando se
  sacó el sistema de avisos, el control quedó intacto porque no compartían una
  sola línea de código.
- **El cupo del día se descuenta cuando el bróker CONFIRMA, no cuando la señal
  se acepta.** Si no, una señal que el bróker no puede operar —un símbolo que
  no cotiza, la cuenta desconectada— igual se come un lugar de
  `MAX_SIGNALS_PER_DAY`. Con BTCUSD en la lista y un bróker sin cripto, eso
  vaciaba el cupo sin haber operado nada.
- **La IA no puede revertir un descarte deliberado.** Solo se la consulta
  cuando el parser **no entendió**; lo que el parser descartó a propósito
  (crónica, hipotético, resultado) no llega a la IA. Ver §5.
- **Leer cómo terminó una operación no toca nada.** Solo `history_deals_get()`,
  solo cuando alguien pide el informe, nunca en el camino de una señal.
- **Dos instancias no comparten `state.json`.** El lock es del sistema
  operativo (`msvcrt.locking` / `fcntl.flock`), así que se libera solo si el
  proceso muere: un corte de luz no deja un candado trabado. **Y se ata al
  `state.json`, no a la carpeta** —decirlo mal es fácil y engaña—: dos `.env`
  con la misma `DATA_DIR` y distinto `STATE_PATH` arrancan los dos y se pisan
  `events.jsonl` y `paper_trades.jsonl`. Tampoco vigila la terminal ni la
  sesión de Telethon. Verificado con los cuatro casos.
- **Con dinero real, las credenciales de MT5 son obligatorias, y la cuenta a la
  que se LLEGA tiene que ser la del `.env`.** Son las dos mitades del mismo
  agujero (§6, sexta ronda): `connect()` solo hace `login()` con las tres
  credenciales puestas, así que sin ellas opera la cuenta que la terminal tenga
  cargada. Ahora `LIVE` exige `MT5_LOGIN`/`MT5_PASSWORD`/`MT5_SERVER`, y
  `connect()` aborta si `account.login` no es el del `.env`. **Esa segunda
  verificación no es solo de dinero real**: corre siempre que haya `MT5_LOGIN`,
  porque las dos instancias demo también pueden terminar cada una en la cuenta
  de la otra.
- **`tct simular --ejecutar` no toca una cuenta real.** Reproduce mensajes
  viejos: con `is_live` ni siquiera se construye el bróker. Lo que sí se puede
  contra la real es `simular --con-precios` (no manda una orden) y
  `probar --operar` (una posición mínima, abierta y cerrada).
- **La referencia del freno diario se toma al ARRANCAR**, no con la primera
  señal, que es la diferencia entre *"el saldo con el que abrió el día"* y *"el
  saldo que había cuando llegó el primer mensaje"*. Y si no se puede leer el
  equity, `balance_actual` queda en `None`: sin dato no se rechaza nada, pero
  **tampoco se sigue usando el dato viejo**, que es otra forma de mentir.
- `tct simular` **sin** `--ejecutar` no manda una sola orden, ni siquiera con
  `--con-precios`: ahí el bróker se conecta únicamente para leer cotizaciones.
  `tct informe` no manda ninguna nunca, ni con `--con-resultados`.

---

## 10. Cómo trabajar con este usuario

- Escribe en español rioplatense. Respondele igual.
- No programa. Los mensajes de error tienen que decir **qué hacer**, no solo
  qué falló.
- Está probando en una PC distinta a la de desarrollo. **Nada de lo que hagas
  localmente afecta esa máquina**: todo viaja por GitHub.
- Cuando reporte algo raro, **pedile la salida textual** antes de teorizar.
  `tct simular` fue construido para eso y ya encontró dos bugs reales, y
  `tct informe` contestó el *"hubo nueve señales y leyó cuatro"* de §2 en un
  solo comando. **Si el número que reporta no cierra, el primer paso es
  `tct informe --horas 24`.** Teorizar antes de mirarlo es cómo se pierde
  una tarde buscando un bug que no existe.
- Cuando le tengas que dictar un comando, acordate de
  `scripts\consola.bat`: la ruta larga del `.venv` no se le queda pegada y ya
  le costó seis veces el mismo error.
- **Nadie mira la consola todo el tiempo, y el bot no le escribe** (los avisos
  por Telegram se sacaron a pedido suyo). Eso cambia el estándar de los
  mensajes: algo que falla en silencio no se descubre a los cinco minutos, se
  descubre cuando nota que faltan operaciones. Por eso lo que el bot tiene que
  decir va al log como WARNING, por eso el corte de conexión queda como ERROR,
  y por eso el arranque imprime la configuración que va a usar.
- **Para cambiarle un valor del `.env`, no le dictes líneas para el Bloc de
  notas: dale un `tct cambiar`.** Lo pidió él el 19/09 (*"para eso no hay un
  comando que se pueda poner en la consola para cambiarlo solo?"*). Una sola
  línea para copiar, con todos los cambios de un archivo:
  `tct cambiar --env-file .env.segunda MAX_OPEN_TRADES=2 MAX_DAILY_LOSS_PCT=5`.
  Lo que imprime —cada variable con antes → después— es lo que reemplaza al
  "ya": pedile que te lo pegue. Y después, igual, que reinicie el bot.
- **Para saber qué tiene configurado, no preguntes: pedile que lo muestre.** En
  la ventana de `consola.bat`, `dir /b .env*` lista qué archivos existen, y
  esto muestra las opciones que importan **sin ninguna contraseña**:

  ```
  findstr /b "TRADING_MODE ALLOW_LIVE INSTANCE_NAME INSTANCE_NAMES DEFAULT_LOT MAX_LOT POSITIONS_PER_SIGNAL MAX_POSITIONS MAX_OPEN MAX_SIGNALS MAX_DAILY MAX_SPREAD ALLOWED_SYMBOLS DATA_DIR" .env .env.segunda .env.real
  ```

  El 19/09 eso deshizo una confusión que llevaba varios mensajes: él decía que
  `.env.segunda` "no lo puse" y existía; y existía un `.env.real` que nadie
  sabía que había creado. Confunde los nombres de los archivos entre sí.
- **"Ya" significa "lo hice", no "verificado".** Dos veces dijo "ya" y el bot
  seguía con la configuración vieja: había editado el `.env` pero no había
  reiniciado. El `.env` se lee UNA vez, al arrancar. Después de cualquier
  cambio, pedile que mire las líneas que imprime el bot al arrancar.
- Contesta corto, a veces con una palabra. Respondele al punto.
- Hay una guía web publicada como Artifact que espeja `docs/SETUP_WINDOWS.md`.
  Si cambia algo de la instalación, hay que actualizar las dos.

---

## 11. Relación con `tradingalertaIA`

Otro repo del mismo usuario (genera sus propias señales desde datos públicos;
no copia a nadie). De ahí se reutilizó: la técnica del marcador `sys_platform`,
la arquitectura *soft-fail*, la negociación de *filling mode* (retcode 10030),
la normalización de volumen al paso del bróker, la validación de cuenta demo, y
el partido de mensajes de Telegram en 4096 caracteres.

**No** estaba ahí: leer un grupo ajeno con Telethon, el parser de señales de
terceros, ni los eventos de gestión.

---

## 12. Filosofía

Simple al principio, crecer por capas. Comentarios que expliquen **por qué**,
no qué. Y lo que este proyecto enseñó a la fuerza:

> Un mensaje que no se entiende es barato: se descarta o va a la IA.
> Uno que se entiende **al revés** abre una operación que nadie pidió.

Perderse una señal cuesta poco. Operar una equivocada, no.
