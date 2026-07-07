param(
    [string]$Python = "python",
    [string]$ProjectRoot,
    [string]$VenvPath,
    [switch]$Recreate
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
if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    $VenvPath = Join-Path $Root ".venv_package"
}

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

if ($Recreate -and (Test-Path -LiteralPath $VenvPath)) {
    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
    $resolvedVenv = (Resolve-Path -LiteralPath $VenvPath).Path
    if (-not $resolvedVenv.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to recreate venv outside project root: $resolvedVenv"
    }
    Remove-Item -LiteralPath $VenvPath -Recurse -Force
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Creating package venv: $VenvPath"
    & $Python -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create package venv with '$Python'."
    }
}

Write-Host "Installing runtime packaging dependencies into: $VenvPath"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}

& $VenvPython -m pip install -e $Root
if ($LASTEXITCODE -ne 0) {
    throw "Runtime dependency install failed."
}

& $VenvPython -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller install failed."
}

Write-Host "Package venv ready."
Write-Host "Python: $VenvPython"
