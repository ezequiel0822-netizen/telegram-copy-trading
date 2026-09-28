@echo off
REM ---------------------------------------------------------------------------
REM  ARRANCA EL BOT CONTRA LA CUENTA REAL.
REM
REM  Usa .env.real, que es un archivo APARTE del .env de la demo. La cuenta real
REM  es de BULLWAVES y tiene su propio MetaTrader (MT5_PATH en .env.real), asi
REM  que puede correr al mismo tiempo que las dos demos: cada bot tiene su
REM  terminal, su carpeta de datos y su sesion de Telegram.
REM
REM  Con ENABLE_TELEGRAM_CONTROL=false (como esta), NO hay pausa desde el
REM  telefono: se frena cerrando esta ventana.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title BOT REAL - Bot de Trading
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)
if not exist ".env.real" (
    echo.
    echo No existe el archivo .env.real
    echo.
    echo Crealo copiando la plantilla y completalo:
    echo     copy .env.real.example .env.real
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo   ESTE BOT OPERA CON DINERO REAL
echo ============================================================
echo.
echo   Para detenerlo: cerra esta ventana o apreta Ctrl+C.
echo   Desde el telefono SOLO si ENABLE_TELEGRAM_CONTROL=true en .env.real
echo   (hoy esta en false: la unica forma es cerrar esta ventana).
echo.
echo   Te va a pedir la CLAVE DE ARRANQUE. No se ve mientras la escribis.
echo   Si todavia no pusiste una:  tct clave --env-file .env.real
echo.
pause

".venv\Scripts\python.exe" --version >nul 2>nul
".venv\Scripts\python.exe" -m tct --env-file .env.real run

echo.
echo El bot REAL se detuvo.
pause
