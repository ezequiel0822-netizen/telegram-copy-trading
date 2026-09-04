@echo off
REM ---------------------------------------------------------------------------
REM  Abre una consola con el entorno del bot YA ACTIVADO.
REM
REM  Existe por un motivo concreto y repetido: escribir "python -m tct check" a
REM  secas NO funciona. Ese "python" es el de Windows, que no tiene el bot
REM  instalado, y contesta "No module named tct", un mensaje que no explica
REM  nada y que no sugiere que hacer.
REM
REM  El bot vive en el Python de la carpeta .venv del proyecto. Desde esta
REM  ventana ese ya es el Python activo, asi que los comandos se escriben
REM  cortos: tct check, tct status, tct run.
REM ---------------------------------------------------------------------------
chcp 65001 >nul
title Consola del Bot de Trading
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   No se encontro el entorno virtual .venv en esta carpeta.
    echo   Eso significa que el bot todavia no esta instalado aca.
    echo.
    echo   Corre primero:  scripts\instalar.bat
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo.
echo  ==============================================================
echo    Consola del bot. El entorno ya esta activado.
echo  ==============================================================
echo.
echo    tct check          Diagnostico: dice que falta y que hacer
echo    tct status         Posiciones abiertas y estadisticas
echo    tct probar         Verifica la cadena completa contra MetaTrader
echo    tct run            Arranca el bot
echo.
echo    tct simular --horas 2
echo        Muestra que habria hecho con los mensajes de las ultimas 2 horas.
echo        Sin --ejecutar no toca nada.
echo.
echo    tct simular --horas 2 --con-precios
echo        Lo mismo, y ademas compara cada entrada contra el precio real de
echo        MT5 para decirte que limite poner en el .env. Tampoco opera.
echo.
echo  --------------------------------------------------------------
echo    Escribi "exit" para cerrar esta ventana.
echo  --------------------------------------------------------------
echo.

cmd /k
