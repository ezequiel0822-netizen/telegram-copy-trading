# Contexto Maestro — Telegram Copy Trading

**Documento de continuidad.** Si sos una IA retomando este proyecto en un chat
nuevo, leé esto entero antes de tocar código. Está escrito para que puedas
seguir sin repetir el trabajo ni volver a caer en las trampas que ya costaron
caras.

Actualizado: 2026-09-11 · v1.2.1 · 528 tests · el último commit que describe
es `dddfb13`, más este mismo cambio (que es el que trae la v1.2.1)
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

### La configuración de hoy

| | |
|---|---|
| Bróker | **`MetaQuotes-Demo`, NO FxPro** |
| `MT5_PATH` | **vacío**, a propósito |
| Lote / máx | 0.01 / 0.01 |
| `MAX_OPEN_TRADES` / `MAX_SIGNALS_PER_DAY` | **100 / 100** (de fábrica son 5 y 20) |
| `MAX_DAILY_LOSS_PCT` | **sin tope** |
| `MAX_SPREAD_FROM_ENTRY_PCT` | 0.5% (sin calibrar, pero con margen de sobra) |
| `OLLAMA_TIMEOUT_SECONDS` | 45 (bajado de 180) |
| `POSITIONS_PER_SIGNAL` | **3** — una posición por TP, o sea 0.03 por señal |
| `MAX_POSITIONS_PER_SYMBOL` | **0** — sin tope, para que la TP3 colgada no bloquee |
| `BREAKEVEN_USES_REAL_ENTRY` | `true` (ver §5) |

Tres cosas de esa tabla merecen atención antes de dinero real:

- **`MetaQuotes-Demo` no es FxPro.** Valida la cañería —parser, motor, riesgo,
  control— pero **nada** de lo que cambia entre brókers: nombres con sufijo,
  lotes mínimos, spreads, *filling mode*. Correr `tct probar` en las dos y
  comparar es lo que muestra la diferencia. Y **no tiene cripto**, que importa
  porque el canal sí manda señales de BTCUSD.
- **`MT5_PATH` vacío** es lo más robusto con UNA instancia: se engancha a la
  terminal que esté abierta. Con dos deja de tener respuesta correcta (§5).
  Efecto secundario: la cuenta con la que opera depende de en cuál esté
  logueada esa ventana.
- **100 / 100, sin freno diario y sin tope por instrumento** son cuatro
  protecciones prácticamente desactivadas, y `POSITIONS_PER_SIGNAL=3`
  triplica cada señal encima de eso. En demo da igual y es a propósito: el
  objetivo declarado es juntar datos. **Antes de real hay que volver a
  bajar las cuatro**, y el freno diario no se deja en 0.

### Decisiones tomadas que no hay que revisar

- **BTCUSD se queda en `ALLOWED_SYMBOLS`** aunque este bróker no lo tenga. Las
  señales se registran igual como paper trade —que es lo que sirve para
  evaluar el canal— y desde el arreglo del cupo ya no gastan lugar del día.
  Se resuelve solo cuando conecte FxPro.
- **La IA local se queda como está.** Ver §4: subirle el nivel no ayudaría.
- La cuenta **real no está configurada**. Existe `.env.real.example` sin
  completar.

### La decisión de los tres TP, ya tomada

**Se decidió abrir las tres.** El 2026-09-11, con una semana de datos reales
sobre la mesa, el usuario eligió perseguir los tres objetivos. El motivo es
recolectar datos: la cuenta es demo, así que triplicar el tamaño no cuesta
nada, y es la única forma de saber cuántas veces el precio llega al TP2 y al
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
el tope es `MAX_POSITIONS_PER_SYMBOL`, y en esta máquina está en **0** (sin
tope). Antes de dinero real hay que volver a bajarlo.

### Lo que sigue esperando datos

Ahora que los tres objetivos se mandan de verdad, lo que falta es dejar correr
una semana y mirar `tct informe --con-resultados`: cuántas llegan al TP2 y al
TP3. Recién con eso se sabe si tres posiciones rinden más que una, que es la
pregunta que originalmente motivó todo esto.

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
| `mt5` | Lee la cuenta MT5 abierta y dice qué poner en el `.env`. |
| `chatid` | Averigua el chat id para las notificaciones. |
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
que no es para ella de un motivo escrito a mano. **Nadie compara los `.env`
entre sí**: cada uno solo valida que su `INSTANCE_NAME` esté en su propio
`INSTANCE_NAMES`. Si dos declaran listas distintas, lo único que lo delata es
el roster que cada bot imprime al arrancar.

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

