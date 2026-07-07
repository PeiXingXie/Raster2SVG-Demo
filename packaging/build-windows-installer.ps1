param(
    [string]$Python = "python",
    [switch]$SkipNpmInstall,
    [switch]$SkipPackageVenv,
    [switch]$RecreatePackageVenv,
    [ValidateSet("onedir", "onefile")]
    [string]$BundleMode = "onedir"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

Write-Host "Building Windows installer MVP..."
Write-Host "Project root: $ProjectRoot"

& (Join-Path $PSScriptRoot "validate-version.ps1") -ProjectRoot $ProjectRoot

$PackageVenvPython = Join-Path $ProjectRoot ".venv_package\Scripts\python.exe"
if (-not $SkipPackageVenv) {
    & (Join-Path $PSScriptRoot "prepare-package-venv.ps1") `
        -Python $Python `
        -ProjectRoot $ProjectRoot `
        -Recreate:$RecreatePackageVenv
    $Python = $PackageVenvPython
}

& (Join-Path $PSScriptRoot "build-backend.ps1") `
    -Python $Python `
    -ProjectRoot $ProjectRoot `
    -BundleMode $BundleMode

& (Join-Path $PSScriptRoot "build-desktop.ps1") -ProjectRoot $ProjectRoot -SkipNpmInstall:$SkipNpmInstall

Write-Host "Windows installer build completed."
