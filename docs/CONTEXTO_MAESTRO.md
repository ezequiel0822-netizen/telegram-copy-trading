# Contexto Maestro — Telegram Copy Trading

**Documento de continuidad.** Si sos una IA retomando este proyecto en un chat
nuevo, leé esto entero antes de tocar código. Está escrito para que puedas
seguir sin repetir el trabajo ni volver a caer en las trampas que ya costaron
caras.

Actualizado: 2026-09-02 · v0.6.0 · 284 tests · sobre el commit `b622a4e`
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
- MT5 **demo** conectado (bróker FxPro), Telegram configurado, grupo elegido.
- Ollama con `llama3.2:3b` funcionando.
- **Todavía no arrancó el bot en modo automático.** Está probando con
  `tct simular`, que es lo correcto.
- La cuenta **real no está configurada**. Existe `.env.real.example` pero no
  la ha completado.

### Fricciones recurrentes que va a tener de nuevo

1. **Escribe `python -m tct` en vez de `.\.venv\Scripts\python.exe -m tct`.**
   Le pasó cinco veces. El `python` a secas usa el Python del sistema, que no
   tiene el paquete. Si reporta `No module named tct`, es esto.
2. **Bajó el proyecto como ZIP, no clonado.** Ya se convirtió a repo git, pero
   si vuelve a bajar un ZIP hay que repetir la conversión (`git init` +
   `remote add` + `fetch` + `reset --hard origin/main`). Verificado que
   conserva `.env`, `.session` y `data/`.
3. **Suele quedar en un commit viejo.** Cuando reporte un comportamiento ya
   arreglado, lo primero es pedirle `git pull` y confirmar el commit.

### Preguntas abiertas que le hice y no contestó

- ¿El canal opera **solo oro**? Importa porque `MOVER SL A 4444` no nombra
  instrumento, y sin símbolo el bot aplica el cambio a **todas** las posiciones
  abiertas.
- El mensaje textual de una señal que salió con entrada 4438 y stop 4436 (2
  puntos de stop en oro, sospechosamente ajustado).

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
ajusta volúmenes al mínimo del instrumento y sabe rechazar. Todo lo de arriba
es indetectable contra el bróker de papel. **Cualquier cambio en el volumen o
en el estado de las posiciones se prueba ahí.**

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
2. **Primera orden real contra MT5.** Todas las constantes están verificadas
   contra el paquete instalado, pero un `order_send` de verdad no. El punto
   delicado es el *filling mode*, que cada bróker acepta distinto.
   `tct probar --operar` existe para eso.
3. **Punto como separador de miles.** `"DAX SELL 18.500"` → 18.5. Los tres
   números escalan juntos, así que la geometría no lo nota. El contraste con
   el mercado ahora lo ataja *si el bróker cotiza ese símbolo*, pero eso es una
   red debajo del error, no el arreglo del parser.
4. **`ollama.py`: la guarda antialucinaciones tiene dos fallas.** El `0*` de
   `_aparece_en_texto` deja pasar prefijos (`3950` valida contra `39,500`), y
   rechaza números legítimos con separador de miles (el prompt le pide al
   modelo que copie las comas, y después el parseo se rompe con ellas).
5. **El contraste con el mercado no cubre los eventos de gestión.** Un
   `MOVER SL A 4444` no se compara contra nada: si el número está mal leído, el
   stop se mueve igual. Solo se valida la apertura. Peor con un `MOVE_SL` sin
   símbolo, que aplica el número de un instrumento a **todas** las posiciones
   abiertas —ver la pregunta abierta de §2.
6. **Dos procesos con el mismo `.env` se pisan.** No hay lockfile.
7. **Órdenes pendientes no se pueden cancelar.** Solo se usa `positions_get()`.
8. **Sin P&L de los paper trades.** Es lo que haría falta para saber si el
   grupo de señales realmente sirve. Ya hay media pieza: cada paper trade
   guarda `precio_mercado`, el precio real del instrumento en el momento de la
   señal. Falta el precio de salida.

### Lo que quedó sin revisar

Una auditoría en paralelo se quedó a mitad de camino por límite de uso. Nunca
corrieron:

- **Ninguna revisión independiente del contraste con el mercado** (§5 y el
  commit `b622a4e`). Es código nuevo en el camino que decide si se manda una
  orden, escrito y verificado por la misma persona. Lo que sí tiene son tests
  de mutación: romper el cableado pone 11 tests en rojo, y neutralizar la regla
  en `risk.py`, otros 8.
- **La investigación del punto como separador de miles** (punto 3 de arriba).

Si retomás esto, son los dos primeros lugares donde mirar.

---

## 9. Reglas que el código respeta (no romperlas)

- El paper trade se escribe **siempre**, y **antes** de llamar al bróker.
- El estado solo cambia si el bróker **confirmó**. Vale para los cuatro
  handlers, incluido el cierre parcial, que era el que faltaba.
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
