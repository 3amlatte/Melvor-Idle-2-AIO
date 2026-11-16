param(
    [string]$Thumbprint = "",
    [string]$PfxPath = "",
    [string]$PfxPassword = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$SignTool = ""
)

# Build the standalone desktop app and package it for a GitHub release.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

# Force the helper build so the packaged app contains the self-contained
# SaveTool (no .NET runtime required on the user's machine).
& (Join-Path $PSScriptRoot "build_savetool.ps1")

& (Join-Path $PSScriptRoot "build_app.ps1")

$version = (Select-String -Path (Join-Path $root "pyproject.toml") `
    -Pattern '^version = "(.+)"$').Matches.Groups[1].Value
if (-not $version) {
    throw "Could not read the version from pyproject.toml."
}

$dist = Join-Path $root "dist\MI2 AIO"
if (-not (Test-Path $dist)) {
    throw "Build output is missing: $dist"
}

if ($Thumbprint -or $PfxPath) {
    & (Join-Path $PSScriptRoot "sign_app.ps1") `
        -Root $dist `
        -Thumbprint $Thumbprint `
        -PfxPath $PfxPath `
        -PfxPassword $PfxPassword `
        -TimestampUrl $TimestampUrl `
        -SignTool $SignTool
} else {
    Write-Warning "No signing certificate supplied; this release will be unsigned. See docs/signing.md."
}

$stageRoot = Join-Path $root "dist\_package"
$stage = Join-Path $stageRoot "MI2 AIO"
if (Test-Path $stageRoot) {
    Remove-Item -Recurse -Force $stageRoot
}
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item -Path (Join-Path $dist "*") -Destination $stage -Recurse

$readme = @"
MI2 AIO $version

1. Extract this folder somewhere you can write to (for example Documents\MI2 AIO).
2. Run MI2 AIO.exe.
3. The first launch checks your setup and explains anything missing.

The app keeps settings and logs in %APPDATA%\MI2 AIO.
Do not move individual files out of this folder: MI2 AIO.exe needs _internal.

Windows SmartScreen may warn because this build is unsigned. Use
"More info" -> "Run anyway" after checking the SHA256 published with the release.

Unofficial project. Not affiliated with the Melvor Idle developers. Automation
may violate the game's terms of service; use at your own risk.
"@
Set-Content -Path (Join-Path $stage "README.txt") -Value $readme -Encoding UTF8

$zip = Join-Path $root "dist\MI2-AIO-$version-win64.zip"
if (Test-Path $zip) {
    Remove-Item -Force $zip
}
Write-Host "Packing $zip"
Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $zip
Remove-Item -Recurse -Force $stageRoot

$hash = Get-FileHash -Path $zip -Algorithm SHA256
$hashFile = Join-Path $root "dist\SHA256.txt"
"$($hash.Hash)  $(Split-Path -Leaf $zip)" | Set-Content -Path $hashFile -Encoding ASCII

Write-Host "OK: $zip"
Write-Host "SHA256: $($hash.Hash)"
Write-Host "Hashes: $hashFile"
