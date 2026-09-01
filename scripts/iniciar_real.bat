@echo off
REM ---------------------------------------------------------------------------
REM  ARRANCA EL BOT CONTRA LA CUENTA REAL.
REM
REM  Usa .env.real, que es un archivo APARTE del .env de la demo. Los dos
REM  pueden correr al mismo tiempo: cada uno tiene su carpeta de datos y su
REM  sesion de Telegram.
REM
REM  Para frenarlo desde el telefono, mandate a vos mismo en Telegram:
REM      /pausa real
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
echo   Para pausarlo desde el telefono, en Telegram: /pausa real
echo.
pause

".venv\Scripts\python.exe" --version >nul 2>nul
".venv\Scripts\python.exe" -m tct --env-file .env.real run

echo.
echo El bot REAL se detuvo.
pause
