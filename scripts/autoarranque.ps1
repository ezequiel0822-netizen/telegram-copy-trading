# ---------------------------------------------------------------------------
#  Prende o apaga el arranque automatico del bot al iniciar sesion en Windows.
#
#  No se llama directo: usa scripts\autoarranque.bat, que saltea la
#  restriccion de PowerShell para scripts descargados de internet.
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Raiz

$Inicio = [Environment]::GetFolderPath("Startup")
$AccesoBot = Join-Path $Inicio "Bot de Trading.lnk"
$Lanzador = Join-Path $Raiz "scripts\iniciar_auto.bat"
$Shell = New-Object -ComObject WScript.Shell

function Titulo($texto) {
    Write-Host ""
    Write-Host ("=" * 66)
    Write-Host "  $texto"
    Write-Host ("=" * 66)
}

# --- Estado actual ---------------------------------------------------------
Titulo "ARRANQUE AUTOMATICO DEL BOT"

$Activo = Test-Path $AccesoBot
if ($Activo) {
    Write-Host "  Estado actual: ACTIVADO" -ForegroundColor Green
    $destino = $Shell.CreateShortcut($AccesoBot).TargetPath
    Write-Host "  Arranca: $destino"
} else {
    Write-Host "  Estado actual: apagado" -ForegroundColor Yellow
}

# --- Que hace falta ademas -------------------------------------------------
Write-Host ""
Write-Host "  OJO: el bot necesita MetaTrader ABIERTO y logueado para operar."
Write-Host "  'Al prender la PC' en realidad significa 'al INICIAR SESION' en"
Write-Host "  Windows, porque MetaTrader es un programa de escritorio y vive en"
Write-Host "  tu sesion. Si la PC se reinicia sola por un corte de luz y queda"
Write-Host "  en la pantalla de contrasena, no arranca nada."
Write-Host ""
Write-Host "  Para que ande sin que nadie toque la maquina hacen falta tres cosas:"
Write-Host "     1. Este arranque automatico            <- lo que hace este script"
Write-Host "     2. MetaTrader tambien en el inicio     <- lo ofrece aca abajo"
Write-Host "     3. Windows entrando solo a tu usuario  <- lo tenes que hacer vos"
Write-Host ""
Write-Host "  Para el punto 3: Win+R, escribi 'netplwiz', Enter, destilda"
Write-Host "  'Los usuarios deben escribir su nombre y contrasena'."
Write-Host "  Solo hacelo si esa PC esta en un lugar de confianza: cualquiera"
Write-Host "  que la prenda entra a tu sesion sin contrasena."

# --- Que hacer -------------------------------------------------------------
Write-Host ""
if ($Activo) {
    $r = Read-Host "  Que hago? [D]esactivar / [N]ada"
    if ($r -match "^[Dd]") {
        Remove-Item $AccesoBot -Force
        Write-Host ""
        Write-Host "  Arranque automatico DESACTIVADO." -ForegroundColor Yellow
        Write-Host "  El bot ya no va a arrancar solo. Para arrancarlo a mano:"
        Write-Host "      scripts\iniciar_bot.bat"
    } else {
        Write-Host "  No se cambio nada."
    }
    Write-Host ""
    exit 0
}

$r = Read-Host "  Activar el arranque automatico? [S/n]"
if ($r -ne "" -and $r -notmatch "^[SsYy]") {
    Write-Host "  No se cambio nada."
    Write-Host ""
    exit 0
}

if (-not (Test-Path $Lanzador)) {
    Write-Host "  ERROR: no existe $Lanzador" -ForegroundColor Red
    Write-Host "  Corre 'git pull' para bajar la version que lo incluye."
    exit 1
}

$acceso = $Shell.CreateShortcut($AccesoBot)
$acceso.TargetPath       = $Lanzador
$acceso.WorkingDirectory = $Raiz
$acceso.Description      = "Arranca el bot de copy trading al iniciar sesion"
$acceso.Save()

Write-Host ""
Write-Host "  Arranque automatico ACTIVADO." -ForegroundColor Green
Write-Host "  Usa scripts\iniciar_auto.bat, que espera hasta 5 minutos a que"
Write-Host "  MetaTrader este listo y vuelve a levantar el bot si se cae."

# --- MetaTrader tambien --------------------------------------------------
Titulo "Y METATRADER?"

$yaEsta = @(Get-ChildItem $Inicio -Filter *.lnk -ErrorAction SilentlyContinue |
    Where-Object { $Shell.CreateShortcut($_.FullName).TargetPath -like "*terminal64.exe" })

if ($yaEsta.Count -gt 0) {
    Write-Host "  MetaTrader ya esta en el inicio. Nada que hacer." -ForegroundColor Green
    Write-Host ""
    exit 0
}

Write-Host "  Sin MetaTrader abierto el bot no puede operar, asi que conviene"
Write-Host "  que arranque solo tambien."
Write-Host ""
Write-Host "  Buscando MetaTrader en la maquina..."

$candidatos = @(
    Get-ChildItem "C:\Program Files" -Filter terminal64.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 5 -ExpandProperty FullName
)

if ($candidatos.Count -eq 0) {
    Write-Host "  No se encontro ninguno en C:\Program Files." -ForegroundColor Yellow
    Write-Host "  Agregalo a mano: Win+R -> shell:startup -> copia ahi el acceso"
    Write-Host "  directo de MetaTrader."
    Write-Host ""
    exit 0
}

Write-Host ""
for ($i = 0; $i -lt $candidatos.Count; $i++) {
    Write-Host "     [$($i + 1)] $($candidatos[$i])"
}
Write-Host "     [0] ninguno, lo agrego a mano"
Write-Host ""
$elegido = Read-Host "  Cual agrego al inicio?"

if ($elegido -notmatch "^\d+$" -or [int]$elegido -lt 1 -or [int]$elegido -gt $candidatos.Count) {
    Write-Host "  No se agrego MetaTrader al inicio."
    Write-Host ""
    exit 0
}

$exe = $candidatos[[int]$elegido - 1]
$accesoMt5 = $Shell.CreateShortcut((Join-Path $Inicio "MetaTrader 5.lnk"))
$accesoMt5.TargetPath       = $exe
$accesoMt5.WorkingDirectory = Split-Path -Parent $exe
$accesoMt5.Save()

Write-Host ""
Write-Host "  MetaTrader agregado al inicio." -ForegroundColor Green
Write-Host "  Acordate de que tiene que quedar logueado en la cuenta y con"
Write-Host "  'Algo Trading' en verde: eso lo recuerda solo entre reinicios."
Write-Host ""
