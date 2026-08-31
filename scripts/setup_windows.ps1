# Instalador para Windows.
#
# No se ejecuta directo: usa instalar.bat, que lo llama saltando la politica
# de ejecucion de PowerShell (que por defecto bloquea los .ps1 descargados y
# es el primer muro con el que choca cualquiera).
#
# Nota sobre el texto: todo va sin acentos a proposito. Windows PowerShell 5.1
# lee los .ps1 como ANSI salvo que tengan BOM, y los acentos se ven rotos en
# media consola. Prefiero texto correcto y feo antes que bonito y garabateado.

$ErrorActionPreference = "Stop"

function Escribir-Titulo($texto) {
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Cyan
    Write-Host "  $texto" -ForegroundColor Cyan
    Write-Host "==========================================================" -ForegroundColor Cyan
}
function Paso($t)  { Write-Host "==> $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "!!  $t" -ForegroundColor Yellow }
function Error2($t){ Write-Host "ERROR: $t" -ForegroundColor Red }

# Ubicarse en la raiz del proyecto sin importar desde donde se invoque.
$RaizProyecto = Split-Path -Parent $PSScriptRoot
Set-Location $RaizProyecto

Escribir-Titulo "Telegram Copy Trading - instalacion para Windows"
Write-Host "Carpeta: $RaizProyecto"
Write-Host ""

# ---------------------------------------------------------------------------
# 1) Python 3.10 o superior
# ---------------------------------------------------------------------------
Paso "Buscando Python 3.10 o superior..."

function Sirve-Python($comando, $argumentos) {
    try {
        $salida = & $comando @argumentos "-c" "import sys; print(1 if sys.version_info>=(3,10) else 0)" 2>$null
        return ($LASTEXITCODE -eq 0 -and $salida -match "1")
    } catch { return $false }
}

$Python = $null
$PythonArgs = @()

# El lanzador 'py' es el camino confiable en Windows: 'python' a secas puede
# ser el alias de la Microsoft Store, que abre la tienda en vez de ejecutar
# nada y deja al usuario mirando una ventana sin entender por que.
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("-3.13", "-3.12", "-3.11", "-3.10", "-3")) {
        if (Sirve-Python "py" @($v)) { $Python = "py"; $PythonArgs = @($v); break }
    }
}
if (-not $Python) {
    foreach ($c in @("python3", "python")) {
        if ((Get-Command $c -ErrorAction SilentlyContinue) -and (Sirve-Python $c @())) {
            $Python = $c; $PythonArgs = @(); break
        }
    }
}

if (-not $Python) {
    Error2 "No se encontro Python 3.10 o superior."
    Write-Host ""
    Write-Host "  Instalalo asi (2 minutos, no hace falta la terminal):"
    Write-Host ""
    Write-Host "    1. Entra a  https://www.python.org/downloads/windows/"
    Write-Host "    2. Descarga 'Windows installer (64-bit)' de Python 3.13"
    Write-Host "    3. IMPORTANTE: al abrir el instalador, tilda abajo la casilla"
    Write-Host "       'Add python.exe to PATH' ANTES de darle a Install." -ForegroundColor Yellow
    Write-Host "       Si no la tildas, Windows no lo va a encontrar."
    Write-Host "    4. Cierra esta ventana y volve a ejecutar instalar.bat"
    Write-Host ""
    exit 1
}

$VersionPython = (& $Python @PythonArgs "--version" 2>&1)
Paso "Usando $VersionPython"

# ---------------------------------------------------------------------------
# 2) Entorno virtual
# ---------------------------------------------------------------------------
if (Test-Path ".venv") {
    Paso "El entorno virtual .venv ya existe, se reutiliza."
} else {
    Paso "Creando entorno virtual en .venv ..."
    & $Python @PythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Error2 "No se pudo crear el entorno virtual."; exit 1 }
}

$VenvPython = Join-Path $RaizProyecto ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { Error2 "El entorno virtual quedo incompleto."; exit 1 }

# ---------------------------------------------------------------------------
# 3) Dependencias
# ---------------------------------------------------------------------------
Paso "Actualizando pip..."
& $VenvPython -m pip install --quiet --upgrade pip

Paso "Instalando dependencias (puede tardar unos minutos)..."
& $VenvPython -m pip install --quiet -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { Error2 "Fallo la instalacion de dependencias."; exit 1 }

# Registrar el propio paquete. Sin esto las dependencias quedan instaladas
# pero 'python -m tct' falla con "No module named tct", y los tests igual
# pasan porque pytest agrega src/ al path solo para si mismo.
Paso "Registrando el comando 'tct'..."
& $VenvPython -m pip install --quiet -e . --no-deps
& $VenvPython -c "import tct" 2>$null
if ($LASTEXITCODE -ne 0) {
    Error2 "El paquete 'tct' no quedo instalado."
    Write-Host "  Proba a mano:  .venv\Scripts\python.exe -m pip install -e . --no-deps"
    exit 1
}

