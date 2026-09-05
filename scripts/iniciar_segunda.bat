@echo off
REM ---------------------------------------------------------------------------
REM  ARRANCA LA SEGUNDA INSTANCIA, contra otra cuenta de MetaTrader.
REM
REM  Usa .env.segunda, un archivo APARTE del .env principal. Los dos bots
REM  corren al mismo tiempo, cada uno con su carpeta de datos, su sesion de
REM  Telegram y su terminal de MetaTrader.
REM
REM  ANTES DE ARRANCAR ESTE, acordate de que la otra MetaTrader tiene que
REM  estar abierta y logueada en SU cuenta. El bot se conecta a la terminal
REM  que dice MT5_PATH, y si esa ruta esta vacia se engancha a cualquiera.
REM
REM  Para frenarlo desde el telefono, en Telegram mandate a vos mismo:
REM      /pausa <el nombre que le pusiste en INSTANCE_NAME>
REM
REM  Para una TERCERA instancia: copia este archivo, cambia .env.segunda por
REM  el nombre del nuevo, y agregala a INSTANCE_NAMES en TODOS los .env.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title BOT 2 - Bot de Trading
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual. Corre primero scripts\instalar.bat
    pause
    exit /b 1
)
if not exist ".env.segunda" (
    echo.
    echo   No existe el archivo .env.segunda
    echo.
    echo   Crealo copiando la plantilla y completalo:
    echo       copy .env.segunda.example .env.segunda
    echo.
    echo   Adentro esta explicado que cinco cosas TIENEN que ser distintas
    echo   de las del .env principal.
    echo.
    pause
    exit /b 1
)

echo.
echo   Arrancando la SEGUNDA instancia.
echo.
echo   Mira la linea "MT5 listo ^| servidor=..." de abajo: esa dice contra
echo   que cuenta esta por operar. Si no es la que esperabas, pará con
echo   Ctrl+C y revisa MT5_PATH en .env.segunda.
echo.

".venv\Scripts\python.exe" -m tct --env-file .env.segunda run

echo.
echo El segundo bot se detuvo.
pause
