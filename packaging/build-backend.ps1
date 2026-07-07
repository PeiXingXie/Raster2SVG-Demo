param(
    [string]$Python = "python",
    [string]$ProjectRoot,
    [ValidateSet("onedir", "onefile")]
    [string]$BundleMode = "onedir"
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
$BackendDist = Join-Path $Root "dist\backend"
$PyInstallerWork = Join-Path $Root "dist\pyinstaller-work"
$PyInstallerSpec = Join-Path $Root "dist\pyinstaller-spec"
$EntryPoint = Join-Path $Root "src\deepagents_template\desktop_server.py"
$StaticSource = Join-Path $Root "src\deepagents_template\static"
$PreviousPythonNoUserSite = $env:PYTHONNOUSERSITE
$env:PYTHONNOUSERSITE = "1"

Write-Host "Project root: $Root"
Write-Host "Backend dist: $BackendDist"

if (-not (Test-Path -LiteralPath $EntryPoint)) {
    throw "Desktop server entrypoint not found: $EntryPoint"
}

& $Python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed for '$Python'. Install it first with: $Python -m pip install pyinstaller"
}

New-Item -ItemType Directory -Path $BackendDist -Force | Out-Null
New-Item -ItemType Directory -Path $PyInstallerWork -Force | Out-Null
New-Item -ItemType Directory -Path $PyInstallerSpec -Force | Out-Null

try {
    $BundleFlag = if ($BundleMode -eq "onefile") { "--onefile" } else { "--onedir" }
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --name raster-svg-api `
        $BundleFlag `
        --paths (Join-Path $Root "src") `
        --add-data "$StaticSource;deepagents_template/static" `
        --distpath $BackendDist `
        --workpath $PyInstallerWork `
        --specpath $PyInstallerSpec `
        $EntryPoint

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller backend build failed."
    }
}
finally {
    $env:PYTHONNOUSERSITE = $PreviousPythonNoUserSite
}

$BackendExe = if ($BundleMode -eq "onefile") {
    Join-Path $BackendDist "raster-svg-api.exe"
} else {
    Join-Path $BackendDist "raster-svg-api\raster-svg-api.exe"
}
if (-not (Test-Path -LiteralPath $BackendExe)) {
    throw "Expected backend executable was not produced: $BackendExe"
}

Write-Host "Backend executable created: $BackendExe"
