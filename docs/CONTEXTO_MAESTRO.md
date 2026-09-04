# Contexto Maestro — Telegram Copy Trading

**Documento de continuidad.** Si sos una IA retomando este proyecto en un chat
nuevo, leé esto entero antes de tocar código. Está escrito para que puedas
seguir sin repetir el trabajo ni volver a caer en las trampas que ya costaron
caras.

Actualizado: 2026-09-02 · v0.7.2 · 320 tests · sobre el commit `952af8b`
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

- Windows 10 configurado, `check` da **"todo listo para arrancar"**.
- **El 2026-09-04 el bot arrancó por primera vez de punta a punta.** Las cuatro
  patas conectadas a la vez: MT5, Telegram leyendo el grupo, el control por
  Telegram en Mensajes Guardados, y Ollama. Lo dejó correr medio minuto y lo
  paró; el cierre fue limpio.
- **El bróker conectado es `MetaQuotes-Demo`, NO FxPro.** Es la cuenta demo
  genérica que MetaTrader crea sola, y la eligió a propósito para probar. Sirve
  para validar la cañería —parser, motor, riesgo, control— pero **no** valida
  nada específico de FxPro: nombres de instrumentos con sufijo, lotes mínimos,
  spreads, ni el *filling mode*. Correr `tct probar` en las dos cuentas y
  comparar es lo que muestra qué cambia.
- `MT5_PATH` quedó **vacío** en su `.env`, a propósito. Tenía una ruta con un
  error de tipeo (`MetaTrade 5`, sin la "r") y vacío es más robusto: el bot se
  engancha a la terminal que esté abierta. **Efecto secundario a tener
  presente:** se conecta a la que haya, así que la cuenta con la que opera
  depende de en cuál esté logueada esa ventana.
- Ollama con `llama3.2:3b` funcionando.
- **El 2026-09-04 el bot mandó su primera orden de verdad.**
  `tct probar --operar` abrió y cerró 0.01 de XAUUSD contra MetaQuotes-Demo
  sin un solo tropiezo. Es el hito que cierra el punto 2 de §8.
- **El canal opera BTCUSD y `MetaQuotes-Demo` no tiene cripto.** Se decidió
  **dejarlo** en `ALLOWED_SYMBOLS`: las señales igual se registran como paper
  trade —que es lo que sirve para evaluar el canal— y ya no gastan cupo
  diario. Se resuelve solo cuando conecte FxPro, que sí lo opera.
- La cuenta **real no está configurada**. Existe `.env.real.example` pero no
  la ha completado.
- Tiene `MAX_DAILY_LOSS_PCT` sin poner (el arranque dice "sin tope"), y
  `MAX_OPEN_TRADES=10` / `MAX_SIGNALS_PER_DAY=10`. En demo da igual; antes de
  real, el freno diario no se deja en 0.

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
15 mensajes, 14 con texto, y **7 interpretados como señal**. El formato es
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

**Patrón: scalping de oro, 8 puntos de stop, TPs a +4 / +6 / +8.** Eso corrige
la sospecha vieja de "2 puntos de stop": son 8, y son consistentes.

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
una notificación por Telegram cada vez. Es un casi-acierto de `_NARRATIVA_RE`:
lo agarró antes de que pudiera hacer daño, no antes de hacer ruido.

### Preguntas abiertas

- **Qué son los 7 mensajes que NO se interpretaron.** Hace falta correr
  `tct simular --horas 23 --todos` para verlos. Pueden ser charla y media
  (inofensivo) o señales que se están perdiendo.

---

## 3. Arquitectura, en una pantalla

```
Telegram (Telethon, sesión de usuario)
   ↓  reader.py         descarta stickers/media, distingue texto de caption
   ↓  parser.py         reglas: rápido, gratis, determinista
   ↓  [si falla] ollama.py    IA local, SOLO avisa, nunca opera
   ↓  engine.py         orquesta; serializa con un Lock
   ↓  risk.py           todas las validaciones, cada una con su motivo
   ↑  broker.market_price()   el unico dato de afuera que entra al riesgo
                               (aperturas y tambien MOVE_SL)
   ↓  brokers/          paper | mt5_native (Windows) | metaapi (macOS)
   →  store.py          JSONL + estado atómico
```

Módulos en `src/tct/`. La CLI (`cli.py`) expone:

| Comando | Para qué |
|---|---|
| `check` | Diagnóstico. Lo primero en una máquina nueva. |
| `mt5` | Lee la cuenta MT5 abierta y dice qué poner en el `.env`. |
| `chatid` | Averigua el chat id para las notificaciones. |
| `simular` | **Reproduce los mensajes reales del grupo.** Sin `--ejecutar` no toca nada. Con `--con-precios` compara cada entrada contra el precio real de MT5 y sugiere el límite, sin operar. |
| `probar` | Verifica la cadena contra MT5. Con `--operar` abre y cierra una posición mínima. |
| `chats` / `test` / `status` / `run` | Listar grupos / probar el parser / ver estado / arrancar. |

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
| **Demo y real = dos procesos** | MT5 solo admite una cuenta por proceso: `login()` reemplaza, no agrega. Verificado contra la API. Dos `.env`, dos carpetas de datos, dos sesiones. |
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

**`control.py` — vocabulario cerrado de destinatarios.** `{demo, real, papel,
paper}`. Sin lista fija, `/pausa mercado feo` se leía como dirigido a una
instancia llamada "mercado".

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

