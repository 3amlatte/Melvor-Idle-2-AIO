# Rebuild dist\MI2 AIO only when the source changed since the last package.
param(
    [switch]$Launch,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "build_hash.ps1")

$dist = Join-Path $root "dist\MI2 AIO"
$exe = Join-Path $dist "MI2 AIO.exe"
$stamp = Join-Path $dist "build-info.json"

$currentHash = Get-Mi2SourceHash -Root $root
$info = $null
if ((Test-Path $exe) -and (Test-Path $stamp)) {
    try {
        $info = Get-Content $stamp -Raw | ConvertFrom-Json
    } catch {
        $info = $null
    }
}

$stale = (-not $info) -or ($info.source_hash -ne $currentHash) -or (-not (Test-Path $exe))
if ($stale) {
    if (-not $info) {
        Write-Host "No dist build stamp found; a build is required."
    } else {
        Write-Host "Source changed since dist $($info.version); a rebuild is required."
    }
    if ($CheckOnly) {
        Write-Host "STALE"
        exit 1
    }
    & (Join-Path $PSScriptRoot "package_app.ps1")
} else {
    Write-Host "dist is up to date (version $($info.version))."
    if ($CheckOnly) {
        exit 0
    }
}

if ($Launch) {
    Start-Process -FilePath $exe -WorkingDirectory $dist
}
