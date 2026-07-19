param(
    [string]$Python = "python",
    [string]$VenvDir,
    [Alias("Host")]
    [string]$ListenHost,
    [int]$Port,
    [switch]$Desktop,
    [switch]$SkipBootstrap,
    [switch]$SkipDesktopBootstrap,
    [switch]$UseActivePython,
    [switch]$ForceBootstrap
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:DevSessionStopped = $false

function Get-ProjectRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path $PSScriptRoot).Path
    }
    return (Get-Location).Path
}

function New-DevShutdownToken {
    return [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
}

function New-DevSessionId {
    return [guid]::NewGuid().ToString("N")
}

function Convert-ToSingleQuotedPowerShellLiteral {
    param(
        [string]$Value
    )

    if ($null -eq $Value) {
        return "''"
    }

    return "'" + $Value.Replace("'", "''") + "'"
}

function Write-DevSessionFile {
    param(
        [string]$FilePath,
        [string]$SessionId,
        [string]$ProjectRoot,
        [string]$FrontendUrl,
        [int]$Port,
        [int]$ApiPid,
        [int]$BackendPid,
        [int]$DesktopPid,
        [string]$ShutdownToken,
        [string]$Mode,
        [string]$ElectronPidFile,
        [string]$BackendStartTime
    )

    $payload = [ordered]@{
        sessionId = $SessionId
        mode = $Mode
        projectRoot = $ProjectRoot
        frontendUrl = $FrontendUrl
        port = $Port
        apiPid = $ApiPid
        backendPid = $BackendPid
        backendStartTime = $BackendStartTime
        desktopPid = $DesktopPid
        electronPidFile = $ElectronPidFile
        shutdownToken = $ShutdownToken
        createdAt = (Get-Date).ToString("o")
        updatedAt = (Get-Date).ToString("o")
    }

    $payload | ConvertTo-Json | Set-Content -LiteralPath $FilePath -Encoding ASCII
}

function Stop-DevSession {
    param(
        [string]$ProjectRoot,
        [string]$SessionFile
    )

    if ($script:DevSessionStopped) {
        return
    }

    $script:DevSessionStopped = $true
    $stopScript = Join-Path $ProjectRoot "stop-dev.ps1"
    if (-not (Test-Path -LiteralPath $stopScript)) {
        return
    }

    & $stopScript -SessionFile $SessionFile
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

function Wait-DesktopElectronProcess {
    param(
        [string]$PidFilePath,
        [int]$TimeoutSeconds = 20,
        [int]$PollIntervalMilliseconds = 250
    )

    if ([string]::IsNullOrWhiteSpace($PidFilePath)) {
        return 0
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $electronPid = Read-ProcessIdFromFile -FilePath $PidFilePath
        if ($electronPid -gt 0) {
            try {
                $null = Get-Process -Id $electronPid -ErrorAction Stop
                return $electronPid
            } catch {
            }
        }
        Start-Sleep -Milliseconds $PollIntervalMilliseconds
    }

    return 0
}

function Test-CondaEnvironmentActive {
    return -not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)
}

function Test-VirtualEnvironmentActive {
    return -not [string]::IsNullOrWhiteSpace($env:VIRTUAL_ENV)
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

function Convert-ToPositiveIntOrNull {
    param(
        [string]$RawValue,
        [string]$SettingName,
        [string]$SourceLabel
    )

    if ([string]::IsNullOrWhiteSpace($RawValue)) {
        return $null
    }

    $parsedValue = 0
    if ([int]::TryParse($RawValue, [ref]$parsedValue) -and $parsedValue -gt 0) {
        return $parsedValue
    }

    Write-Warning "$SettingName value '$RawValue' from $SourceLabel is invalid. Falling back to the default value."
    return $null
}

function Convert-ToPortOrNull {
    param(
        [string]$RawValue,
        [string]$SettingName,
        [string]$SourceLabel
    )

    if ([string]::IsNullOrWhiteSpace($RawValue)) {
        return $null
    }

    $parsedValue = 0
    if ([int]::TryParse($RawValue, [ref]$parsedValue) -and $parsedValue -ge 1 -and $parsedValue -le 65535) {
        return $parsedValue
    }

    Write-Warning "$SettingName value '$RawValue' from $SourceLabel is invalid. Expected a port between 1 and 65535. Falling back to the default value."
    return $null
}

function Get-IntSettingValue {
    param(
        [string]$FilePath,
        [string]$Key,
        [int]$DefaultValue
    )

    $environmentValue = [Environment]::GetEnvironmentVariable($Key)
    $parsedEnvironmentValue = Convert-ToPositiveIntOrNull -RawValue $environmentValue -SettingName $Key -SourceLabel "the current shell environment"
    if ($null -ne $parsedEnvironmentValue) {
        return $parsedEnvironmentValue
    }

    $dotEnvValue = Get-DotEnvValue -FilePath $FilePath -Key $Key
    $parsedDotEnvValue = Convert-ToPositiveIntOrNull -RawValue $dotEnvValue -SettingName $Key -SourceLabel $FilePath
    if ($null -ne $parsedDotEnvValue) {
        return $parsedDotEnvValue
    }

    return $DefaultValue
}

function Get-PortSettingValue {
    param(
        [string]$FilePath,
        [string]$Key,
        [int]$DefaultValue
    )

    $environmentValue = [Environment]::GetEnvironmentVariable($Key)
    $parsedEnvironmentValue = Convert-ToPortOrNull -RawValue $environmentValue -SettingName $Key -SourceLabel "the current shell environment"
    if ($null -ne $parsedEnvironmentValue) {
        return $parsedEnvironmentValue
    }

    $dotEnvValue = Get-DotEnvValue -FilePath $FilePath -Key $Key
    $parsedDotEnvValue = Convert-ToPortOrNull -RawValue $dotEnvValue -SettingName $Key -SourceLabel $FilePath
    if ($null -ne $parsedDotEnvValue) {
        return $parsedDotEnvValue
    }

    return $DefaultValue
}

function Get-PythonExecutablePath {
    param(
        [string]$PythonExe
    )

    $resolvedPath = & $PythonExe -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python executable '$PythonExe' was not found or failed to run."
    }
    return ($resolvedPath | Select-Object -First 1).Trim()
}

function Get-ListeningProcessInfo {
    param(
        [int]$TargetPort
    )

    try {
        $connections = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction Stop
    } catch {
        return @()
    }

    $results = @()
    foreach ($connection in $connections) {
        $processName = $null
        try {
            $processName = (Get-Process -Id $connection.OwningProcess -ErrorAction Stop).ProcessName
        } catch {
            $processName = "<unknown>"
        }

        $results += [PSCustomObject]@{
            ProcessId    = $connection.OwningProcess
            ProcessName  = $processName
            LocalAddress = $connection.LocalAddress
            LocalPort    = $connection.LocalPort
        }
    }

    return $results
}

function Read-LineWithTimeout {
    param(
        [string]$Prompt,
        [int]$TimeoutSeconds
    )

    Write-Host -NoNewline $Prompt

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $buffer = New-Object System.Text.StringBuilder

    while ((Get-Date) -lt $deadline) {
        $keyAvailable = $false
        try {
            $keyAvailable = [Console]::KeyAvailable
        } catch {
            Write-Host
            return $null
        }

        if (-not $keyAvailable) {
            Start-Sleep -Milliseconds 200
            continue
        }

        $key = [Console]::ReadKey($true)
        if ($key.Key -eq [ConsoleKey]::Enter) {
            Write-Host
            return $buffer.ToString()
        }

        if ($key.Key -eq [ConsoleKey]::Backspace) {
            if ($buffer.Length -gt 0) {
                $buffer.Length = $buffer.Length - 1
                Write-Host -NoNewline "`b `b"
            }
            continue
        }

        if (-not [char]::IsControl($key.KeyChar)) {
            [void]$buffer.Append($key.KeyChar)
            Write-Host -NoNewline $key.KeyChar
        }
    }

    Write-Host
    return $null
}

function Wait-BackendHealth {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSeconds = 20,
        [int]$PollIntervalMilliseconds = 500
    )

    $healthUrl = $BaseUrl.TrimEnd("/") + "/health"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds $PollIntervalMilliseconds
        }
    }

    return $false
}

