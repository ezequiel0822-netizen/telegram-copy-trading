@echo off
REM ---------------------------------------------------------------------------
REM  Descarga el modelo de IA local y lo deja activado en el .env.
REM  Se puede correr cuando quieras: el bot funciona sin esto.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Instalar IA local - Bot de Trading
cd /d "%~dp0.."

where ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama no esta instalado.
    echo.
    echo Instalalo con uno de estos dos caminos y volve a correr este archivo:
    echo.
    echo   A^) Desde una terminal:   winget install Ollama.Ollama
    echo   B^) Descargandolo de:     https://ollama.com/download
    echo.
    pause
    exit /b 1
)

echo Modelos que ya tenes descargados:
echo.
ollama list
echo.
echo Si arriba YA aparece un modelo que quieras usar, cerra esta ventana y
echo escribi su nombre en OLLAMA_MODEL dentro del archivo .env
echo.
echo Si no, se va a descargar llama3.2:3b ^(2 GB, unos minutos^).
echo.
pause

ollama pull llama3.2:3b
if errorlevel 1 (
    echo.
    echo La descarga fallo. Podes reintentar corriendo este archivo de nuevo.
    pause
    exit /b 1
)

REM Dejar la IA activada sin que el usuario tenga que editar el .env a mano:
REM despues de esperar media hora una descarga, pedirle que ademas edite un
REM archivo de configuracion es la forma mas facil de que quede sin usarse.
if not exist ".env" (
    echo.
    echo Modelo descargado, pero todavia no existe el archivo .env
    echo Corre primero scripts\instalar.bat
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "import pathlib,re; p=pathlib.Path('.env'); t=p.read_text(encoding='utf-8'); t=re.sub(r'^ENABLE_OLLAMA=.*$','ENABLE_OLLAMA=true',t,flags=re.M); t=re.sub(r'^OLLAMA_MODEL=.*$','OLLAMA_MODEL=llama3.2:3b',t,flags=re.M); p.write_text(t,encoding='utf-8'); print('   .env actualizado: ENABLE_OLLAMA=true, OLLAMA_MODEL=llama3.2:3b')"

echo.
echo Listo. La IA local queda activada.
echo Verificalo con scripts\diagnostico.bat
echo.
pause
