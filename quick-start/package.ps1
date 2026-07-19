param(
    [string]$OutputRoot,
    [string]$PackageName,
    [string]$Timestamp,
    [switch]$IncludeEnv,
    [switch]$IncludeArtifacts,
    [switch]$IncludeRuntimeOverrides
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ProjectRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
    return (Get-Location).Path
}

function Copy-OptionalPath {
    param(
        [string]$SourcePath,
        [string]$TargetPath
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        Write-Host "Skipping missing path: $SourcePath"
        return
    }

    $targetParent = Split-Path -Parent $TargetPath
    if ($targetParent) {
        New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
    }
    Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Recurse -Force
}

function Remove-PackagingCaches {
    param(
        [string]$StageDir
    )

    $DirectoryNames = @("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")
    foreach ($DirectoryName in $DirectoryNames) {
        Get-ChildItem -LiteralPath $StageDir -Recurse -Force -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq $DirectoryName } |
            Remove-Item -Recurse -Force
    }

    $FilePatterns = @("*.pyc", "*.pyo", "*.pyd", "*.log")
    foreach ($Pattern in $FilePatterns) {
        Get-ChildItem -LiteralPath $StageDir -Recurse -Force -File -Filter $Pattern -ErrorAction SilentlyContinue |
            Remove-Item -Force
    }
}

function Copy-DesktopSource {
    param(
        [string]$ProjectRoot,
        [string]$StageDir
    )

    $DesktopSource = Join-Path $ProjectRoot "desktop"
    $DesktopStage = Join-Path $StageDir "desktop"

    $DesktopItems = @(
        "assets\icon.png",
        "assets\icon.ico",
        "bootstrap.bat",
        "bootstrap.ps1",
        "bootstrap.sh",
        "main.js",
        "package-lock.json",
        "package.json",
        "preload.js",
        "README.desktop.md",
        "start-desktop.bat",
        "start-desktop.ps1",
        "start-desktop.sh"
    )

    foreach ($Item in $DesktopItems) {
        Copy-OptionalPath (Join-Path $DesktopSource $Item) (Join-Path $DesktopStage $Item)
    }
}

$ProjectRoot = Get-ProjectRoot
$ProjectName = Split-Path -Leaf $ProjectRoot

if ([string]::IsNullOrWhiteSpace($Timestamp)) {
    $Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
}
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $ProjectRoot "dist\deploy-packages"
}
if ([string]::IsNullOrWhiteSpace($PackageName)) {
    $PackageName = "$ProjectName-deploy-$Timestamp"
}

$StageDir = Join-Path $OutputRoot $PackageName
$ArchivePath = Join-Path $OutputRoot "$PackageName.zip"