# ---------------------------------------------------------------------------
# 4) MetaTrader 5
# ---------------------------------------------------------------------------
Write-Host ""
Paso "Verificando MetaTrader 5..."
& $VenvPython -c "import MetaTrader5" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "    Paquete de Python: OK"
} else {
    Aviso "El paquete MetaTrader5 no se instalo. Revisa que este Windows sea 64-bit."
}

$RutasMT5 = @(
    "$env:ProgramFiles\MetaTrader 5\terminal64.exe",
    "${env:ProgramFiles(x86)}\MetaTrader 5\terminal64.exe",
    "$env:APPDATA\MetaQuotes\Terminal"
)
$TerminalEncontrada = $RutasMT5 | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($TerminalEncontrada) {
    Write-Host "    Terminal instalada:  $TerminalEncontrada"
} else {
    Aviso "No se encontro la terminal MetaTrader 5 instalada."
    Write-Host "        Descargala del sitio de tu broker o de metatrader5.com,"
    Write-Host "        abrila y logueate en tu cuenta DEMO antes de arrancar el bot."
}

# ---------------------------------------------------------------------------
# 5) Ollama (IA local, opcional)
# ---------------------------------------------------------------------------
Write-Host ""
Paso "Verificando Ollama (IA local para mensajes raros)..."
$ModeloIA = $null
$OllamaListo = $false
$OllamaPresente = $false

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "    Ollama ya esta instalado."
    $OllamaPresente = $true
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "    Ollama no esta. Se puede instalar con winget (el gestor oficial"
    Write-Host "    de Windows). Son unos 700 MB."
    $r = Read-Host "    Instalar Ollama ahora? [S/n]"
    if ($r -eq "" -or $r -match "^[SsYy]") {
        Paso "Instalando Ollama..."
        winget install --id Ollama.Ollama --accept-package-agreements --accept-source-agreements -e
        # winget no refresca el PATH de la sesion actual.
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path","User")
        if (Get-Command ollama -ErrorAction SilentlyContinue) { $OllamaPresente = $true }
        else { Aviso "Ollama se instalo pero hay que reiniciar la terminal para usarlo." }
    }
} else {
    Aviso "Ollama no esta instalado y no hay winget."
    Write-Host "        Descargalo de https://ollama.com/download"
}

if ($OllamaPresente) {
    # Antes de bajar 4.7 GB, se mira que hay. Una maquina que ya uso Ollama
    # para otra cosa suele tener un modelo perfectamente capaz de esta tarea,
    # y descargar otro seria tirar tiempo y disco al vacio.
    $Instalados = @()
    try {
        $Instalados = (ollama list 2>$null | Select-Object -Skip 1) |
            ForEach-Object { ($_ -split "\s+")[0] } |
            Where-Object { $_ }
    } catch { }

    # Orden de preferencia para extraer datos de un texto corto y desprolijo
    # en castellano. Los qwen2.5/3 son los mas solidos siguiendo un schema;
    # los de 3B entran al final porque se equivocan mas, pero sirven.
    $Preferencia = @("qwen2.5", "qwen3", "llama3.1", "mistral", "gemma", "phi", "llama3.2")
    foreach ($pref in $Preferencia) {
        $encontrado = $Instalados | Where-Object { $_ -like "$pref*" } | Select-Object -First 1
        if ($encontrado) { $ModeloIA = $encontrado; break }
    }

    if ($ModeloIA) {
        Write-Host "    Se reutiliza un modelo que ya tenias: $ModeloIA" -ForegroundColor Green
        Write-Host "    (no hace falta descargar nada)"
        $OllamaListo = $true
    } else {
        Write-Host ""
        Write-Host "    No hay ningun modelo descargado. El recomendado es qwen2.5:7b:"
        Write-Host "      - Ocupa 4.7 GB y tarda entre 10 y 30 minutos segun tu conexion."
        Write-Host "      - Se puede hacer despues, cuando quieras, con scripts\instalar_ia.bat"
        Write-Host "      - El bot funciona igual sin esto: solo pierde los mensajes raros."
        $r = Read-Host "    Descargar el modelo ahora? [s/N]"
        if ($r -match "^[SsYy]") {
            Paso "Descargando qwen2.5:7b. Podes dejarlo corriendo y volver despues..."
            ollama pull qwen2.5:7b
            if ($LASTEXITCODE -eq 0) {
                $ModeloIA = "qwen2.5:7b"
                $OllamaListo = $true
                Write-Host "    Modelo listo." -ForegroundColor Green
            } else {
                Aviso "No se pudo descargar. Reintenta despues con scripts\instalar_ia.bat"
            }
        } else {
            Write-Host "    Saltado. Cuando quieras: scripts\instalar_ia.bat"
        }
    }
}

