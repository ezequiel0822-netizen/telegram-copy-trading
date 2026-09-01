@echo off
REM ---------------------------------------------------------------------------
REM  Reproduce los mensajes REALES de las ultimas 24 horas del grupo y muestra
REM  como los habria interpretado el bot.
REM
REM  NO ejecuta ni registra nada: es solo una mirada. Para correrlo de verdad
REM  contra la cuenta demo, usa el comando que se imprime al final.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Simular el dia - Bot de Trading
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m tct simular --horas 24
echo.
pause
