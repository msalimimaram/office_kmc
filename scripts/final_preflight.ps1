[CmdletBinding()]
param(
    [switch]$Production
)

$ErrorActionPreference = "Stop"

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "FAILED: $Name (exit code $LASTEXITCODE)"
    }

    Write-Host "PASS: $Name" -ForegroundColor Green
}

$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

if (-not (Test-Path "manage.py")) {
    throw "Run this script from the office_kmc repository root (manage.py was not found)."
}

Write-Host "Python executable: $python"
& $python --version
if ($LASTEXITCODE -ne 0) {
    throw "Python could not be started."
}

Invoke-Check -Name "Dependency consistency" -Command $python -Arguments @("-m", "pip", "check")
Invoke-Check -Name "Django system checks" -Command $python -Arguments @("manage.py", "check")
Invoke-Check -Name "Migration drift check" -Command $python -Arguments @("manage.py", "makemigrations", "--check", "--dry-run")
Invoke-Check -Name "Complete Django test suite" -Command $python -Arguments @("manage.py", "test", "--verbosity", "2")
Invoke-Check -Name "Workflow publication gate" -Command $python -Arguments @("manage.py", "audit_workflows")

if ($Production) {
    if (-not $env:DJANGO_DEBUG -or $env:DJANGO_DEBUG.ToLowerInvariant() -ne "false") {
        throw "Production preflight requires DJANGO_DEBUG=False."
    }
    if (-not $env:DATABASE_URL -or $env:DATABASE_URL -notmatch "^postgres(ql)?://") {
        throw "Production preflight requires a PostgreSQL DATABASE_URL."
    }
    if (-not $env:REDIS_URL) {
        throw "Production preflight requires REDIS_URL for shared throttling."
    }
    if (-not $env:DJANGO_ALLOWED_HOSTS) {
        throw "Production preflight requires explicit DJANGO_ALLOWED_HOSTS."
    }
    if (-not $env:CLAMD_HOST) {
        throw "Production preflight requires CLAMD_HOST for malware scanning."
    }
    if (-not $env:DJANGO_SECRET_KEY -or $env:DJANGO_SECRET_KEY.Length -lt 50) {
        throw "Production preflight requires a strong DJANGO_SECRET_KEY (at least 50 characters)."
    }

    Invoke-Check -Name "Production security checks" -Command $python -Arguments @("manage.py", "check", "--deploy")
    Invoke-Check -Name "Database migration state (read-only)" -Command $python -Arguments @("manage.py", "migrate", "--check")
    Invoke-Check -Name "Static asset collection" -Command $python -Arguments @("manage.py", "collectstatic", "--noinput")
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "ALL REQUESTED PREFLIGHT CHECKS PASSED" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
if (-not $Production) {
    Write-Host "This was the local preflight. Run with -Production only against a staging clone of production; never point the Django test runner at the live production database."
}
