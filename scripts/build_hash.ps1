# Shared source fingerprint for the portable build.
# Dot-source: . .\scripts\build_hash.ps1

function Get-Mi2SourceHash {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    $items = @(
        "src",
        "data",
        "assets",
        "config\settings.default.toml",
        "pyproject.toml",
        "requirements.txt",
        "run_app.py",
        "mi2_aio.spec",
        "tools\SaveTool",
        "scripts\build_app.ps1",
        "scripts\build_savetool.ps1",
        "scripts\package_app.ps1"
    )

    $files = New-Object System.Collections.Generic.List[System.IO.FileInfo]
    foreach ($item in $items) {
        $path = Join-Path $rootPath $item
        if (Test-Path $path -PathType Container) {
            Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch "\\__pycache__\\" } |
                ForEach-Object { $files.Add($_) }
        } elseif (Test-Path $path -PathType Leaf) {
            $files.Add((Get-Item $path))
        }
    }

    $hasher = [System.Security.Cryptography.SHA256]::Create()
    $manifest = New-Object System.Text.StringBuilder
    foreach ($file in ($files | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($rootPath.Length).TrimStart('\')
        $fileHash = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
        [void]$manifest.Append($relative).Append(":").Append($fileHash).Append("`n")
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($manifest.ToString())
    return ([System.BitConverter]::ToString($hasher.ComputeHash($bytes))).Replace("-", "")
}