function Get-ListenerProcessIds {
    param(
        [int]$TargetPort
    )

    try {
        return @(
            Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
    } catch {
        return @()
    }
}

function Wait-BackendListenerProcess {
    param(
        [int]$TargetPort,
        [int]$WrapperPid,
        [int]$TimeoutSeconds = 15
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $listenerPids = @(Get-ListenerProcessIds -TargetPort $TargetPort)
        foreach ($listenerPid in $listenerPids) {
            if ($listenerPid -ne $WrapperPid) {
                return $listenerPid
            }
        }
        Start-Sleep -Milliseconds 500
    }

    return 0
}

function Test-PortAvailable {
    param(
        [int]$TargetPort
    )

    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $TargetPort)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            try {
                $listener.Stop()
            } catch {
            }
        }
    }
}

function Find-FreePort {
    param(
        [int]$PreferredPort
    )

    $startPort = [Math]::Max($PreferredPort + 1, 1024)
    for ($candidate = $startPort; $candidate -le 65535; $candidate++) {
        if (Test-PortAvailable -TargetPort $candidate) {
            return $candidate
        }
    }

    for ($candidate = 1024; $candidate -lt $startPort; $candidate++) {
        if (Test-PortAvailable -TargetPort $candidate) {
            return $candidate
        }
    }

    throw "Unable to find a free TCP port automatically."
}