# ---------------------------------------------------------------------------
# 6) Archivo .env
# ---------------------------------------------------------------------------
Write-Host ""
if (Test-Path ".env") {
    Paso "El archivo .env ya existe, no se toca."
} else {
    Paso "Creando .env a partir de .env.example ..."
    Copy-Item ".env.example" ".env"
    # Solo se enciende la IA si hay un modelo REAL disponible: dejarla en true
    # sin modelo llenaria los logs de avisos en cada arranque.
    if ($OllamaListo -and $ModeloIA) {
        $contenido = Get-Content ".env"
        $contenido = $contenido -replace "^ENABLE_OLLAMA=.*", "ENABLE_OLLAMA=true"
        $contenido = $contenido -replace "^OLLAMA_MODEL=.*", "OLLAMA_MODEL=$ModeloIA"
        $contenido | Set-Content ".env" -Encoding UTF8
        Write-Host "    IA local activada en el .env con el modelo $ModeloIA."
    }
    Aviso "Hay que EDITAR .env y completar las credenciales."
}

New-Item -ItemType Directory -Force -Path "data", "logs" | Out-Null

# ---------------------------------------------------------------------------
# 7) Verificacion
# ---------------------------------------------------------------------------
Write-Host ""
Paso "Corriendo los tests..."
& $VenvPython -m pytest -q
if ($LASTEXITCODE -ne 0) { Error2 "Los tests fallaron. Algo quedo mal instalado."; exit 1 }
Paso "Tests OK."

Write-Host ""
Paso "Diagnostico del entorno:"
Write-Host ""
& $VenvPython -m tct check

# ---------------------------------------------------------------------------
# 8) Accesos directos
# ---------------------------------------------------------------------------
Write-Host ""
Paso "Creando accesos directos..."

$LanzadorBat = Join-Path $RaizProyecto "scripts\iniciar_bot.bat"
$Escritorio  = [Environment]::GetFolderPath("Desktop")
$Shell       = New-Object -ComObject WScript.Shell

$AccesoEscritorio = $Shell.CreateShortcut((Join-Path $Escritorio "Bot de Trading.lnk"))
$AccesoEscritorio.TargetPath       = $LanzadorBat
$AccesoEscritorio.WorkingDirectory = $RaizProyecto
$AccesoEscritorio.Description      = "Arranca el bot de copy trading"
$AccesoEscritorio.Save()
Write-Host "    Escritorio: 'Bot de Trading'"

$r = Read-Host "    Arrancar el bot solo al prender la PC? [S/n]"
if ($r -eq "" -or $r -match "^[SsYy]") {
    $Inicio = [Environment]::GetFolderPath("Startup")
    $AccesoInicio = $Shell.CreateShortcut((Join-Path $Inicio "Bot de Trading.lnk"))
    $AccesoInicio.TargetPath       = $LanzadorBat
    $AccesoInicio.WorkingDirectory = $RaizProyecto
    $AccesoInicio.Save()
    Write-Host "    Arranque automatico: activado" -ForegroundColor Green
    Write-Host "    (para desactivarlo, borra 'Bot de Trading' de la carpeta que"
    Write-Host "     se abre con Win+R -> shell:startup)"
}

# ---------------------------------------------------------------------------
Escribir-Titulo "PROXIMOS PASOS"
@"

  Ya no hay que instalar nada mas. Falta completar el .env.

  1. Abri el archivo .env (esta en esta misma carpeta) con el Bloc de notas.

  2. Credenciales de Telegram, de https://my.telegram.org
     (seccion "API development tools"):
         TELEGRAM_API_ID=...
         TELEGRAM_API_HASH=...

  3. Abri MetaTrader 5, logueate en tu cuenta DEMO, y anota los datos:
         MT5_LOGIN=...
         MT5_PASSWORD=...
         MT5_SERVER=...
     Dejala ABIERTA: el bot le habla a la terminal que ya esta corriendo.

  4. Abri una terminal en esta carpeta y activa el entorno:
         .venv\Scripts\activate

  5. Busca el ID del grupo de senales:
         python -m tct chats
     La primera vez pide telefono y un codigo que llega por Telegram.
     Copia el ID a TELEGRAM_SOURCE_CHATS en el .env.

  6. Verifica que este todo bien:
         python -m tct check

  7. Arranca, con doble clic en 'Bot de Trading' del escritorio, o:
         python -m tct run

  Guia completa y detallada: docs\SETUP_WINDOWS.md

"@ | Write-Host

Write-Host "Presiona Enter para cerrar..." -ForegroundColor Cyan
Read-Host | Out-Null
