# Build a standalone MI2 AIO desktop app with PyInstaller.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$saveTool = Join-Path $root "tools\bin\SaveTool.exe"
if (-not (Test-Path $saveTool)) {
    Write-Host "SaveTool.exe is missing; building it first."
    & (Join-Path $PSScriptRoot "build_savetool.ps1")
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m pip install "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) {
    throw "Could not install PyInstaller (exit $LASTEXITCODE)."
}
& $python -m PyInstaller --noconfirm --clean (Join-Path $root "mi2_aio.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE)."
}

$output = Join-Path $root "dist\MI2 AIO\MI2 AIO.exe"
if (-not (Test-Path $output)) {
    throw "Build finished but $output is missing."
}
Write-Host "OK: $output"
Write-Host "The app keeps config/logs in %APPDATA%\MI2 AIO."
exit 0
