@echo off
REM ---------------------------------------------------------------------------
REM  ARRANCA LA DEMO DE BULLWAVES: el ensayo de la cuenta real.
REM
REM  Usa .env.bullwaves: los MISMOS numeros que .env.real, contra una cuenta
REM  DEMO de Bullwaves. Corre al lado de las otras demos, con su carpeta de
REM  datos, su sesion de Telegram y el MetaTrader de Bullwaves.
REM
REM  El MetaTrader de Bullwaves tiene que estar abierto y logueado en la
REM  cuenta DEMO. Es temporal: para pasar a la real se cierra este bot y se
REM  retira el archivo (ver arriba de .env.bullwaves).
REM
REM  Sin control por Telegram, igual que la real: se frena cerrando la ventana.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title DEMO BULLWAVES - Bot de Trading
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)
if not exist ".env.bullwaves" (
    echo.
    echo   No existe el archivo .env.bullwaves
    echo.
    echo   Los archivos de configuracion que SI hay en esta carpeta:
    echo.
    REM  *env* y no .env*: el error mas comun es que el archivo haya quedado
    REM  SIN el punto de adelante -Windows no deja crear nombres que empiecen
    REM  con punto desde el Explorador-, y con el patron .env* ese caso, que
    REM  es justo el que hay que mostrar, no aparecia en la lista.
    REM  /a-d deja afuera las carpetas, o la lista incluiria .venv.
    dir /b /a-d *env* 2>nul
    echo.
    echo   Si en esa lista ves uno con el contenido que completaste pero con
    echo   otro nombre, NO lo copies de nuevo: renombralo, asi no perdes lo
    echo   que ya escribiste adentro.
    echo.
    echo       ren "el-nombre-que-tiene" .env.bullwaves
    echo.
    echo   Y si no esta, crealo desde la plantilla:
    echo       copy .env.bullwaves.example .env.bullwaves
    echo.
    echo   Adentro esta explicado que completar y en que orden.
    echo.
    pause
    exit /b 1
)

echo.
echo   Arrancando la DEMO DE BULLWAVES (ensayo de la real).
echo.
echo   Mira la linea "MT5 listo ^| servidor=..." de abajo: esa dice contra
echo   que cuenta esta por operar. Si no es la que esperabas, pará con
echo   Ctrl+C y revisa MT5_PATH en .env.bullwaves.
echo.
echo   Si le pusiste clave de arranque, te la va a pedir. No se ve mientras
echo   la escribis. Para ponerla o cambiarla:  tct clave --env-file .env.bullwaves
echo.

".venv\Scripts\python.exe" -m tct --env-file .env.bullwaves run

echo.
echo La demo de Bullwaves se detuvo.
pause
