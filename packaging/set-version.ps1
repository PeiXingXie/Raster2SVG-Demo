param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
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

if ($Version -notmatch '^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$') {
    throw "Version must look like 0.1.1 or 0.2.0-beta.1. Received: $Version"
}

$Root = Get-ProjectRoot
$DesktopPackagePath = Join-Path $Root "desktop\package.json"
$DesktopLockPath = Join-Path $Root "desktop\package-lock.json"
$PyprojectPath = Join-Path $Root "pyproject.toml"

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

function Replace-Once {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text,
        [Parameter(Mandatory = $true)]
        [string]$Pattern,
        [Parameter(Mandatory = $true)]
        [string]$Replacement,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not [regex]::IsMatch($Text, $Pattern)) {
        throw "Failed to find $Description."
    }

    $Updated = [regex]::Replace($Text, $Pattern, $Replacement, 1)
    return $Updated
}

$DesktopPackageText = Get-Content -Raw -LiteralPath $DesktopPackagePath
$DesktopPackageText = Replace-Once `
    -Text $DesktopPackageText `
    -Pattern '("version"\s*:\s*")[^"]+(")' `
    -Replacement "`${1}$Version`${2}" `
    -Description "desktop/package.json version"
Write-Utf8NoBom -Path $DesktopPackagePath -Text $DesktopPackageText

# Validate JSON after the text-preserving update.
Get-Content -Raw -LiteralPath $DesktopPackagePath | ConvertFrom-Json | Out-Null

if (Test-Path -LiteralPath $DesktopLockPath) {
    $DesktopLockText = Get-Content -Raw -LiteralPath $DesktopLockPath
    $DesktopLockText = Replace-Once `
        -Text $DesktopLockText `
        -Pattern '("name"\s*:\s*"raster-svg-desktop-client",\s*\r?\n\s*"version"\s*:\s*")[^"]+(")' `
        -Replacement "`${1}$Version`${2}" `
        -Description "desktop/package-lock.json top-level version"
    $DesktopLockText = Replace-Once `
        -Text $DesktopLockText `
        -Pattern '(""\s*:\s*\{\s*\r?\n\s*"name"\s*:\s*"raster-svg-desktop-client",\s*\r?\n\s*"version"\s*:\s*")[^"]+(")' `
        -Replacement "`${1}$Version`${2}" `
        -Description "desktop/package-lock.json root package version"
    Write-Utf8NoBom -Path $DesktopLockPath -Text $DesktopLockText
}

$PyprojectText = Get-Content -Raw -LiteralPath $PyprojectPath
$UpdatedPyproject = [regex]::Replace(
    $PyprojectText,
    '(?m)^version\s*=\s*"[^"]+"',
    "version = `"$Version`"",
    1
)
if ($UpdatedPyproject -eq $PyprojectText -and $PyprojectText -notmatch "version = `"$Version`"") {
    throw "Failed to update version in pyproject.toml."
}
Write-Utf8NoBom -Path $PyprojectPath -Text $UpdatedPyproject

& (Join-Path $PSScriptRoot "validate-version.ps1") -ProjectRoot $Root

Write-Host "Version set to $Version"
