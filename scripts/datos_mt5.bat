@echo off
REM ---------------------------------------------------------------------------
REM  Lee tu cuenta de MetaTrader 5 y te dice exactamente que poner en el .env.
REM  Sirve para no tener que averiguar a mano el nombre del servidor, que es
REM  la parte que mas confunde de toda la instalacion.
REM
REM  MetaTrader 5 tiene que estar ABIERTO y logueado antes de correr esto.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Datos de MT5 - Bot de Trading
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m tct mt5
echo.
pause
