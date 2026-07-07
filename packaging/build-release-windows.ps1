param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
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

& (Join-Path $PSScriptRoot "set-version.ps1") -Version $Version -ProjectRoot $ProjectRoot

& (Join-Path $PSScriptRoot "build-windows-installer.ps1") `
    -Python $Python `
    -SkipNpmInstall:$SkipNpmInstall `
    -SkipPackageVenv:$SkipPackageVenv `
    -RecreatePackageVenv:$RecreatePackageVenv `
    -BundleMode $BundleMode

$InstallerPath = Join-Path $ProjectRoot "dist\installers\Raster to SVG Setup $Version.exe"
if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Expected versioned installer not found: $InstallerPath"
}

Write-Host "Release installer ready: $InstallerPath"
