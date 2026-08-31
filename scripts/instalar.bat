@echo off
REM ---------------------------------------------------------------------------
REM  Instalador de Telegram Copy Trading para Windows.
REM  Doble clic aca. No hace falta abrir ninguna terminal.
REM
REM  Este .bat existe por una sola razon: PowerShell bloquea por defecto los
REM  scripts .ps1, asi que hacer doble clic en setup_windows.ps1 no funciona y
REM  el error que muestra no explica nada. El -ExecutionPolicy Bypass de abajo
REM  aplica SOLO a esta ejecucion: no cambia ninguna configuracion de Windows.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Instalador - Bot de Trading
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"
if errorlevel 1 (
    echo.
    echo La instalacion no termino bien. Mira el mensaje de arriba.
    pause
)
