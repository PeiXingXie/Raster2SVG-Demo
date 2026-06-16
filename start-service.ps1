param(
    [string]$Python = "python",
    [string]$Host,
    [int]$Port,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

$ProjectRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$EnvFile = Join-Path $ProjectRoot ".env"

$resolvedHost = $Host
if ([string]::IsNullOrWhiteSpace($resolvedHost)) {
    $resolvedHost = Get-DotEnvValue -FilePath $EnvFile -Key "APP_HOST"
}
if ([string]::IsNullOrWhiteSpace($resolvedHost)) {
    $resolvedHost = "127.0.0.1"
}

$resolvedPort = $Port
if (-not $PSBoundParameters.ContainsKey("Port")) {
    $portFromEnv = Get-DotEnvValue -FilePath $EnvFile -Key "APP_PORT"
    if ($portFromEnv) {
        $resolvedPort = [int]$portFromEnv
    } else {
        $resolvedPort = 8120
    }
}

Push-Location $ProjectRoot
try {
    Write-Host "Project root: $ProjectRoot"

    if (-not (Test-Path -LiteralPath $EnvFile)) {
        Write-Warning ".env file not found. The service will still start, but environment-backed settings may fall back to defaults."
    }

    if (-not $SkipInstall) {
        Write-Host "Installing project in editable mode..."
        & $Python -m pip install -e .
        if ($LASTEXITCODE -ne 0) {
            throw "Editable install failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "Starting uvicorn on http://$resolvedHost`:$resolvedPort ..."
    & $Python -m uvicorn deepagents_template.api:app --host $resolvedHost --port $resolvedPort --reload
    if ($LASTEXITCODE -ne 0) {
        throw "Uvicorn exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
