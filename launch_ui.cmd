@echo off
setlocal
cd /d "%~dp0"

set "PY=python"
set "PYW=pythonw"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if exist ".venv\Scripts\pythonw.exe" set "PYW=.venv\Scripts\pythonw.exe"

rem Check the required tools before importing the GUI. If something is
rem missing, keep the window open so the fix instructions can be read.
"%PY%" -m mi2_aio.preflight
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)

start "" "%PYW%" -m mi2_aio.app
endlocal
