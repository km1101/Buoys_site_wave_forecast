# Run the wave forecast dashboard locally.

$ErrorActionPreference = "Stop"
$DashboardRoot = $PSScriptRoot
$ProjectRoot = Split-Path $DashboardRoot -Parent
$EnvFile = Join-Path $DashboardRoot ".env"
$EnvExample = Join-Path $DashboardRoot ".env.example"

function Set-DatabaseUrlFromFile($Path) {
    if (-not (Test-Path $Path)) { return $false }
    Get-Content $Path | ForEach-Object {
        if ($_ -match '^\s*DATABASE_URL=(.+)$') {
            $env:DATABASE_URL = $matches[1].Trim().Trim('"').Trim("'")
            return $true
        }
    }
    return $false
}

if (-not $env:DATABASE_URL) {
    Set-DatabaseUrlFromFile $EnvFile | Out-Null
}

if (-not $env:DATABASE_URL) {
    $LocalSettings = Join-Path $ProjectRoot "local.settings.json"
    if (Test-Path $LocalSettings) {
        $settings = Get-Content $LocalSettings -Raw | ConvertFrom-Json
        if ($settings.Values.DATABASE_URL) {
            $env:DATABASE_URL = $settings.Values.DATABASE_URL
        }
    }
}

$isPlaceholder = $false
if ($env:DATABASE_URL) {
    $isPlaceholder = $env:DATABASE_URL -match '@host[:/]' `
        -or $env:DATABASE_URL -match 'user:pass@' `
        -or $env:DATABASE_URL -match 'USER:PASSWORD@' `
        -or $env:DATABASE_URL -match 'YOUR-CLUSTER'
}

if (-not $env:DATABASE_URL -or $isPlaceholder) {
    Write-Host "DATABASE_URL is missing or still a placeholder." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. Copy the example file:"
    Write-Host "   Copy-Item `"$EnvExample`" `"$EnvFile`""
    Write-Host ""
    Write-Host "2. Edit dashboard\.env and set your real CockroachDB URL"
    Write-Host "   (same value as on the waveforecast Azure Function app)."
    Write-Host ""
    Write-Host "3. Run .\run.ps1 again"
    exit 1
}

Write-Host "Using DATABASE_URL from environment / .env"
Set-Location $DashboardRoot
py -m pip install -r requirements.txt -q
Write-Host ""
Write-Host "Dashboard: http://127.0.0.1:8080" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""
py -m uvicorn api.main:app --app-dir $DashboardRoot --host 127.0.0.1 --port 8080 --reload --reload-dir api --reload-dir static --reload-exclude ".venv"
