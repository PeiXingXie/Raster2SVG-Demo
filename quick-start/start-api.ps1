param(
    [string]$Python,
    [string]$VenvDir,
    [Alias("Host")]
    [string]$ListenHost,
    [int]$Port,
    [switch]$SkipPortResolutionPrompt,
    [switch]$ChildMode
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ProjectRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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
        if ($parts.Count -ne 2) {
            continue
        }

        if ($parts[0].Trim() -eq $Key) {
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

function Test-CondaEnvironmentActive {
    return -not [string]::IsNullOrWhiteSpace($env:CONDA_PREFIX)
}

function Test-VirtualEnvironmentActive {
    return -not [string]::IsNullOrWhiteSpace($env:VIRTUAL_ENV)
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
        [int]$RequestedPort,
        [switch]$SkipPrompt,
        [switch]$QuietAvailability
    )

    $currentPort = $RequestedPort

    while ($true) {
        $listeners = @(Get-ListeningProcessInfo -TargetPort $currentPort)
        if ($listeners.Count -eq 0) {
            if (-not $QuietAvailability) {
                Write-Host "Port check: $currentPort is available."
            }
            return $currentPort
        }

        if ($SkipPrompt) {
            throw "Port check failed: port $currentPort is already in use and interactive resolution is disabled for this startup path."
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
        "# Generated by quick-start/start-api.ps1"
        "APP_HOST=$AppHost"
        "APP_PORT=$Port"
        "PORT_PROMPT_TIMEOUT_SECONDS=$TimeoutSeconds"
    )

    Set-Content -LiteralPath $FilePath -Value $content -Encoding ASCII
}

function Get-EnvironmentSummary {
    param(
        [string]$PythonPath,
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
    if ($PythonPath -eq "python") {
        return "Active Python on PATH"
    }
    if ($PythonPath -like "$VenvPath*") {
        return ".venv fallback ($PythonPath)"
    }
    return "Custom Python ($PythonPath)"
}

function Show-StartupSummary {
    param(
        [string]$BackendUrl,
        [string]$EnvironmentSummary,
        [string]$RuntimeConfigPath,
        [string]$PythonExecutable,
        [int]$TimeoutSeconds,
        [bool]$ApiConfigReady
    )

    Write-Host ""
    Write-Host "Startup summary"
    Write-Host "  Mode: backend"
    Write-Host "  Environment: $EnvironmentSummary"
    Write-Host "  Python executable: $PythonExecutable"
    Write-Host "  Backend URL: $BackendUrl"
    Write-Host "  Runtime config: $RuntimeConfigPath"
    Write-Host "  Port prompt timeout: ${TimeoutSeconds}s"
    Write-Host "  API config ready: $(if ($ApiConfigReady) { 'yes' } else { 'no' })"
    Write-Host ""
}

$ProjectRoot = Get-ProjectRoot
if ([string]::IsNullOrWhiteSpace($VenvDir)) {
    $VenvDir = Join-Path $ProjectRoot ".venv"
}

if ([string]::IsNullOrWhiteSpace($Python)) {
    if (Test-VirtualEnvironmentActive -or Test-CondaEnvironmentActive) {
        $Python = "python"
    } else {
        $Python = Join-Path $VenvDir "Scripts\python.exe"
    }
}

$ResolvedPython = $Python
if ($Python -eq "python" -or -not (Test-Path -LiteralPath $Python)) {
    try {
        $ResolvedPython = Get-PythonExecutablePath -PythonExe $Python
    } catch {
        if (-not (Test-Path -LiteralPath $Python)) {
            throw "Python executable not found at $Python. Run .\bootstrap.ps1 first, activate your environment, or pass -Python explicitly."
        }
    }
}

$EnvFile = Join-Path $ProjectRoot ".env"
$RuntimeEnvFile = Join-Path $ProjectRoot ".runtime_startup.env"

if (-not (Test-Path -LiteralPath $ResolvedPython)) {
    throw "Python executable not found at $ResolvedPython. Run .\bootstrap.ps1 first, activate your environment, or pass -Python explicitly."
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

$ForwardedArgs = @()
if ($args.Count -gt 0) {
    $ForwardedArgs = $args
}

Push-Location $ProjectRoot
try {
    $apiConfigReady = $false
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        Write-Warning ".env file not found. Bootstrap can create one from .env.example."
    } else {
        $apiKey = Get-DotEnvValue -FilePath $EnvFile -Key "API_KEY"
        $baseUrl = Get-DotEnvValue -FilePath $EnvFile -Key "BASE_URL"
        if ([string]::IsNullOrWhiteSpace($apiKey)) {
            Write-Warning "API_KEY is empty in .env . The frontend can open, but real model-backed conversions will fail until you fill it."
        }
        if ([string]::IsNullOrWhiteSpace($baseUrl)) {
            Write-Warning "BASE_URL is empty in .env . Fill it before the first real model-backed conversion."
        }
        $apiConfigReady = (-not [string]::IsNullOrWhiteSpace($apiKey)) -and (-not [string]::IsNullOrWhiteSpace($baseUrl))
    }

    $Port = Resolve-ListenPortInteractive -RequestedPort $Port -SkipPrompt:$SkipPortResolutionPrompt -QuietAvailability:$ChildMode
    Write-RuntimeStartupConfig -FilePath $RuntimeEnvFile -AppHost $ListenHost -Port $Port -TimeoutSeconds $PortPromptTimeoutSeconds
    $backendUrl = "http://$ListenHost`:$Port"

    if (-not $ChildMode) {
        Write-Host "Project root: $ProjectRoot"
        Show-StartupSummary -BackendUrl $backendUrl -EnvironmentSummary (Get-EnvironmentSummary -PythonPath $ResolvedPython -VenvPath $VenvDir) -RuntimeConfigPath $RuntimeEnvFile -PythonExecutable $ResolvedPython -TimeoutSeconds $PortPromptTimeoutSeconds -ApiConfigReady $apiConfigReady
        Write-Host "Starting uvicorn on $backendUrl"
    }

    & $ResolvedPython -m uvicorn deepagents_template.api:app --host $ListenHost --port $Port @ForwardedArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Uvicorn exited with code $LASTEXITCODE. Check whether the port is already in use and whether your environment is installed correctly."
    }
}
finally {
    Pop-Location
}
