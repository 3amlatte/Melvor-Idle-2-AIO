@echo off
setlocal
cd /d "%~dp0"

rem Rebuild dist\MI2 AIO if the source changed, then launch the portable app.
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ensure_dist.ps1" -Launch
if errorlevel 1 (
    echo.
    pause
)
endlocal
