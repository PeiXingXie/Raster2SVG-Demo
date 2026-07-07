param(
    [string]$VenvPath,
    [string]$ProjectRoot,
    [int]$Top = 40
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
if ([string]::IsNullOrWhiteSpace($VenvPath)) {
    $VenvPath = Join-Path $Root ".venv_package"
}

$SitePackages = Join-Path $VenvPath "Lib\site-packages"
if (-not (Test-Path -LiteralPath $SitePackages)) {
    throw "site-packages not found: $SitePackages"
}

$Rows = @()
foreach ($item in Get-ChildItem -LiteralPath $SitePackages -Force) {
    if ($item.Name -like "*.dist-info" -or $item.Name -like "*.egg-info" -or $item.Name -eq "__pycache__") {
        continue
    }
    $sum = 0
    if ($item.PSIsContainer) {
        $measure = Get-ChildItem -LiteralPath $item.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum
        $sum = [int64]($measure.Sum)
    } else {
        $sum = [int64]$item.Length
    }
    if ($sum -gt 0) {
        $Rows += [pscustomobject]@{
            Name = $item.Name
            SizeMB = [math]::Round($sum / 1MB, 2)
            Bytes = $sum
        }
    }
}

$Rows = $Rows | Sort-Object Bytes -Descending
$ReportPath = Join-Path $Root "dist\dependency-size-report.md"
New-Item -ItemType Directory -Path (Split-Path -Parent $ReportPath) -Force | Out-Null

$total = [math]::Round((($Rows | Measure-Object Bytes -Sum).Sum) / 1MB, 2)
$lines = @()
$lines += "# Package Dependency Size Report"
$lines += ""
$lines += "- Venv: $VenvPath"
$lines += "- Site-packages total scanned size: ${total} MB"
$lines += "- Generated at: $((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"))"
$lines += ""
$lines += "| Rank | Package/Module | Size MB |"
$lines += "| ---: | --- | ---: |"
$rank = 1
foreach ($row in ($Rows | Select-Object -First $Top)) {
    $lines += "| $rank | $($row.Name) | $($row.SizeMB) |"
    $rank += 1
}

$lines | Set-Content -LiteralPath $ReportPath -Encoding UTF8
$Rows | Select-Object -First $Top | Format-Table Name, SizeMB -AutoSize
Write-Host "Report written: $ReportPath"
