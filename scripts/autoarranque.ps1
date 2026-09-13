# ---------------------------------------------------------------------------
#  Prende o apaga el arranque automatico de los bots al iniciar sesion.
#
#  Maneja UNA o DOS instancias. La segunda existe cuando hay un .env.segunda
#  -el bot que opera contra el otro broker- y necesita su propio acceso
#  directo, porque son dos procesos distintos con configuraciones distintas.
#
#  No se llama directo: usa scripts\autoarranque.bat, que saltea la
#  restriccion de PowerShell para scripts descargados de internet.
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Raiz

$Inicio = [Environment]::GetFolderPath("Startup")
$Lanzador = Join-Path $Raiz "scripts\iniciar_auto.bat"
$Shell = New-Object -ComObject WScript.Shell

# Las instancias que se pueden poner en el inicio. El nombre del acceso
# directo del primero NO cambia ("Bot de Trading.lnk") para no dejar
# huerfano el que ya tenga puesto quien uso la version anterior.
$Instancias = @(
    [pscustomobject]@{ Nombre = "principal"; Env = ".env";         Acceso = "Bot de Trading.lnk" }
    [pscustomobject]@{ Nombre = "segunda";   Env = ".env.segunda"; Acceso = "Bot de Trading (segunda).lnk" }
)

function Titulo($texto) {
    Write-Host ""
    Write-Host ("=" * 66)
    Write-Host "  $texto"
    Write-Host ("=" * 66)
}

# Solo se ofrecen las que existen de verdad: sin .env.segunda no tiene
# sentido hablar de dos bots.
$Disponibles = @($Instancias | Where-Object { Test-Path (Join-Path $Raiz $_.Env) })

if ($Disponibles.Count -eq 0) {
    Write-Host "  ERROR: no se encontro ningun .env en $Raiz" -ForegroundColor Red
    Write-Host "  Corre primero scripts\instalar.bat"
    exit 1
}

# --- Estado actual ---------------------------------------------------------
Titulo "ARRANQUE AUTOMATICO"

$Activos = 0
foreach ($i in $Disponibles) {
    $ruta = Join-Path $Inicio $i.Acceso
    if (Test-Path $ruta) {
        $Activos++
        $acc = $Shell.CreateShortcut($ruta)
        $arg = if ($acc.Arguments) { $acc.Arguments } else { "(el .env de siempre)" }
        Write-Host ("  {0,-11} ACTIVADO   -> {1}" -f $i.Nombre, $arg) -ForegroundColor Green
    } else {
        Write-Host ("  {0,-11} apagado" -f $i.Nombre) -ForegroundColor Yellow
    }
}

if ($Disponibles.Count -eq 1) {
    Write-Host ""
    Write-Host "  (no hay .env.segunda, asi que solo se maneja el bot principal)"
}

# --- Que hace falta ademas -------------------------------------------------
Write-Host ""
Write-Host "  OJO: cada bot necesita SU MetaTrader ABIERTO y logueado."
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
if ($Activos -eq $Disponibles.Count) {
    $r = Read-Host "  Que hago? [D]esactivar todo / [N]ada"
    if ($r -match "^[Dd]") {
        foreach ($i in $Disponibles) {
            $ruta = Join-Path $Inicio $i.Acceso
            if (Test-Path $ruta) { Remove-Item $ruta -Force }
        }
        Write-Host ""
        Write-Host "  Arranque automatico DESACTIVADO." -ForegroundColor Yellow
        Write-Host "  Para arrancarlos a mano:"
        Write-Host "      scripts\iniciar_bot.bat        (el principal)"
        if ($Disponibles.Count -gt 1) {
            Write-Host "      scripts\iniciar_segunda.bat    (el segundo)"
        }
    } else {
        Write-Host "  No se cambio nada."
    }
    Write-Host ""
    exit 0
}

$cuantos = if ($Disponibles.Count -gt 1) { "los $($Disponibles.Count) bots" } else { "el bot" }
$r = Read-Host "  Activar el arranque automatico de $cuantos? [S/n]"
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

Write-Host ""
foreach ($i in $Disponibles) {
    $acceso = $Shell.CreateShortcut((Join-Path $Inicio $i.Acceso))
    $acceso.TargetPath       = $Lanzador
    # El principal va SIN argumento: asi el acceso directo queda identico al
    # que creaba la version anterior de este script.
    $acceso.Arguments        = if ($i.Env -eq ".env") { "" } else { $i.Env }
    $acceso.WorkingDirectory = $Raiz
    $acceso.Description      = "Arranca el bot de copy trading ($($i.Nombre)) al iniciar sesion"
    $acceso.Save()
    Write-Host ("  OK  {0,-11} -> {1}" -f $i.Nombre, $i.Env) -ForegroundColor Green
}

