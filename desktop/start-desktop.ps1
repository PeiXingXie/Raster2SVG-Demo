param(
    [string]$FrontendUrl,
    [switch]$SkipBootstrap
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-DesktopRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path $PSScriptRoot).Path
    }
    return (Get-Location).Path
}

function Get-DotEnvValue {
    param(
        [string]$FilePath,
        [string]$Key
    )

    if (-not (Test-Path -LiteralPath $FilePath)) {
        return $null
    }

    foreach ($line in Get-Content -LiteralPath $FilePath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed -split "=", 2
        if ($parts.Count -eq 2 -and $parts[0].Trim() -eq $Key) {
            return $parts[1].Trim()
        }
    }

    return $null
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

function Test-ElectronInstallHealthy {
    param(
        [string]$DesktopPath
    )

    $electronPackageDir = Join-Path $DesktopPath "node_modules\electron"
    $electronPathFile = Join-Path $electronPackageDir "path.txt"

    if (-not (Test-Path -LiteralPath $electronPackageDir)) {
        return $false
    }

    return (Test-Path -LiteralPath $electronPathFile)
}

function Wait-BackendHealth {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSeconds = 20,
        [int]$PollIntervalMilliseconds = 1000
    )

    $healthUrl = $BaseUrl.TrimEnd("/") + "/health"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $attempt = 0

    while ((Get-Date) -lt $deadline) {
        $attempt += 1
        try {
            Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3 | Out-Null
            Write-Host "Backend health check passed: $BaseUrl"
            return $true
        } catch {
            if ($attempt -eq 1) {
                Write-Host "Waiting for backend health at $healthUrl ..."
            }
            Start-Sleep -Milliseconds $PollIntervalMilliseconds
        }
    }

    Write-Warning "Backend health check failed for $BaseUrl after ${TimeoutSeconds}s. Start the FastAPI service first and verify $healthUrl in a browser."
    return $false
}

function Resolve-ServiceUrl {
    param(
        [string]$Url
    )

    try {
        $uri = [System.Uri]$Url
        return "$($uri.Scheme)://$($uri.Authority)/"
    } catch {
        return $Url
    }
}

$DesktopRoot = Get-DesktopRoot
$ProjectRoot = Split-Path -Parent $DesktopRoot
$RuntimeEnvFile = Join-Path $ProjectRoot ".runtime_startup.env"
$EnvFile = Join-Path $ProjectRoot ".env"

if ([string]::IsNullOrWhiteSpace($FrontendUrl)) {
    $FrontendUrl = $env:RASTER_SVG_FRONTEND_URL
}
if ([string]::IsNullOrWhiteSpace($FrontendUrl)) {
    $configSource = "built-in default"
    $host = $null
    $port = $null
    foreach ($candidateFile in @($RuntimeEnvFile, $EnvFile)) {
        if (-not (Test-Path -LiteralPath $candidateFile)) {
            continue
        }

        $host = Get-DotEnvValue -FilePath $candidateFile -Key "APP_HOST"
        $port = Get-DotEnvValue -FilePath $candidateFile -Key "APP_PORT"
        $configSource = $candidateFile
        if (-not [string]::IsNullOrWhiteSpace($host) -or -not [string]::IsNullOrWhiteSpace($port)) {
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($host)) {
        $host = "127.0.0.1"
    }
    if ([string]::IsNullOrWhiteSpace($port)) {
        $port = "8120"
    }
    $FrontendUrl = "http://$host`:$port/"
    Write-Host "Frontend URL source: $configSource"
}

if (-not $SkipBootstrap) {
    & (Join-Path $DesktopRoot "bootstrap.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop bootstrap failed."
    }
}

if (-not (Test-ElectronInstallHealthy -DesktopPath $DesktopRoot)) {
    throw "Electron installation is incomplete. Rerun desktop bootstrap to repair it, or delete desktop/node_modules/electron and install again."
}

$WindowsNodeBinDir = Resolve-ExistingPath @(
    "C:\Program Files\nodejs"
    "C:\Program Files (x86)\nodejs"
)
if ($WindowsNodeBinDir) {
    Add-DirectoryToPath -DirectoryPath $WindowsNodeBinDir
}

$ElectronCommand = Resolve-ExistingPath @(
    (Join-Path $DesktopRoot "node_modules\electron\dist\electron.exe")
    (Join-Path $DesktopRoot "node_modules\.bin\electron.cmd")
    (Join-Path $DesktopRoot "node_modules\.bin\electron.ps1")
)
if (-not $ElectronCommand) {
    throw "Electron launch command not found under desktop/node_modules. Run desktop bootstrap first and confirm Electron was installed correctly."
}

$ServiceUrl = Resolve-ServiceUrl -Url $FrontendUrl
if (-not (Wait-BackendHealth -BaseUrl $ServiceUrl)) {
    throw "Backend health check failed for $ServiceUrl. Desktop shell startup aborted."
}

Push-Location $DesktopRoot
try {
    $env:RASTER_SVG_FRONTEND_URL = $FrontendUrl
    Write-Host "Electron launch command: $ElectronCommand"
    Write-Host "Launching desktop shell against $FrontendUrl"
    & $ElectronCommand .
    if ($LASTEXITCODE -ne 0) {
        throw "Electron exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
