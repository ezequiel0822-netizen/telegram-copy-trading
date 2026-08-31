@echo off
REM ---------------------------------------------------------------------------
REM  Descarga el modelo de IA local para interpretar mensajes raros.
REM  Se puede correr cuando quieras: el bot funciona sin esto.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Instalar IA local - Bot de Trading
cd /d "%~dp0.."

where ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama no esta instalado.
    echo.
    echo Descargalo de https://ollama.com/download , instalalo,
    echo y despues volve a correr este archivo.
    echo.
    pause
    exit /b 1
)

echo Modelos que ya tenes:
ollama list
echo.
echo Se va a descargar qwen2.5:7b ^(4.7 GB^). Puede tardar entre 10 y 30 minutos.
echo Si arriba ya aparece un modelo que quieras usar, cancela con Ctrl+C y
echo escribi su nombre en OLLAMA_MODEL dentro del archivo .env
echo.
pause

ollama pull qwen2.5:7b
if errorlevel 1 (
    echo.
    echo La descarga fallo. Podes reintentar corriendo este archivo de nuevo.
    pause
    exit /b 1
)

echo.
echo Modelo descargado. Ahora activalo en el archivo .env:
echo     ENABLE_OLLAMA=true
echo     OLLAMA_MODEL=qwen2.5:7b
echo.
pause
