@echo off
REM ---------------------------------------------------------------------------
REM  Verifica la cadena completa contra MetaTrader 5: conexion, cuenta demo,
REM  AutoTrading, simbolos, cotizaciones y tamano de lote.
REM
REM  NO opera. Para la prueba de fuego (abrir y cerrar una posicion real de
REM  tamano minimo en la demo), usa el comando que se imprime al final.
REM
REM  MetaTrader 5 tiene que estar ABIERTO y logueado.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Probar MT5 - Bot de Trading
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m tct probar
echo.
pause