---

## 7. Errores de proceso que costaron tiempo

Escrito para no repetirlos.

**Heredocs de bash corrompen el código.** Tres ediciones seguidas se dañaron.
Una dejó un `\x08` literal (backspace) dentro de una expresión regular,
volviéndola imposible de satisfacer, y **ningún test lo detectaba**.
→ **Para editar código, usar la herramienta Edit o escribir un script `.py` con
Write y ejecutarlo.** Nunca heredoc con regex o escapes.

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

**Verificar imports no es verificar comportamiento.** `import tct.cli` pasaba
con el control desconectado.
→ Verificar el efecto, no que el módulo cargue.

**Caché de bytecode.** Una vez `inspect.getsource` mostró el código nuevo
mientras corría el viejo. Si algo no tiene sentido, limpiar `__pycache__`.

---

## 8. Qué falta

Ordenado por lo que más importa antes de dinero real.

1. **Calibrar los dos límites del contraste con el mercado contra el grupo
   real.** El control ya existe y está conectado (ver §5), pero `0.5%` a
   mercado y `3%` en pendientes son números elegidos a mano, no medidos. Con
   el oro en 4438, `0.5%` son 22 puntos: durante una noticia eso se mueve en
   minutos, y una señal procesada tarde se rechazaría siendo buena.
   `tct simular --horas 2 --con-precios` mide las señales reales del grupo
   contra el precio de MT5 sin operar y sugiere el número. **Es lo primero que
   hay que hacer con este cambio, antes de confiar en él.**
2. **Primera orden real contra FxPro.** ✅ El `order_send` de verdad **ya
   ocurrió**: el 2026-09-04, `tct probar --operar` abrió y cerró una posición
   de 0.01 en XAUUSD contra `MetaQuotes-Demo`
   (`ticket=10356633241 precio=4483.3`), y la negociación de *filling mode*
   funcionó a la primera. La cadena completa —conectar, resolver el símbolo,
   cotizar, normalizar el volumen, `order_send`, cerrar— está probada contra
   una terminal real.
   **Lo que sigue faltando es repetirlo en FxPro**, que es donde va a operar:
   el *filling mode* es justamente lo que cada bróker acepta distinto, así que
   este resultado no se traslada.
3. **Punto como separador de miles.** `"DAX SELL 18.500"` → 18.5. Los tres
   números escalan juntos, así que la geometría no lo nota. El contraste con
   el mercado ahora lo ataja *si el bróker cotiza ese símbolo*, pero eso es una
   red debajo del error, no el arreglo del parser.
4. **`ollama.py`: la guarda antialucinaciones tiene dos fallas.** El `0*` de
   `_aparece_en_texto` deja pasar prefijos (`3950` valida contra `39,500`), y
   rechaza números legítimos con separador de miles (el prompt le pide al
   modelo que copie las comas, y después el parseo se rompe con ellas).
5. **En la gestión solo se ataja el error de ESCALA, no el sutil.** Un
   `MOVER SL A 4438` leído como `4338` pasa: está a 2% del mercado, que es un
   stop perfectamente plausible. Distinguirlo de un stop ancho legítimo no se
   puede sin saber la intención del mensaje, así que probablemente no tenga
   arreglo por este lado. Lo que sí queda: un `MOVE_SL` sin símbolo sigue
   aplicando a **todas** las posiciones cuya escala coincida —si el canal opera
   oro y otro instrumento de precio parecido, el filtro no los separa. Ver la
   pregunta abierta de §2.
6. **Dos procesos con el mismo `.env` se pisan.** No hay lockfile.
7. **Órdenes pendientes no se pueden cancelar.** Solo se usa `positions_get()`.
8. **Sin P&L de los paper trades.** Es lo que haría falta para saber si el
   grupo de señales realmente sirve. Ya hay media pieza: cada paper trade
   guarda `precio_mercado`, el precio real del instrumento en el momento de la
   señal. Falta el precio de salida.

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
- **La investigación del punto como separador de miles** (punto 3 de arriba).

---

## 9. Reglas que el código respeta (no romperlas)

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
- Dinero real requiere **dos** llaves: `TRADING_MODE=LIVE` **y**
  `ALLOW_LIVE_TRADING=true`. La barrera de "solo demo" vive en el ejecutor, no
  en la configuración.
- Si el control por Telegram no se puede activar y la instancia es real, el bot
  **no arranca**.
- La pausa **persiste**: un reinicio no reanuda solo.
- **Sin dato no se inventa un rechazo.** Vale para el equity (freno diario) y
  para la cotización (contraste con el mercado): si el bróker no responde, esa
  capa no opina y la señal sigue su curso. Un bróker lento no puede dejar al
  bot sin operar.
- `tct simular` **sin** `--ejecutar` no manda una sola orden, ni siquiera con
  `--con-precios`: ahí el bróker se conecta únicamente para leer cotizaciones.

---

## 10. Cómo trabajar con este usuario

- Escribe en español rioplatense. Respondele igual.
- No programa. Los mensajes de error tienen que decir **qué hacer**, no solo
  qué falló.
- Está probando en una PC distinta a la de desarrollo. **Nada de lo que hagas
  localmente afecta esa máquina**: todo viaja por GitHub.
- Cuando reporte algo raro, **pedile la salida textual** antes de teorizar.
  `tct simular` fue construido para eso y ya encontró dos bugs reales.
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
