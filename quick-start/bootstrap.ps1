param(
    [string]$Python = "python",
    [string]$VenvDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-ProjectRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
    return (Get-Location).Path
}

$ProjectRoot = Get-ProjectRoot
if ([string]::IsNullOrWhiteSpace($VenvDir)) {
    $VenvDir = Join-Path $ProjectRoot ".venv"
}

$EnvFile = Join-Path $ProjectRoot ".env"
$EnvExampleFile = Join-Path $ProjectRoot ".env.example"

Push-Location $ProjectRoot
try {
    Write-Host "Project root: $ProjectRoot"
    Write-Host "Using Python: $Python"
    Write-Host "Virtualenv: $VenvDir"

    & $Python --version | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Python executable '$Python' was not found or failed to run."
    }

    if (-not (Test-Path -LiteralPath $VenvDir)) {
        Write-Host "Creating virtual environment..."
        & $Python -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) {
            throw "Virtual environment creation failed with exit code $LASTEXITCODE."
        }
    }

    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Virtual environment Python not found at $VenvPython"
    }

    Write-Host "Upgrading pip..."
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed with exit code $LASTEXITCODE."
    }

    Write-Host "Installing project in editable mode..."
    & $VenvPython -m pip install -e $ProjectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Editable install failed with exit code $LASTEXITCODE."
    }

    if (-not (Test-Path -LiteralPath $EnvFile) -and (Test-Path -LiteralPath $EnvExampleFile)) {
        Copy-Item -LiteralPath $EnvExampleFile -Destination $EnvFile
        Write-Host "Created $EnvFile from .env.example"
        Write-Host "Please edit .env before starting the service."
    }

    Write-Host "Bootstrap completed."
}
finally {
    Pop-Location
}
