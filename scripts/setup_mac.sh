#!/usr/bin/env bash
#
# Instalador para macOS. Deja el sistema listo en un solo comando:
#
#     bash scripts/setup_mac.sh
#
# Crea un entorno virtual, instala las dependencias, prepara el .env y corre
# el diagnostico. No toca nada fuera de esta carpeta.

set -euo pipefail

# Colores solo si la salida es una terminal (si se redirige a un archivo, no
# ensucia con codigos de escape).
if [ -t 1 ]; then
    BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; OFF=$'\033[0m'
else
    BOLD=""; GREEN=""; YELLOW=""; RED=""; OFF=""
fi

info()  { echo "${GREEN}==>${OFF} $*"; }
warn()  { echo "${YELLOW}!!${OFF}  $*"; }
error() { echo "${RED}ERROR:${OFF} $*" >&2; }

# Ubicarse en la raiz del proyecto, sin importar desde donde se invoque.
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo
echo "${BOLD}==========================================================${OFF}"
echo "${BOLD}  Telegram Copy Trading - instalacion para macOS${OFF}"
echo "${BOLD}==========================================================${OFF}"
echo "Carpeta: $PROJECT_DIR"
echo

# ---------------------------------------------------------------------------
# 1) Python 3.10 o superior
# ---------------------------------------------------------------------------
# macOS trae Python 3.9, que es demasiado viejo para la sintaxis `X | None`
# que usa el proyecto. Se busca uno mas nuevo antes de rendirse.
info "Buscando Python 3.10 o superior..."
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    error "No se encontro Python 3.10 o superior."
    echo
    echo "  macOS trae Python 3.9, que no alcanza. Instalá uno nuevo con Homebrew:"
    echo
    echo "      /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "      brew install python@3.12"
    echo
    echo "  Y despues volvé a correr este script."
    exit 1
fi
info "Usando $($PYTHON --version) ($(command -v "$PYTHON"))"

# ---------------------------------------------------------------------------
# 2) Entorno virtual
# ---------------------------------------------------------------------------
# Se aisla en .venv para no ensuciar el Python del sistema (macOS lo protege
# y pip fallaria con "externally-managed-environment").
if [ -d ".venv" ]; then
    info "El entorno virtual .venv ya existe, se reutiliza."
else
    info "Creando entorno virtual en .venv ..."
    "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
info "Entorno virtual activo."

# ---------------------------------------------------------------------------
# 3) Dependencias
# ---------------------------------------------------------------------------
info "Actualizando pip..."
python -m pip install --quiet --upgrade pip

# Una sola instalacion, sin preguntas. Incluye el puente MetaApi aunque todavia
# no se use: asi pasar a MT5 demo mas adelante es completar el .env y nada mas.
# En macOS, MetaTrader5 se saltea solo gracias al marcador sys_platform del
# requirements.txt. Si esto falla con "Could not find a version that satisfies
# the requirement MetaTrader5", ese marcador se rompio.
info "Instalando todas las dependencias (puede tardar unos minutos)..."
python -m pip install --quiet -r requirements-dev.txt

# Motor de OCR. Es una dependencia de sistema, no de Python, asi que solo se
# puede automatizar si el usuario ya tiene Homebrew. No es bloqueante: el OCR
# viene apagado (ENABLE_OCR=false) y el resto del sistema no lo necesita.
echo
if command -v brew >/dev/null 2>&1; then
    if brew list tesseract >/dev/null 2>&1; then
        info "Tesseract (OCR) ya estaba instalado."
    else
        info "Instalando Tesseract para el OCR de imagenes..."
        if brew install tesseract >/dev/null 2>&1; then
            info "Tesseract instalado."
        else
            warn "No se pudo instalar Tesseract. El OCR queda sin motor, pero"
            warn "viene apagado por defecto, asi que no afecta a nada mas."
        fi
    fi
else
    info "Homebrew no esta instalado, se omite Tesseract (solo hace falta para"
    echo "        leer senales dentro de imagenes, que viene apagado)."
fi

# ---------------------------------------------------------------------------
# 4) Archivo .env
# ---------------------------------------------------------------------------
echo
if [ -f ".env" ]; then
    info "El archivo .env ya existe, no se toca."
else
    info "Creando .env a partir de .env.example ..."
    cp .env.example .env
    warn "Hay que EDITAR .env y completar las credenciales de Telegram."
fi

mkdir -p data logs

# ---------------------------------------------------------------------------
# 5) Verificacion
# ---------------------------------------------------------------------------
echo
info "Corriendo los tests..."
if python -m pytest -q; then
    info "Tests OK."
else
    error "Los tests fallaron. Algo quedo mal instalado."
    exit 1
fi

echo
info "Diagnostico del entorno:"
echo
python -m tct check || true

# ---------------------------------------------------------------------------
echo
echo "${BOLD}==========================================================${OFF}"
echo "${BOLD}  PROXIMOS PASOS${OFF}"
echo "${BOLD}==========================================================${OFF}"
cat <<'PASOS'

  Ya no hay que instalar nada mas. Lo unico que queda es completar el .env.

  1. Conseguir las credenciales de Telegram en https://my.telegram.org
     (seccion "API development tools") y ponerlas en el archivo .env:
         TELEGRAM_API_ID=...
         TELEGRAM_API_HASH=...

  2. Activar el entorno (hace falta en cada terminal nueva):
         source .venv/bin/activate

  3. Ver los grupos disponibles y sus IDs:
         python -m tct chats
     La primera vez pide el telefono y un codigo de verificacion.

  4. Copiar el ID del grupo de senales a TELEGRAM_SOURCE_CHATS en el .env.

  5. Verificar que este todo bien:
         python -m tct check

  6. Arrancar:
         python -m tct run

  ---------------------------------------------------------------------
  OPERAR EN TU CUENTA MT5 DEMO

  Ya esta todo instalado. El sistema arranca en TRADING_MODE=AUTO, que
  corre en papel mientras no haya credenciales de broker, y pasa solo a
  MT5 demo apenas las encuentre. Para activarlo, completa en el .env:

         METAAPI_TOKEN=...
         METAAPI_ACCOUNT_ID=...

  (se sacan de https://app.metaapi.cloud, agregando ahi tu cuenta MT5
  demo) y volve a arrancar. No hay que reinstalar ni cambiar el modo.

  Guia completa y detallada: docs/SETUP_MAC.md

PASOS
