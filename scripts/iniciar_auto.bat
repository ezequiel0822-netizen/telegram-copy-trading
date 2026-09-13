@echo off
REM ---------------------------------------------------------------------------
REM  ARRANQUE AUTOMATICO. Es el que corre solo al prender la PC.
REM
REM  Se diferencia de iniciar_bot.bat en dos cosas, las dos por el mismo
REM  motivo: nadie esta mirando la pantalla cuando esto arranca.
REM
REM  1. ESPERA A METATRADER. Al iniciar sesion, MetaTrader y el bot arrancan
REM     casi al mismo tiempo, pero MetaTrader tarda: levanta la interfaz, se
REM     conecta al broker y loguea la cuenta. El bot gana esa carrera casi
REM     siempre, y como sin broker no arranca, el arranque automatico fallaba
REM     en silencio en casi todos los encendidos.
REM
REM  2. SE VUELVE A LEVANTAR. Si el proceso se cae (se corto la conexion y no
REM     se pudo recuperar, por ejemplo), espera un minuto y arranca de nuevo.
REM     Sin esto, un corte de madrugada te deja sin bot hasta que te acordes
REM     de mirar.
REM
REM  Para apagar el arranque automatico:  scripts\autoarranque.bat
REM ---------------------------------------------------------------------------
chcp 65001 >nul
cd /d "%~dp0.."

REM  Con QUE configuracion arranca. Sin argumento es el .env de siempre, que
REM  es como lo llamaba el acceso directo antes de que existiera la segunda
REM  instancia: los accesos viejos siguen funcionando igual.
REM
REM     iniciar_auto.bat                  -> .env
REM     iniciar_auto.bat .env.segunda     -> el segundo bot
set "ARCHIVO=%~1"
if "%ARCHIVO%"=="" set "ARCHIVO=.env"

title Bot de Trading (arranque automatico - %ARCHIVO%)

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)

if not exist "%ARCHIVO%" (
    echo No existe el archivo de configuracion "%ARCHIVO%".
    echo Revisa el acceso directo del inicio, o corre scripts\autoarranque.bat
    pause
    exit /b 1
)

set INTENTOS=0

:arrancar
echo.
echo ==============================================================
echo   Bot de Trading  -  arranque automatico
echo   Configuracion: %ARCHIVO%
echo ==============================================================
echo   Espera hasta 5 minutos a que MetaTrader este listo.
echo   Para pararlo del todo: cerra esta ventana.
echo.

".venv\Scripts\python.exe" -m tct --env-file "%ARCHIVO%" run --esperar-mt5 300
set CODIGO=%ERRORLEVEL%

REM Codigo 1 = el bot decidio no arrancar (config mala, carpeta ocupada, o
REM MetaTrader nunca aparecio). Reintentar en bucle no lo va a arreglar y
REM llenaria el log de lo mismo cada minuto.
if "%CODIGO%"=="1" (
    echo.
    echo   El bot no pudo arrancar y reintentar no lo va a arreglar.
    echo   Mira el motivo arriba. Esta ventana queda abierta.
    echo.
    pause
    exit /b 1
)

set /a INTENTOS+=1
if %INTENTOS% GEQ 20 (
    echo.
    echo   Se reinicio 20 veces. Algo esta mal de verdad: se corta el bucle
    echo   para que puedas leer que pasa en la carpeta logs\
    echo   (el archivo exacto lo dice LOG_PATH de %ARCHIVO%)
    echo.
    pause
    exit /b 1
)

echo.
echo   El bot se detuvo (intento %INTENTOS%). Reintentando en 60 segundos...
echo   Para que NO vuelva a arrancar, cerra esta ventana ahora.
echo.
timeout /t 60 /nobreak >nul
goto arrancar
