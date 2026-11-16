@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m mi2_aio.app
) else (
    start "" pythonw -m mi2_aio.app
)
endlocal
