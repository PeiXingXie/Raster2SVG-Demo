param(
    [string]$Python,
    [string]$VenvDir,
    [Alias("Host")]
    [string]$ListenHost,
    [int]$Port
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

$ProjectRoot = Get-ProjectRoot
if ([string]::IsNullOrWhiteSpace($VenvDir)) {
    $VenvDir = Join-Path $ProjectRoot ".venv"
}

if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $VenvDir "Scripts\python.exe"
}

$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found at $Python. Run .\bootstrap.ps1 first or pass -Python."
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

if (-not $PSBoundParameters.ContainsKey("Port")) {
    if ($env:APP_PORT) {
        $Port = [int]$env:APP_PORT
    } else {
        $portFromEnv = Get-DotEnvValue -FilePath $EnvFile -Key "APP_PORT"
        if ($portFromEnv) {
            $Port = [int]$portFromEnv
        } else {
            $Port = 8120
        }
    }
}

$ForwardedArgs = @()
if ($args.Count -gt 0) {
    $ForwardedArgs = $args
}

Push-Location $ProjectRoot
try {
    Write-Host "Project root: $ProjectRoot"
    Write-Host "Starting uvicorn on http://$ListenHost`:$Port"
    & $Python -m uvicorn deepagents_template.api:app --host $ListenHost --port $Port @ForwardedArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Uvicorn exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
