@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%gemini_key_setup.py"
set "PYTHONW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

if exist "%PYTHONW%" (
    start "" "%PYTHONW%" "%SCRIPT_PATH%"
    exit /b 0
)

if exist "%PYTHON%" (
    start "" "%PYTHON%" "%SCRIPT_PATH%"
    exit /b 0
)

echo Python 3.13 was not found at:
echo %LOCALAPPDATA%\Programs\Python\Python313
echo.
echo Please install Python 3.13 or run gemini_key_setup.py with an installed Python.
pause
exit /b 1