Write-Host ""
Write-Host "  Arranque automatico ACTIVADO." -ForegroundColor Green
Write-Host "  Usa scripts\iniciar_auto.bat, que espera hasta 5 minutos a que"
Write-Host "  MetaTrader este listo y vuelve a levantar el bot si se cae."
if ($Disponibles.Count -gt 1) {
    Write-Host ""
    Write-Host "  Van a abrirse DOS ventanas negras, una por bot. Es lo esperado:"
    Write-Host "  cerrar una para el bot de esa cuenta y deja la otra andando."
}

# --- MetaTrader tambien --------------------------------------------------
Titulo "Y METATRADER?"

$yaEsta = @(Get-ChildItem $Inicio -Filter *.lnk -ErrorAction SilentlyContinue |
    Where-Object { $Shell.CreateShortcut($_.FullName).TargetPath -like "*terminal64.exe" })

$faltan = $Disponibles.Count - $yaEsta.Count

if ($faltan -le 0) {
    Write-Host "  Ya hay $($yaEsta.Count) MetaTrader en el inicio, uno por bot." -ForegroundColor Green
    Write-Host "  Nada que hacer."
    Write-Host ""
    exit 0
}

if ($yaEsta.Count -gt 0) {
    Write-Host "  Hay $($yaEsta.Count) MetaTrader en el inicio y $($Disponibles.Count) bots." -ForegroundColor Yellow
    Write-Host "  Cada bot necesita el SUYO: falta(n) $faltan."
} else {
    Write-Host "  Sin MetaTrader abierto el bot no puede operar, asi que conviene"
    Write-Host "  que arranquen solos tambien."
}
Write-Host ""
Write-Host "  Buscando MetaTrader en la maquina..."

# Se miran las dos carpetas de programas: los brokers no coinciden en cual
# usan, y con dos instalaciones distintas es muy probable que esten separadas.
$candidatos = @(
    foreach ($base in @("C:\Program Files", "C:\Program Files (x86)")) {
        if (Test-Path $base) {
            Get-ChildItem $base -Filter terminal64.exe -Recurse -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty FullName
        }
    }
) | Select-Object -Unique | Select-Object -First 8

# Las que ya estan en el inicio no se vuelven a ofrecer.
$puestas = @($yaEsta | ForEach-Object { $Shell.CreateShortcut($_.FullName).TargetPath })
$candidatos = @($candidatos | Where-Object { $puestas -notcontains $_ })

if ($candidatos.Count -eq 0) {
    Write-Host "  No se encontro ninguno nuevo." -ForegroundColor Yellow
    Write-Host "  Agregalo a mano: Win+R -> shell:startup -> copia ahi el acceso"
    Write-Host "  directo de cada MetaTrader."
    Write-Host ""
    exit 0
}

Write-Host ""
for ($i = 0; $i -lt $candidatos.Count; $i++) {
    Write-Host "     [$($i + 1)] $($candidatos[$i])"
}
Write-Host "     [0] ninguno, los agrego a mano"
Write-Host ""
if ($faltan -gt 1) {
    Write-Host "  Podes elegir varios separados por coma. Ejemplo:  1,2"
    Write-Host ""
}
$elegido = Read-Host "  Cual(es) agrego al inicio?"

$indices = @(
    $elegido -split "," |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ -match "^\d+$" } |
        ForEach-Object { [int]$_ } |
        Where-Object { $_ -ge 1 -and $_ -le $candidatos.Count }
) | Select-Object -Unique

if ($indices.Count -eq 0) {
    Write-Host "  No se agrego ningun MetaTrader al inicio."
    Write-Host ""
    exit 0
}

Write-Host ""
$n = 0
foreach ($idx in $indices) {
    $exe = $candidatos[$idx - 1]
    # Un nombre por instalacion: usar siempre "MetaTrader 5.lnk" haria que la
    # segunda pisara a la primera y quedara una sola en el inicio.
    $n++
    $nombre = if ($n -eq 1) { "MetaTrader 5.lnk" } else { "MetaTrader 5 ($n).lnk" }
    $accesoMt5 = $Shell.CreateShortcut((Join-Path $Inicio $nombre))
    $accesoMt5.TargetPath       = $exe
    $accesoMt5.WorkingDirectory = Split-Path -Parent $exe
    $accesoMt5.Save()
    Write-Host "  OK  $nombre -> $exe" -ForegroundColor Green
}

Write-Host ""
Write-Host "  MetaTrader agregado al inicio." -ForegroundColor Green
Write-Host "  Acordate de que cada uno tiene que quedar logueado en SU cuenta y"
Write-Host "  con 'Algo Trading' en verde: eso lo recuerda solo entre reinicios."
Write-Host ""
