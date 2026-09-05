@echo off
REM ---------------------------------------------------------------------------
REM  Prende o apaga que el bot arranque solo al iniciar sesion en Windows.
REM
REM  Doble clic aca. Muestra como esta ahora y te deja cambiarlo.
REM
REM  El -ExecutionPolicy Bypass aplica SOLO a esta ejecucion: no cambia
REM  ninguna configuracion de tu Windows. Existe porque PowerShell bloquea
REM  por defecto los scripts descargados de internet.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Arranque automatico - Bot de Trading
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0autoarranque.ps1"
echo.
pause
