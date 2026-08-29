# Contexto Maestro - Telegram Copy Trading

Documento de continuidad: lo que hay que saber para seguir el proyecto.
Actualizado: 2026-08-29 (v0.2.0).

---

## Qué quiere el usuario

Está en un grupo de Telegram donde mandan señales de trading (take profit, stop
loss, imágenes, captions, entradas, cierres parciales y cambios). Quiere un
sistema casi autónomo que vea esos mensajes y replique las operaciones en MT5.

La prioridad **no** es dinero real. El orden es:

1. Paper trading automático.
2. Cuenta demo de MT5.
3. Recién después, y cuando el usuario lo decida, el camino a cuenta real.

Quiere capas de seguridad, pero **no** un sistema que le bloquee para siempre el
paso a real. Las protecciones deben ser **configurables, visibles y fáciles de
cambiar**.

---

## Restricción que define la arquitectura: el destino es una Mac M1

El sistema **no corre en la máquina donde se desarrolló** (Windows). El destino
es la Mac (Apple Silicon M1) del padre del usuario, y tiene que poder entregarse
como repositorio de GitHub o carpeta, para que él lo instale por terminal.

Eso cambia todo, porque:

> **El paquete `MetaTrader5` de PyPI publica únicamente wheels `win_amd64` y no
> tiene source distribution.** En una Mac `pip install MetaTrader5` no anda mal:
> no instala. Y el terminal MT5 para macOS es un envoltorio de Wine que la API
> de Python no alcanza.

Verificado contra la API de PyPI el 2026-08-29 (versión 5.0.6147: 9 wheels,
todas `win_amd64`, ningún `.tar.gz`).

**Consecuencias de diseño:**

- El `requirements.txt` lleva `MetaTrader5 ... ; sys_platform == "win32"`.
  Sin ese marcador la instalación **aborta entera** en la Mac. No sacarlo.
- La ejecución de órdenes está detrás de una interfaz (`brokers/base.py`) con
  tres implementaciones. El motor nunca importa un broker concreto.
- El camino a MT5 real desde la Mac es **MetaApi Cloud**, que hostea el terminal
  y lo expone por internet.
- Telegram, parser y paper trading corren **100% nativo** en la Mac.

---

## Decisiones tomadas con el usuario (2026-08-29)

| Tema | Decisión |
|---|---|
| MT5 en Mac | Paper-only **y** MetaApi. Ambos implementados |
| Lectura de Telegram | Telethon (sesión de usuario), no Bot API |
| Imágenes | Mezcla texto/imagen: hook de OCR preparado pero **apagado** |
| Máquina destino | Mac M1 (Apple Silicon) |

---

## Estado actual (v0.2.0)

**Hecho y con tests (76 verdes, sin red ni credenciales):**

- Parser de señales: aperturas, tipos de orden (`BUY LIMIT` / `SELL STOP` /
  `BUY NOW`), rangos de entrada, TPs múltiples, alias de símbolos, emojis,
  markdown, comas de miles, coma decimal española, mensajes editados, y eventos
  de gestión (cierre total, parcial, mover SL a BE). Descarta la charla.
- Motor completo: parser → riesgo → paper trade → broker → estado.
- Capas de riesgo, todas configurables desde el `.env`.
- Persistencia JSONL + estado atómico que sobrevive a reinicios, con
  deduplicación de mensajes.
- Broker de papel, y adaptadores MetaApi y MT5 nativo.
- CLI: `check`, `chats`, `test`, `status`, `run`.
- Instalador para macOS y documentación paso a paso.

**Escrito pero sin probar contra el servicio real** (requiere credenciales):

- `brokers/metaapi.py` — escrito contra la API de `metaapi-cloud-sdk`. El SDK
  publicado hoy es 29.1.1 y el código se escribió contra la forma 27.x; el
  primer contacto puede necesitar ajustes en los nombres de método.
- `telegram/reader.py` — la superficie de API de Telethon 1.44 sí se verificó
  (`events.NewMessage`, `events.MessageEdited`, `iter_dialogs`,
  `download_media`), pero el flujo de login real no.

---

## Qué falta

1. **Primer contacto real con Telegram.** Correr `python -m tct chats` con
   credenciales de verdad y confirmar el login. Después, `DRY_RUN=true` unos
   días contra el grupo real: es la única forma de saber cómo escribe ESE grupo.
2. **Ajustar el parser con mensajes reales.** Los casos de `tests/test_parser.py`
   son representativos, no exhaustivos. Cada mensaje que el grupo mande y el
   parser no entienda debería volverse un test nuevo.
3. **Probar MetaApi** contra una cuenta demo. Verificar los nombres de método
   del SDK 29.x y el campo `type` del `account_information`.
4. **Atar los eventos de gestión a la señal original.** Hoy un "close 50%" sin
   símbolo aplica a todas las posiciones abiertas. Telegram expone
   `reply_to_message_id` y ya se captura en `SignalEvent`: si el grupo gestiona
   respondiendo al mensaje original, se puede resolver la posición exacta.
5. **OCR**, sólo si resulta que una parte real de las señales viene en imagen.
   Medir primero con los eventos `image_skipped` del log.
6. **Seguimiento de resultados.** Hoy se registra la apertura y el cierre, pero
   no se calcula el P&L de los paper trades. Es lo que haría falta para saber si
   el grupo de señales realmente sirve.

---

## Reglas que el código respeta (no romperlas)

- Siempre se guarda el paper trade, aunque el broker esté apagado o falle.
  El paper trade se escribe **antes** de llamar al broker.
- No se opera fuera de `ALLOWED_SYMBOLS`.
- No se usa lote mayor que `MAX_LOT` (el bot ni siquiera arranca).
- Si el mensaje es ambiguo: se registra el evento y **no** se manda nada.
- Se registran también los rechazos, con su motivo. Es lo que permite después
  contestar "¿por qué el bot no tomó esta señal?".
- Dinero real requiere **dos** llaves: `TRADING_MODE=LIVE` y
  `ALLOW_LIVE_TRADING=true`. La barrera de "solo cuentas demo" vive en el
  ejecutor de órdenes, no en la configuración.

---

## Relación con `tradingalertaIA`

Es **otro producto**: genera sus propias señales desde datos públicos (Yahoo,
SEC, COT). No copia a nadie. Pero su capa de ejecución era justo lo que faltaba
acá y se reutilizó:

- La técnica del marcador `sys_platform` en `requirements.txt`.
- La arquitectura *soft-fail* (todo degrada en vez de reventar).
- De `mt5_demo_trader.py`: negociación de *filling mode* (retcode 10030),
  normalización de volumen al paso del bróker, validación de cuenta demo.
- De `mt5_symbol_map.py`: el enfoque de perfiles por bróker.
- De `telegram_notifier.py`: el partido de mensajes en 4096 chars.

**No** estaba ahí: leer un grupo ajeno con Telethon (ese repo solo usa la Bot
API para su propio bot), el parser de señales de terceros, ni los eventos de
gestión.

---

## Filosofía

Simple al principio, crecer por capas. Mantenerlo entendible, con comentarios
útiles, sin sobrecomplicar. La persona que lo va a usar no programa: los
mensajes de error tienen que decir qué hacer, no sólo qué falló.
