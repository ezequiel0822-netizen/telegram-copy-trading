@echo off
REM  Revisa que este todo bien configurado. No modifica nada.
chcp 65001 >nul
title Diagnostico - Bot de Trading
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m tct check
echo.
pause
