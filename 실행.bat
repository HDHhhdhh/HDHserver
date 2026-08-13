@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\waitress-serve.exe" (
    echo [ERROR] Waitress is not installed in C:\server\venv.
    echo [INFO] Install Waitress and run this launcher again.
    pause
    exit /b 1
)

echo [INFO] Starting the production server...
schtasks /Query /TN "\Academy Server Waitress" >nul 2>&1
if errorlevel 1 (
    start "" /B powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\run_waitress_server.ps1"
) else (
    schtasks /Run /TN "\Academy Server Waitress" >nul
)

timeout /t 3 >nul
start "" "http://192.168.0.5:8003/"
exit /b
