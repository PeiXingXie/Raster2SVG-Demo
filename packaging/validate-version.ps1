param(
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
$DesktopPackagePath = Join-Path $Root "desktop\package.json"
$DesktopLockPath = Join-Path $Root "desktop\package-lock.json"
$PyprojectPath = Join-Path $Root "pyproject.toml"

$DesktopPackage = Get-Content -Raw -LiteralPath $DesktopPackagePath | ConvertFrom-Json
$DesktopVersion = [string]$DesktopPackage.version

$PyprojectText = Get-Content -Raw -LiteralPath $PyprojectPath
$PyprojectMatch = [regex]::Match($PyprojectText, '(?m)^version\s*=\s*"([^"]+)"')
if (-not $PyprojectMatch.Success) {
    throw "Could not find [project] version in pyproject.toml."
}
$PyprojectVersion = $PyprojectMatch.Groups[1].Value

if ($DesktopVersion -ne $PyprojectVersion) {
    throw "Version mismatch: desktop/package.json=$DesktopVersion pyproject.toml=$PyprojectVersion"
}

if (Test-Path -LiteralPath $DesktopLockPath) {
    $DesktopLockText = Get-Content -Raw -LiteralPath $DesktopLockPath
    $LockVersionMatch = [regex]::Match(
        $DesktopLockText,
        '"name"\s*:\s*"raster-svg-desktop-client",\s*\r?\n\s*"version"\s*:\s*"([^"]+)"'
    )
    if (-not $LockVersionMatch.Success) {
        throw "Could not find top-level version in desktop/package-lock.json."
    }
    $LockVersion = $LockVersionMatch.Groups[1].Value
    if ($LockVersion -ne $DesktopVersion) {
        throw "Version mismatch: desktop/package-lock.json=$LockVersion desktop/package.json=$DesktopVersion"
    }

    $LockRootVersionMatch = [regex]::Match(
        $DesktopLockText,
        '""\s*:\s*\{\s*\r?\n\s*"name"\s*:\s*"raster-svg-desktop-client",\s*\r?\n\s*"version"\s*:\s*"([^"]+)"'
    )
    if (-not $LockRootVersionMatch.Success) {
        throw "Could not find packages[''].version in desktop/package-lock.json."
    }
    $LockRootVersion = $LockRootVersionMatch.Groups[1].Value
    if ($LockRootVersion -ne $DesktopVersion) {
        throw "Version mismatch: desktop/package-lock.json packages[''].version=$LockRootVersion desktop/package.json=$DesktopVersion"
    }
}

if ($DesktopPackage.build.appId -ne "com.local.rastertosvg") {
    throw "Unexpected appId '$($DesktopPackage.build.appId)'. Keep appId stable for overwrite updates."
}

if ($DesktopPackage.build.productName -ne "Raster to SVG") {
    throw "Unexpected productName '$($DesktopPackage.build.productName)'. Keep productName stable for overwrite updates."
}

Write-Host "Version metadata OK: $DesktopVersion"
Write-Host "Stable appId: $($DesktopPackage.build.appId)"
Write-Host "Stable productName: $($DesktopPackage.build.productName)"