function Resolve-ListenPortInteractive {
    param(
        [int]$RequestedPort
    )

    $currentPort = $RequestedPort

    while ($true) {
        $listeners = @(Get-ListeningProcessInfo -TargetPort $currentPort)
        if ($listeners.Count -eq 0) {
            Write-Host "Port check: $currentPort is available."
            return $currentPort
        }

        Write-Warning "Port check: $currentPort is already in use."
        Write-Host "Current listeners on port ${currentPort}:"
        foreach ($listener in $listeners) {
            Write-Host "  PID=$($listener.ProcessId) Name=$($listener.ProcessName) Address=$($listener.LocalAddress):$($listener.LocalPort)"
        }
        Write-Host "Input guide:"
        Write-Host "  yes / Yes / Y : stop the listed process(es) and keep using port $currentPort"
        Write-Host "  no / NO / N   : choose another port or exit"
        Write-Host "  no input for $PortPromptTimeoutSeconds seconds : automatically switch to a free port"

        $releaseAnswer = Read-LineWithTimeout -Prompt "Do you want to release port $currentPort and keep using it? (yes/Yes/Y/no/NO/N) " -TimeoutSeconds $PortPromptTimeoutSeconds
        if ($null -eq $releaseAnswer) {
            Write-Warning "No input received within $PortPromptTimeoutSeconds seconds."
            $autoPort = Find-FreePort -PreferredPort $currentPort
            Write-Host "Port selection: automatically switching to free port $autoPort."
            return $autoPort
        }

        if ($releaseAnswer -match '^(?i:y(?:es)?)$') {
            Write-Host "Attempting to release port $currentPort..."
            foreach ($listener in $listeners) {
                try {
                    Stop-Process -Id $listener.ProcessId -Force -ErrorAction Stop
                    Write-Host "Stopped PID $($listener.ProcessId) ($($listener.ProcessName))."
                } catch {
                    throw "Failed to stop PID $($listener.ProcessId) on port $currentPort. Try rerunning with permission to stop that process, or choose another port."
                }
            }

            Start-Sleep -Milliseconds 500
            $remaining = @(Get-ListeningProcessInfo -TargetPort $currentPort)
            if ($remaining.Count -eq 0) {
                Write-Host "Port check: $currentPort is now free and will be used."
                return $currentPort
            }

            Write-Warning "Port $currentPort is still in use after attempting to stop the listener."
        } elseif ($releaseAnswer -match '^(?i:n(?:o)?)$') {
            Write-Host "Input guide:"
            Write-Host "  <port number> : try another port"
            Write-Host "  no / NO / N   : cancel startup"
            Write-Host "  no input for $PortPromptTimeoutSeconds seconds : automatically switch to a free port"
            $nextAnswer = Read-LineWithTimeout -Prompt "Enter another port number to use, or no/NO/N to exit " -TimeoutSeconds $PortPromptTimeoutSeconds
            if ($null -eq $nextAnswer) {
                Write-Warning "No input received within $PortPromptTimeoutSeconds seconds."
                $autoPort = Find-FreePort -PreferredPort $currentPort
                Write-Host "Port selection: automatically switching to free port $autoPort."
                return $autoPort
            }
            if ($nextAnswer -match '^(?i:n(?:o)?)$') {
                throw "Startup cancelled because port $currentPort is occupied."
            }

            $parsedPort = 0
            if (-not [int]::TryParse($nextAnswer, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
                Write-Warning "Invalid port value '$nextAnswer'. Enter a number between 1 and 65535, or no to exit."
                continue
            }

            Write-Host "Port selection: will retry with port $parsedPort."
            $currentPort = $parsedPort
        } else {
            Write-Warning "Unrecognized input '$releaseAnswer'. Please answer yes/Yes/Y or no/NO/N."
        }
    }
}

function Write-RuntimeStartupConfig {
    param(
        [string]$FilePath,
        [string]$AppHost,
        [int]$Port,
        [int]$TimeoutSeconds
    )

    $content = @(
        "# Generated by start-dev.ps1"
        "APP_HOST=$AppHost"
        "APP_PORT=$Port"
        "PORT_PROMPT_TIMEOUT_SECONDS=$TimeoutSeconds"
    )

    Set-Content -LiteralPath $FilePath -Value $content -Encoding ASCII
}

function Get-EnvironmentSummary {
    param(
        [bool]$UseActivatedPythonMode,
        [string]$ResolvedPythonPath,
        [string]$VenvPath
    )

    $virtualEnv = $env:VIRTUAL_ENV
    $condaEnv = $env:CONDA_PREFIX

    if (-not [string]::IsNullOrWhiteSpace($virtualEnv) -and -not [string]::IsNullOrWhiteSpace($condaEnv)) {
        return "Virtualenv ($virtualEnv) on top of Conda ($condaEnv)"
    }
    if (-not [string]::IsNullOrWhiteSpace($virtualEnv)) {
        return "Virtualenv ($virtualEnv)"
    }
    if (-not [string]::IsNullOrWhiteSpace($condaEnv)) {
        return "Conda ($condaEnv)"
    }
    if ($UseActivatedPythonMode) {
        return "Active Python ($ResolvedPythonPath)"
    }
    return ".venv fallback ($VenvPath)"
}

function Show-StartupSummary {
    param(
        [string]$Mode,
        [string]$BackendUrl,
        [string]$EnvironmentSummary,
        [string]$RuntimeConfigPath,
        [string]$PythonExecutable,
        [string]$BootstrapMode,
        [int]$TimeoutSeconds
    )

    Write-Host ""
    Write-Host "Startup summary"
    Write-Host "  Mode: $Mode"
    Write-Host "  Environment: $EnvironmentSummary"
    Write-Host "  Python executable: $PythonExecutable"
    Write-Host "  Backend URL: $BackendUrl"
    Write-Host "  Runtime config: $RuntimeConfigPath"
    Write-Host "  Bootstrap mode: $BootstrapMode"
    Write-Host "  Port prompt timeout: ${TimeoutSeconds}s"
    Write-Host "  Desktop enabled: $(if ($Desktop) { 'yes' } else { 'no' })"
    Write-Host ""
}

$ProjectRoot = Get-ProjectRoot
$QuickStartDir = Join-Path $ProjectRoot "quick-start"
$DesktopDir = Join-Path $ProjectRoot "desktop"
$EnvFile = Join-Path $ProjectRoot ".env"
$RuntimeEnvFile = Join-Path $ProjectRoot ".runtime_startup.env"
$DevSessionFile = Join-Path $ProjectRoot ".dev_session.json"
$DesktopPidFile = Join-Path $ProjectRoot ".dev_desktop.pid"

if ([string]::IsNullOrWhiteSpace($VenvDir)) {
    $VenvDir = Join-Path $ProjectRoot ".venv"
}
if ([string]::IsNullOrWhiteSpace($ListenHost)) {
    $ListenHost = $env:APP_HOST
}
if ([string]::IsNullOrWhiteSpace($ListenHost)) {
    $ListenHost = Get-DotEnvValue -FilePath $EnvFile -Key "APP_HOST"
}
if ([string]::IsNullOrWhiteSpace($ListenHost)) {
    $ListenHost = "127.0.0.1"
}
$NormalizedListenHost = $ListenHost.Trim().ToLowerInvariant()
if ($NormalizedListenHost -notin @("127.0.0.1", "localhost", "::1")) {
    throw "Shape Studio is local-only. APP_HOST/ListenHost must be 127.0.0.1, localhost, or ::1."
}
$ListenHost = "127.0.0.1"
if (-not $PSBoundParameters.ContainsKey("Port")) {
    $Port = Get-PortSettingValue -FilePath $EnvFile -Key "APP_PORT" -DefaultValue 8120
}
$PortPromptTimeoutSeconds = Get-IntSettingValue -FilePath $EnvFile -Key "PORT_PROMPT_TIMEOUT_SECONDS" -DefaultValue 15

$UseActivatedPython = $UseActivePython.IsPresent -or (Test-VirtualEnvironmentActive) -or (Test-CondaEnvironmentActive)
$BootstrapPython = $Python
if ($UseActivatedPython) {
    $BootstrapPython = Get-PythonExecutablePath -PythonExe $Python
    $ResolvedPython = $BootstrapPython
} else {
    $ResolvedPython = Join-Path $VenvDir "Scripts\python.exe"
}

$BootstrapMode = if ($SkipBootstrap) {
    "skipped"
} elseif ($ForceBootstrap) {
    "always"
} else {
    "if-needed"
}

Push-Location $ProjectRoot
try {
    $Port = Resolve-ListenPortInteractive -RequestedPort $Port
    $frontendUrl = "http://$ListenHost`:$Port/"
    $StartupMode = if ($Desktop) { "web + desktop" } else { "web only" }
    $PythonExecutable = $ResolvedPython
    $EnvironmentSummary = Get-EnvironmentSummary -UseActivatedPythonMode $UseActivatedPython -ResolvedPythonPath $ResolvedPython -VenvPath $VenvDir
    Write-Host "Project root: $ProjectRoot"
    Write-Host "Development URL: $frontendUrl"
    Show-StartupSummary -Mode $StartupMode -BackendUrl $frontendUrl.TrimEnd("/") -EnvironmentSummary $EnvironmentSummary -RuntimeConfigPath $RuntimeEnvFile -PythonExecutable $PythonExecutable -BootstrapMode $BootstrapMode -TimeoutSeconds $PortPromptTimeoutSeconds

    if (-not $SkipBootstrap) {
        $BootstrapParams = @{
            Python = $BootstrapPython
            VenvDir = $VenvDir
            InstallDevDependencies = $true
        }
        if ($UseActivatedPython) {
            $BootstrapParams.UseActivePython = $true
        }
        if (-not $ForceBootstrap) {
            $BootstrapParams.IfNeeded = $true
        }

        Write-Host "Running backend bootstrap..."
        & (Join-Path $QuickStartDir "bootstrap.ps1") @BootstrapParams
        if ($LASTEXITCODE -ne 0) {
            throw "Backend bootstrap failed. Review the bootstrap output above for Python, pip, or dependency-install issues."
        }
    }

    if (-not $UseActivatedPython) {
        if (-not (Test-Path -LiteralPath $ResolvedPython)) {
            throw "Virtualenv Python not found at $ResolvedPython . Run bootstrap first, or activate an environment and rerun with -UseActivePython."
        }
        $ResolvedPython = Get-PythonExecutablePath -PythonExe $ResolvedPython
    }

    Write-RuntimeStartupConfig -FilePath $RuntimeEnvFile -AppHost $ListenHost -Port $Port -TimeoutSeconds $PortPromptTimeoutSeconds

    if ($Desktop) {
        $sessionId = New-DevSessionId
        $shutdownToken = New-DevShutdownToken
        Remove-Item -LiteralPath $DesktopPidFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $DevSessionFile -Force -ErrorAction SilentlyContinue
        if (-not $SkipDesktopBootstrap) {
            Write-Host "Running desktop bootstrap..."
            & (Join-Path $DesktopDir "bootstrap.ps1")
            if ($LASTEXITCODE -ne 0) {
                throw "Desktop bootstrap failed. Check Node.js 20+, npm availability, or packaged desktop dependencies."
            }
        }

        Write-Host "Starting API in a background PowerShell process..."
        $apiStartupScript = @(
            '$env:RASTER_SVG_DEV_SHUTDOWN_TOKEN = ' + (Convert-ToSingleQuotedPowerShellLiteral -Value $shutdownToken)
            '& powershell.exe -NoProfile -ExecutionPolicy Bypass -File ' + (Convert-ToSingleQuotedPowerShellLiteral -Value (Join-Path $QuickStartDir "start-api.ps1")) + `
                ' -Python ' + (Convert-ToSingleQuotedPowerShellLiteral -Value $ResolvedPython) + `
                ' -ListenHost ' + (Convert-ToSingleQuotedPowerShellLiteral -Value $ListenHost) + `
                " -Port $Port -SkipPortResolutionPrompt -ChildMode"
        ) -join "; "
        $apiCommand = @("-NoProfile", "-Command", $apiStartupScript)

        $apiProcess = Start-Process -FilePath "powershell.exe" -ArgumentList $apiCommand -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
        Write-Host "API process started with PID $($apiProcess.Id)."
        if (-not (Wait-BackendHealth -BaseUrl $frontendUrl)) {
            throw "Backend health check failed after startup. Aborting desktop launch."
        }
        $backendPid = Wait-BackendListenerProcess -TargetPort $Port -WrapperPid $apiProcess.Id
        if ($backendPid -le 0) {
            throw "Unable to resolve the backend listener PID after health succeeded."
        }
        $backendProcess = Get-Process -Id $backendPid -ErrorAction Stop
        $backendStartTime = $backendProcess.StartTime.ToString("o")
        Write-Host "Backend listener is PID $backendPid."

        Write-Host "Launching desktop shell against $frontendUrl"
        $desktopCommand = @(
            "-NoProfile"
            "-ExecutionPolicy"
            "Bypass"
            "-File"
            ('"{0}"' -f (Join-Path $DesktopDir "start-desktop.ps1"))
            "-FrontendUrl"
            ('"{0}"' -f $frontendUrl)
            "-SkipBootstrap"
        ) -join " "

        $env:RASTER_SVG_DESKTOP_PID_FILE = $DesktopPidFile
        $desktopProcess = Start-Process -FilePath "powershell.exe" -ArgumentList $desktopCommand -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
        Remove-Item Env:\RASTER_SVG_DESKTOP_PID_FILE -ErrorAction SilentlyContinue
        Write-Host "Desktop process started with PID $($desktopProcess.Id)."
        Write-DevSessionFile -FilePath $DevSessionFile -SessionId $sessionId -ProjectRoot $ProjectRoot -FrontendUrl $frontendUrl -Port $Port -ApiPid $apiProcess.Id -BackendPid $backendPid -DesktopPid $desktopProcess.Id -ShutdownToken $shutdownToken -Mode "desktop" -ElectronPidFile $DesktopPidFile -BackendStartTime $backendStartTime
        try {
            $electronPid = Wait-DesktopElectronProcess -PidFilePath $DesktopPidFile
            if ($electronPid -gt 0) {
                Write-Host "Electron process is PID $electronPid."
                Wait-Process -Id $electronPid
            } else {
                Wait-Process -Id $desktopProcess.Id
            }
        }
        finally {
            Stop-DevSession -ProjectRoot $ProjectRoot -SessionFile $DevSessionFile
        }
    } else {
        Write-Host "Starting API in the current terminal..."
        & (Join-Path $QuickStartDir "start-api.ps1") -Python $ResolvedPython -ListenHost $ListenHost -Port $Port -SkipPortResolutionPrompt -ChildMode --reload
        if ($LASTEXITCODE -ne 0) {
            throw "API startup failed. Check port usage, Python environment availability, and .env configuration."
        }
    }
}
finally {
    if ($Desktop) {
        Stop-DevSession -ProjectRoot $ProjectRoot -SessionFile $DevSessionFile
    }
    Pop-Location
}
