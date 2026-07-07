param(
    [string]$SessionFile,
    [int]$TimeoutSeconds = 15
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ProjectRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path $PSScriptRoot).Path
    }
    return (Get-Location).Path
}

function Test-ProcessRunning {
    param(
        [int]$ProcessId
    )

    if ($ProcessId -le 0) {
        return $false
    }

    try {
        $null = Get-Process -Id $ProcessId -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Wait-ProcessExit {
    param(
        [int]$ProcessId,
        [int]$TimeoutSeconds
    )

    if ($ProcessId -le 0) {
        return $true
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-ProcessRunning -ProcessId $ProcessId)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    return -not (Test-ProcessRunning -ProcessId $ProcessId)
}

function Wait-PortReleased {
    param(
        [int]$Port,
        [int]$TimeoutSeconds
    )

    if ($Port -le 0) {
        return $true
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
        } catch {
            return $true
        }
        if ($listeners.Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }

    try {
        return @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        ).Count -eq 0
    } catch {
        return $true
    }
}

function Invoke-DevShutdownEndpoint {
    param(
        [string]$BaseUrl,
        [string]$Token
    )

    if ([string]::IsNullOrWhiteSpace($BaseUrl) -or [string]::IsNullOrWhiteSpace($Token)) {
        return $false
    }

    $shutdownUrl = $BaseUrl.TrimEnd("/") + "/dev/shutdown"
    try {
        Invoke-WebRequest `
            -Uri $shutdownUrl `
            -Method Post `
            -Headers @{ "X-Dev-Shutdown-Token" = $Token } `
            -UseBasicParsing `
            -TimeoutSec 5 | Out-Null
        return $true
    } catch {
        Write-Warning "Graceful shutdown endpoint call failed for $shutdownUrl. Falling back to process stop."
        return $false
    }
}

function Stop-ProcessIfRunning {
    param(
        [int]$ProcessId,
        [string]$Label
    )

    if (-not (Test-ProcessRunning -ProcessId $ProcessId)) {
        return
    }

    Write-Host "Stopping $Label process $ProcessId..."
    try {
        taskkill /PID $ProcessId /T /F | Out-Null
    } catch {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ListenerProcessIds {
    param(
        [int]$Port
    )

    if ($Port -le 0) {
        return @()
    }

    try {
        return @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {
        return @()
    }
}

function Test-ProcessMatchesStartTime {
    param(
        [int]$ProcessId,
        [string]$ExpectedStartTime
    )

    if ($ProcessId -le 0) {
        return $false
    }

    try {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
    } catch {
        return $false
    }

    if ([string]::IsNullOrWhiteSpace($ExpectedStartTime)) {
        return $true
    }

    try {
        $expected = [datetime]::Parse($ExpectedStartTime)
    } catch {
        return $true
    }

    return $process.StartTime -eq $expected
}

function Read-ProcessIdFromFile {
    param(
        [string]$FilePath
    )

    if ([string]::IsNullOrWhiteSpace($FilePath) -or -not (Test-Path -LiteralPath $FilePath)) {
        return 0
    }

    $rawValue = (Get-Content -LiteralPath $FilePath -Raw).Trim()
    $parsedValue = 0
    if ([int]::TryParse($rawValue, [ref]$parsedValue)) {
        return $parsedValue
    }

    return 0
}

$ProjectRoot = Get-ProjectRoot
if ([string]::IsNullOrWhiteSpace($SessionFile)) {
    $SessionFile = Join-Path $ProjectRoot ".dev_session.json"
}

if (-not (Test-Path -LiteralPath $SessionFile)) {
    Write-Host "No active development session file found at $SessionFile."
    exit 0
}

$session = Get-Content -LiteralPath $SessionFile -Raw | ConvertFrom-Json
$apiPid = 0
$backendPid = 0
$desktopPid = 0
if ($session.apiPid) {
    $apiPid = [int]$session.apiPid
}
if ($session.backendPid) {
    $backendPid = [int]$session.backendPid
}
if ($session.desktopPid) {
    $desktopPid = [int]$session.desktopPid
}
$port = 0
if ($session.port) {
    $port = [int]$session.port
}
$frontendUrl = [string]$session.frontendUrl
$shutdownToken = [string]$session.shutdownToken
$electronPidFile = [string]$session.electronPidFile
$backendStartTime = [string]$session.backendStartTime
$electronPid = Read-ProcessIdFromFile -FilePath $electronPidFile

$gracefulRequested = Invoke-DevShutdownEndpoint -BaseUrl $frontendUrl -Token $shutdownToken
if ($backendPid -gt 0) {
    if ($gracefulRequested) {
        Write-Host "Requested graceful backend shutdown for PID $backendPid."
    }
    $backendExited = (Wait-ProcessExit -ProcessId $backendPid -TimeoutSeconds $TimeoutSeconds)
    $portReleased = (Wait-PortReleased -Port $port -TimeoutSeconds $TimeoutSeconds)
    if (-not $backendExited -or -not $portReleased) {
        Write-Warning "Backend listener PID $backendPid or port $port did not exit in time."
        $listenerPids = @(Get-ListenerProcessIds -Port $port)
        foreach ($listenerPid in $listenerPids) {
            if (Test-ProcessMatchesStartTime -ProcessId $listenerPid -ExpectedStartTime $backendStartTime) {
                Stop-ProcessIfRunning -ProcessId $listenerPid -Label "backend-listener"
            }
        }
        if (Test-ProcessMatchesStartTime -ProcessId $backendPid -ExpectedStartTime $backendStartTime) {
            Stop-ProcessIfRunning -ProcessId $backendPid -Label "backend"
        }
    }
}
elseif ($port -gt 0) {
    $listenerPids = @(Get-ListenerProcessIds -Port $port)
    foreach ($listenerPid in $listenerPids) {
        Stop-ProcessIfRunning -ProcessId $listenerPid -Label "backend-listener"
    }
}

if ($apiPid -gt 0) {
    Stop-ProcessIfRunning -ProcessId $apiPid -Label "api-wrapper"
}

if ($desktopPid -gt 0) {
    if (-not (Wait-ProcessExit -ProcessId $desktopPid -TimeoutSeconds 2)) {
        Stop-ProcessIfRunning -ProcessId $desktopPid -Label "desktop"
    }
}

if ($electronPid -gt 0) {
    if (-not (Wait-ProcessExit -ProcessId $electronPid -TimeoutSeconds 2)) {
        Stop-ProcessIfRunning -ProcessId $electronPid -Label "electron"
    }
}

Remove-Item -LiteralPath $SessionFile -Force -ErrorAction SilentlyContinue
if (-not [string]::IsNullOrWhiteSpace($electronPidFile)) {
    Remove-Item -LiteralPath $electronPidFile -Force -ErrorAction SilentlyContinue
}
Write-Host "Development session stopped."