if ((Test-Path -LiteralPath $StageDir) -or (Test-Path -LiteralPath $ArchivePath)) {
    throw "Target package already exists. StageDir=$StageDir Archive=$ArchivePath"
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

Write-Host "Project root: $ProjectRoot"
Write-Host "Output root:  $OutputRoot"
Write-Host "Package name: $PackageName"

Copy-OptionalPath (Join-Path $ProjectRoot "src") (Join-Path $StageDir "src")
Copy-DesktopSource -ProjectRoot $ProjectRoot -StageDir $StageDir
Copy-OptionalPath (Join-Path $ProjectRoot "quick-start") (Join-Path $StageDir "quick-start")
Copy-OptionalPath (Join-Path $ProjectRoot "architecture-summary") (Join-Path $StageDir "architecture-summary")
Copy-OptionalPath (Join-Path $ProjectRoot "packaging\README.packaging.md") (Join-Path $StageDir "packaging\README.packaging.md")
Copy-OptionalPath (Join-Path $ProjectRoot "pyproject.toml") (Join-Path $StageDir "pyproject.toml")
Copy-OptionalPath (Join-Path $ProjectRoot "README.md") (Join-Path $StageDir "README.md")
Copy-OptionalPath (Join-Path $ProjectRoot "README.developer.md") (Join-Path $StageDir "README.developer.md")
Copy-OptionalPath (Join-Path $ProjectRoot "RELEASE_NOTES.md") (Join-Path $StageDir "RELEASE_NOTES.md")
Copy-OptionalPath (Join-Path $ProjectRoot "docs.development.md") (Join-Path $StageDir "docs.development.md")
Copy-OptionalPath (Join-Path $ProjectRoot "docs.installer.md") (Join-Path $StageDir "docs.installer.md")
Copy-OptionalPath (Join-Path $ProjectRoot "docs.settings-mapping.md") (Join-Path $StageDir "docs.settings-mapping.md")
Copy-OptionalPath (Join-Path $ProjectRoot ".env.example") (Join-Path $StageDir ".env.example")
Copy-OptionalPath (Join-Path $ProjectRoot "environment.yml") (Join-Path $StageDir "environment.yml")
Copy-OptionalPath (Join-Path $ProjectRoot "start-dev.ps1") (Join-Path $StageDir "start-dev.ps1")
Copy-OptionalPath (Join-Path $ProjectRoot "start-dev.bat") (Join-Path $StageDir "start-dev.bat")
Copy-OptionalPath (Join-Path $ProjectRoot "start-dev.sh") (Join-Path $StageDir "start-dev.sh")
Copy-OptionalPath (Join-Path $ProjectRoot "start-service.ps1") (Join-Path $StageDir "start-service.ps1")
Copy-OptionalPath (Join-Path $ProjectRoot "start-service.bat") (Join-Path $StageDir "start-service.bat")
Copy-OptionalPath (Join-Path $ProjectRoot "stop-dev.ps1") (Join-Path $StageDir "stop-dev.ps1")

if ($IncludeEnv.IsPresent -and (Test-Path -LiteralPath (Join-Path $ProjectRoot ".env"))) {
    Copy-OptionalPath (Join-Path $ProjectRoot ".env") (Join-Path $StageDir ".env")
    Write-Host "Included .env"
} else {
    Write-Host "Skipped .env"
}

if ($IncludeArtifacts.IsPresent -and (Test-Path -LiteralPath (Join-Path $ProjectRoot "artifacts"))) {
    Copy-OptionalPath (Join-Path $ProjectRoot "artifacts") (Join-Path $StageDir "artifacts")
    Write-Host "Included artifacts/"
} else {
    Write-Host "Skipped artifacts/"
}

if ($IncludeRuntimeOverrides.IsPresent -and (Test-Path -LiteralPath (Join-Path $ProjectRoot ".frontend_runtime_overrides.json"))) {
    Copy-OptionalPath (Join-Path $ProjectRoot ".frontend_runtime_overrides.json") (Join-Path $StageDir ".frontend_runtime_overrides.json")
    Write-Host "Included .frontend_runtime_overrides.json"
} else {
    Write-Host "Skipped .frontend_runtime_overrides.json"
}

$InfoFile = Join-Path $StageDir "DEPLOY_PACKAGE_INFO.txt"
@"
Package: $PackageName
Created At: $(Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Project Root: $ProjectRoot
Included .env: $($IncludeEnv.IsPresent)
Included artifacts: $($IncludeArtifacts.IsPresent)
Included runtime overrides: $($IncludeRuntimeOverrides.IsPresent)

Quick start on Windows:
  powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
  cd quick-start
  powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
  powershell -ExecutionPolicy Bypass -File .\start-api.ps1
  powershell -ExecutionPolicy Bypass -File ..\desktop\start-desktop.ps1

Quick start on Linux/macOS:
  ./start-dev.sh
  cd quick-start
  chmod +x bootstrap.sh start-api.sh
  ./bootstrap.sh
  ./start-api.sh
  ../desktop/start-desktop.sh
"@ | Set-Content -LiteralPath $InfoFile -Encoding UTF8

Remove-PackagingCaches -StageDir $StageDir

Compress-Archive -LiteralPath $StageDir -DestinationPath $ArchivePath -CompressionLevel Optimal

Write-Host "Deployment package created."
Write-Host "Stage directory: $StageDir"
Write-Host "Archive file:    $ArchivePath"
