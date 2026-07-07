param(
    [string]$NodeExe,
    [string]$NpmCmd
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-DesktopRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path $PSScriptRoot).Path
    }
    return (Get-Location).Path
}

function Resolve-ExistingPath {
    param(
        [string[]]$Candidates
    )

    foreach ($candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

function Resolve-CommandPath {
    param(
        [string]$Name
    )

    try {
        $command = Get-Command $Name -ErrorAction Stop
        return $command.Source
    } catch {
        return $null
    }
}

function Get-NodeVersionText {
    param(
        [string]$NodePath
    )

    $versionText = & $NodePath -p "process.versions.node"
    if ($LASTEXITCODE -ne 0) {
        throw "Node runtime failed to run."
    }
    return ($versionText | Select-Object -First 1).Trim()
}

function Test-ElectronInstallHealthy {
    param(
        [string]$DesktopPath
    )

    $electronPackageDir = Join-Path $DesktopPath "node_modules\electron"
    $electronPathFile = Join-Path $electronPackageDir "path.txt"
    $electronLaunchers = @(
        Join-Path $DesktopPath "node_modules\.bin\electron.cmd"
        Join-Path $DesktopPath "node_modules\.bin\electron.ps1"
        Join-Path $DesktopPath "node_modules\.bin\electron"
    )

    if (-not (Test-Path -LiteralPath $electronPackageDir)) {
        return $false
    }
    if (-not (Test-Path -LiteralPath $electronPathFile)) {
        return $false
    }

    $pathFileValue = (Get-Content -LiteralPath $electronPathFile -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($pathFileValue)) {
        return $false
    }

    $electronBinaryPath = Join-Path $electronPackageDir ("dist\" + $pathFileValue)
    if (-not (Test-Path -LiteralPath $electronBinaryPath)) {
        return $false
    }

    foreach ($launcher in $electronLaunchers) {
        if (Test-Path -LiteralPath $launcher) {
            return $true
        }
    }

    return $false
}

function Remove-ElectronInstallArtifacts {
    param(
        [string]$DesktopPath
    )

    $pathsToRemove = @(
        (Join-Path $DesktopPath "node_modules\electron")
        (Join-Path $DesktopPath "node_modules\.bin\electron")
        (Join-Path $DesktopPath "node_modules\.bin\electron.cmd")
        (Join-Path $DesktopPath "node_modules\.bin\electron.ps1")
    )

    foreach ($targetPath in $pathsToRemove) {
        if (Test-Path -LiteralPath $targetPath) {
            Remove-Item -LiteralPath $targetPath -Recurse -Force
        }
    }
}

function Repair-ElectronFromLocalCache {
    param(
        [string]$DesktopPath
    )

    $electronPackageJsonPath = Join-Path $DesktopPath "node_modules\electron\package.json"
    $electronPackageDir = Join-Path $DesktopPath "node_modules\electron"
    $electronDistDir = Join-Path $electronPackageDir "dist"
    $electronPathFile = Join-Path $electronPackageDir "path.txt"

    if (-not (Test-Path -LiteralPath $electronPackageJsonPath)) {
        return $false
    }

    $packageJson = Get-Content -LiteralPath $electronPackageJsonPath -Raw | ConvertFrom-Json
    $electronVersion = $packageJson.version
    if ([string]::IsNullOrWhiteSpace($electronVersion)) {
        return $false
    }

    $cacheRoot = Join-Path $env:LOCALAPPDATA "electron\Cache"
    if (-not (Test-Path -LiteralPath $cacheRoot)) {
        return $false
    }

    $zipPattern = "electron-v$electronVersion-win32-x64.zip"
    $zipFile = Get-ChildItem -Path $cacheRoot -Recurse -Filter $zipPattern -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $zipFile) {
        return $false
    }

    if (Test-Path -LiteralPath $electronDistDir) {
        Remove-Item -LiteralPath $electronDistDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $electronDistDir -Force | Out-Null

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($zipFile.FullName, $electronDistDir)
    } catch {
        return $false
    }

    [System.IO.File]::WriteAllText($electronPathFile, "electron.exe", [System.Text.Encoding]::ASCII)
    return $true
}

function Add-DirectoryToPath {
    param(
        [string]$DirectoryPath
    )

    if ([string]::IsNullOrWhiteSpace($DirectoryPath)) {
        return
    }

    if (-not (Test-Path -LiteralPath $DirectoryPath)) {
        return
    }

    $currentPathEntries = @()
    if (-not [string]::IsNullOrWhiteSpace($env:PATH)) {
        $currentPathEntries = $env:PATH -split ';'
    }

    foreach ($entry in $currentPathEntries) {
        if ($entry -eq $DirectoryPath) {
            return
        }
    }

    if ([string]::IsNullOrWhiteSpace($env:PATH)) {
        $env:PATH = $DirectoryPath
    } else {
        $env:PATH = "$DirectoryPath;$($env:PATH)"
    }
}

$DesktopRoot = Get-DesktopRoot
$ProjectRoot = Split-Path -Parent $DesktopRoot
$NodeModulesDir = Join-Path $DesktopRoot "node_modules"
$ElectronMarker = Join-Path $NodeModulesDir "electron"
$VendorNodeExe = Join-Path $DesktopRoot "runtime\node\node.exe"
$VendorNpmCmd = Join-Path $DesktopRoot "runtime\node\npm.cmd"
$WindowsNodeExeCandidates = @(
    "C:\Program Files\nodejs\node.exe"
    "C:\Program Files (x86)\nodejs\node.exe"
)
$WindowsNpmCmdCandidates = @(
    "C:\Program Files\nodejs\npm.cmd"
    "C:\Program Files (x86)\nodejs\npm.cmd"
)

$resolvedNodeExe = Resolve-ExistingPath @(
    $NodeExe,
    $env:DESKTOP_NODE_EXE,
    $VendorNodeExe
)
if (-not $resolvedNodeExe) {
    $resolvedNodeExe = Resolve-CommandPath "node"
}
if (-not $resolvedNodeExe) {
    $resolvedNodeExe = Resolve-ExistingPath $WindowsNodeExeCandidates
}

$resolvedNpmCmd = Resolve-ExistingPath @(
    $NpmCmd,
    $env:DESKTOP_NPM_CMD,
    $VendorNpmCmd
)
if (-not $resolvedNpmCmd) {
    $resolvedNpmCmd = Resolve-CommandPath "npm"
}
if (-not $resolvedNpmCmd) {
    $resolvedNpmCmd = Resolve-ExistingPath $WindowsNpmCmdCandidates
}

Write-Host "Desktop root: $DesktopRoot"
Write-Host "Project root: $ProjectRoot"
$nodeDisplay = if ($resolvedNodeExe) { $resolvedNodeExe } else { "<not found>" }
$npmDisplay = if ($resolvedNpmCmd) { $resolvedNpmCmd } else { "<not found>" }
Write-Host "Node runtime: $nodeDisplay"
Write-Host "npm command: $npmDisplay"

if (-not (Test-Path -LiteralPath (Join-Path $DesktopRoot "package.json"))) {
    throw "desktop/package.json is missing."
}

if (Test-ElectronInstallHealthy -DesktopPath $DesktopRoot) {
    Write-Host "Electron dependency already present."
    exit 0
}

if (-not $resolvedNodeExe) {
    throw "Node.js runtime not found. Restart the terminal after installing Node.js, package a runtime under desktop/runtime/node, or pass -NodeExe."
}

if (-not $resolvedNpmCmd) {
    throw "npm not found. Restart the terminal after installing Node.js, package desktop/node_modules ahead of time, or provide a runtime with npm.cmd."
}

Push-Location $DesktopRoot
try {
    $nodeVersionText = Get-NodeVersionText -NodePath $resolvedNodeExe
    $nodeBinDir = Split-Path -Parent $resolvedNodeExe
    Add-DirectoryToPath -DirectoryPath $nodeBinDir
    Write-Host "Detected Node.js: v$nodeVersionText"
    Write-Host "Node bin directory added to PATH: $nodeBinDir"
    if ([version]$nodeVersionText -lt [version]"20.0.0") {
        throw "Node.js 20 or newer is required for the desktop shell. Detected version: v$nodeVersionText"
    }

    $attemptedRepair = $false
    if (Test-Path -LiteralPath $ElectronMarker) {
        Write-Warning "Detected an incomplete Electron installation. Attempting npm rebuild electron to repair it..."
        & $resolvedNpmCmd rebuild electron
        if ($LASTEXITCODE -ne 0) {
            throw "npm rebuild electron failed with exit code $LASTEXITCODE."
        }
    } else {
        Write-Host "Installing desktop dependencies..."
        & $resolvedNpmCmd install --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed with exit code $LASTEXITCODE."
        }
    }

    if (-not (Test-ElectronInstallHealthy -DesktopPath $DesktopRoot)) {
        $attemptedRepair = $true
        Write-Warning "Electron install is still incomplete after the first bootstrap pass. Cleaning Electron artifacts and retrying a fresh install..."
        Remove-ElectronInstallArtifacts -DesktopPath $DesktopRoot
        & $resolvedNpmCmd install --no-fund --no-audit
        if ($LASTEXITCODE -ne 0) {
            throw "npm install failed during Electron repair with exit code $LASTEXITCODE."
        }
    }

    if (-not (Test-ElectronInstallHealthy -DesktopPath $DesktopRoot)) {
        Write-Warning "npm-based Electron install is still incomplete. Attempting to repair Electron from the local cache..."
        $cacheRepairSucceeded = Repair-ElectronFromLocalCache -DesktopPath $DesktopRoot
        if ($cacheRepairSucceeded -and (Test-ElectronInstallHealthy -DesktopPath $DesktopRoot)) {
            Write-Host "Electron cache repair succeeded."
        }
    }

    if (-not (Test-ElectronInstallHealthy -DesktopPath $DesktopRoot)) {
        if ($attemptedRepair) {
            throw "Electron install is still incomplete after automatic repair. This is usually caused by a broken cached Electron download, antivirus/file-lock interference, or a partial unzip. Delete desktop/node_modules and rerun desktop bootstrap. If it still fails, clear the Electron/npm cache and try again."
        }
        throw "Electron install is incomplete after bootstrap. Delete desktop/node_modules/electron and rerun desktop bootstrap."
    }

    Write-Host "Electron install verified."
    Write-Host "Desktop bootstrap completed."
}
finally {
    Pop-Location
}
