param(
    [switch]$SkipNpmInstall,
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ProjectRoot {
    if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
        return (Resolve-Path -LiteralPath $ProjectRoot).Path
    }
    if ($PSScriptRoot) {
        return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
    }
    return (Get-Location).Path
}

$Root = Get-ProjectRoot
$DesktopRoot = Join-Path $Root "desktop"
$BackendExeCandidates = @(
    (Join-Path $Root "dist\backend\raster-svg-api\raster-svg-api.exe"),
    (Join-Path $Root "dist\backend\raster-svg-api.exe")
)
$BackendExe = $BackendExeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if ([string]::IsNullOrWhiteSpace($BackendExe)) {
    throw "Packaged backend not found. Build it first. Checked: $($BackendExeCandidates -join ', ')"
}
Write-Host "Packaged backend: $BackendExe"

Push-Location $DesktopRoot
try {
    if (-not $SkipNpmInstall) {
        npm.cmd install
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed."
        }
    }

    npm.cmd run dist -- --win
    if ($LASTEXITCODE -ne 0) {
        throw "electron-builder failed."
    }
}
finally {
    Pop-Location
}

Write-Host "Installer output directory: $(Join-Path $Root "dist\installers")"
