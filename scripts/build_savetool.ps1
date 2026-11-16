# Build the .NET Brotli helper into tools/bin/SaveTool.exe
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root "tools\SaveTool\SaveTool.csproj"
$output = Join-Path $root "tools\bin"

Write-Host "Building $project -> $output"
dotnet publish $project -c Release -o $output

$exe = Join-Path $output "SaveTool.exe"
if (-not (Test-Path $exe)) {
    throw "Build finished but $exe is missing."
}
Write-Host "OK: $exe"
