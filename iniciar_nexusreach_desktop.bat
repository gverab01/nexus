@echo off
title NexusReach Pro Desktop Launcher
echo ========================================================
echo    Iniciando NexusReach Pro Desktop
echo ========================================================
echo.

cd /d "%~dp0"

echo 1. Levantando servidor backend en puerto 8000...
start "NexusReach Backend Server" /min .\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

echo 2. Esperando inicio del servidor backend (3 segundos)...
timeout /t 3 /nobreak >nul

echo 3. Lanzando aplicacion de escritorio Electron...
cd desktop
npm start

echo.
echo Cerrando ventana de lanzamiento...
