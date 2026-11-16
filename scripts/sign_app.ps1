param(
    [string]$Root = "",
    [string]$Thumbprint = "",
    [string]$PfxPath = "",
    [string]$PfxPassword = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$SignTool = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Root) {
    $Root = Join-Path $projectRoot "dist\MI2 AIO"
}
if (-not (Test-Path $Root)) {
    throw "Build output not found: $Root"
}
if (-not $Thumbprint -and -not $PfxPath) {
    throw "Provide -Thumbprint (certificate in the Windows store) or -PfxPath (test/self-signed certificate)."
}

if (-not $SignTool) {
    $kits = "C:\Program Files (x86)\Windows Kits\10\bin"
    if (Test-Path $kits) {
        $SignTool = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $SignTool -or -not (Test-Path $SignTool)) {
    throw "signtool.exe was not found. Install the Windows SDK signing tools, or pass -SignTool <path>."
}

$files = @(
    (Join-Path $Root "MI2 AIO.exe"),
    (Join-Path $Root "_internal\tools\bin\SaveTool.exe")
) | Where-Object { Test-Path $_ }

if (-not $files) {
    throw "No MI2 AIO executables found under $Root."
}

foreach ($file in $files) {
    $arguments = @(
        "sign",
        "/fd", "SHA256",
        "/td", "SHA256",
        "/tr", $TimestampUrl
    )
    if ($Thumbprint) {
        $arguments += @("/sha1", $Thumbprint)
    }
    if ($PfxPath) {
        $arguments += @("/f", $PfxPath)
        if ($PfxPassword) {
            $arguments += @("/p", $PfxPassword)
        }
    }
    $arguments += $file

    Write-Host "Signing $file"
    & $SignTool @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Signing failed for $file (signtool exit $LASTEXITCODE)."
    }

    & $SignTool verify /pa /v $file
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed for $file (signtool exit $LASTEXITCODE)."
    }
}

Write-Host "Signed and verified $($files.Count) executable(s)."
Write-Host "Sign before creating the release zip; re-zipping does not change the signatures."
