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
title Bot de Trading (arranque automatico)
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)

set INTENTOS=0

:arrancar
echo.
echo ==============================================================
echo   Bot de Trading  -  arranque automatico
echo ==============================================================
echo   Espera hasta 5 minutos a que MetaTrader este listo.
echo   Para pararlo del todo: cerra esta ventana.
echo.

".venv\Scripts\python.exe" -m tct run --esperar-mt5 300
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
    echo   para que puedas leer que pasa en logs\tct.log
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
