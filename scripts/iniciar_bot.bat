@echo off
REM ---------------------------------------------------------------------------
REM  Arranca el bot. Es el destino del acceso directo del escritorio y del
REM  arranque automatico de Windows.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Bot de Trading
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual.
    echo Corre primero scripts\instalar.bat
    pause
    exit /b 1
)

echo Arrancando el bot. Para detenerlo, cerra esta ventana o apreta Ctrl+C.
echo.
".venv\Scripts\python.exe" -m tct run

REM Si el bot termina (por un error o por Ctrl+C), la ventana queda abierta
REM para poder leer que paso. Sin esto se cierra sola y el motivo se pierde.
echo.
echo El bot se detuvo.
pause
