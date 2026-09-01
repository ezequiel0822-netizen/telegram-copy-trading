@echo off
REM  Diagnostico de la instancia REAL. No modifica nada.
chcp 65001 >nul
title Diagnostico REAL - Bot de Trading
cd /d "%~dp0.."
if not exist ".env.real" (
    echo No existe .env.real  ^(copialo de .env.real.example^)
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m tct --env-file .env.real check
echo.
pause