**`engine.py` — hay avisos que NO se pueden callar sin perder información que
no está en ningún otro lado.** `_notify(..., problema=True)` marca cuáles. Los
dos que importan:

- **El aviso de señal RECHAZADA es la única voz del freno por pérdida diaria.**
  Cuando ese freno salta, rechaza **todas** las señales hasta el día siguiente.
  Sin el aviso, un día entero frenado se ve desde el teléfono exactamente igual
  que un día sin señales. `/estado` tampoco lo muestra.
- **Una apertura que entró a medias avisa aparte, y tiene que seguir así.**
  Antes esa información viajaba adentro del `SENAL ACEPTADA`, que es un aviso
  de rutina: al callar la rutina se iba con él. Con `POSITIONS_PER_SIGNAL=3`,
  si el bróker acepta dos y rechaza una, el usuario cree perseguir tres
  objetivos y persigue dos — y **el informe tampoco lo muestra**: `fallidas` se
  guarda en el evento `aceptada` y nadie lo lee. No es un problema de plata
  (entra menos exposición, no más) sino de **dato**: las tres posiciones
  existen para medir cuántas veces el precio llega al TP2 y al TP3, y un 2 de 3
  invisible hace figurar el TP3 como "no llegó" cuando nunca se mandó.

**Y ningún test protegía la entrega de un aviso.** Los de `test_desconexion.py`
afirman sobre el TEXTO FUENTE (`inspect.getsource`), no sobre comportamiento:
se comprobó que parchear `Notifier.enabled()` para devolver `False` dejaba la
suite entera en verde. `test_nivel_de_avisos.py` son los primeros que se ponen
en rojo si los avisos dejan de salir.

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

**Caché de bytecode.** Una vez `inspect.getsource` mostró el código nuevo
mientras corría el viejo. Si algo no tiene sentido, limpiar `__pycache__`.

---

## 8. Qué falta

Ordenado por lo que más importa antes de dinero real.

1. **Juntar una semana de resultados y decidir la pregunta de los tres TP.**
   Es lo único que hoy bloquea una decisión de verdad, y ya no falta código:
   `tct informe --con-resultados` lee el historial de MT5 y clasifica cada
   operación en TP, SL, breakeven o cierre a mano. Lo que falta es **tiempo
   corriendo**. Con la proporción entre "llegó al TP1" y "murió en breakeven"
   se contesta lo de §2, y de paso se sabe si el canal sirve —que es el
   objetivo de todo el proyecto—. **Correr el informe una vez no alcanza: son
   3 señales por día.**
2. **Repetir contra FxPro lo que ya funcionó contra MetaQuotes-Demo.** La
   cadena entera —conectar, resolver el símbolo, cotizar, normalizar el
   volumen, `order_send`, cerrar— está probada contra una terminal real desde
   el 2026-09-04. Pero el *filling mode*, los sufijos de los nombres y los
   lotes mínimos son **exactamente** lo que cambia entre brókers, así que ese
   resultado no se traslada. `tct probar` en las dos cuentas y comparar.
   Además, FxPro es lo que destraba BTCUSD.
3. **Volver a bajar las protecciones antes de dinero real.** Hoy están en
   `100 / 100` y sin freno diario (§2), que para demo está bien y para real no.
   Es un cambio de `.env`, pero es fácil de olvidar justo en el momento en que
   más importa.
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
- **Callar los avisos nunca puede cambiar lo que el bot HACE.**
  `TELEGRAM_NOTIFY_LEVEL` filtra la salida y nada más: con `none` el bot abre,
  cierra y mueve stops exactamente igual. Y **no deja sin freno**: los comandos
  entran por la sesión de Telethon (`control.py:390`), que es otro canal — el
  notificador usa la Bot API con `TELEGRAM_BOT_TOKEN`. Son dos mecanismos que
  no comparten una sola línea de código.
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
- **Dos instancias no comparten carpeta de datos.** El lock es del sistema
  operativo (`msvcrt.locking` / `fcntl.flock`), así que se libera solo si el
  proceso muere: un corte de luz no deja un candado trabado.
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
- **El bot arranca solo al prender la PC, así que ya nadie mira la consola.**
  Eso cambia el estándar de los mensajes: algo que falla en silencio no se
  descubre a los cinco minutos, se descubre cuando el usuario nota que faltan
  operaciones. Por eso el corte de conexión ahora se avisa (§6) y por eso el
  arranque imprime la configuración que va a usar.
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
