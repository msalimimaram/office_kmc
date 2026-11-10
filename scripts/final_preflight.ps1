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

# A fresh local clone has unapplied migrations by definition. Apply them to the
# local development database before checking migration state. Production mode
# must remain read-only and therefore never runs migrate.
if (-not $Production) {
    Invoke-Check -Name "Apply local database migrations" -Command $python -Arguments @("manage.py", "migrate", "--noinput")
}

Invoke-Check -Name "Database migration state" -Command $python -Arguments @("manage.py", "migrate", "--check")
Invoke-Check -Name "Verify operational database tables" -Command $python -Arguments @("manage.py", "verify_database_schema")
Invoke-Check -Name "Complete Django test suite" -Command $python -Arguments @("manage.py", "test", "--verbosity", "2")

# Seed only the disposable local development database. The demo command is
# guarded by DEBUG=True; Production preflight never creates demo accounts/data.
if (-not $Production) {
    Invoke-Check -Name "Seed local demo data" -Command $python -Arguments @("manage.py", "seed_demo")
    Invoke-Check -Name "Seed operational workflows" -Command $python -Arguments @("manage.py", "seed_operational_workflows")
}

Invoke-Check -Name "Workflow publication gate" -Command $python -Arguments @("manage.py", "audit_workflows")

if ($Production) {
    # Read the effective Django settings rather than PowerShell's process
    # environment: python-dotenv and the service EnvironmentFile may supply
    # values that are not exported into the invoking shell.
    $productionConfigCheck = @"
from django.conf import settings
assert settings.DEBUG is False, "DJANGO_DEBUG must be False"
assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql", "PostgreSQL DATABASE_URL is required"
assert settings.CACHES["default"]["BACKEND"] == "django_redis.cache.RedisCache", "Shared Redis cache is required"
assert len(settings.SECRET_KEY) >= 50, "DJANGO_SECRET_KEY must contain at least 50 characters"
assert settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS != ["localhost", "127.0.0.1"], "Explicit production hosts are required"
assert settings.CSRF_TRUSTED_ORIGINS, "DJANGO_CSRF_TRUSTED_ORIGINS must be configured"
assert bool(settings.CLAMD_HOST), "CLAMD_HOST is required for malware scanning"
assert settings.SECURE_SSL_REDIRECT, "HTTPS redirect must be enabled"
assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE, "Secure session and CSRF cookies are required"
assert settings.SECURE_HSTS_SECONDS >= 31536000, "One-year HSTS must be configured"
assert getattr(settings, "SECURE_PROXY_SSL_HEADER", None) == ("HTTP_X_FORWARDED_PROTO", "https"), "Trusted HTTPS proxy header must be configured"
print("Effective production settings validated.")
"@
    Invoke-Check -Name "Production environment configuration" -Command $python -Arguments @("manage.py", "shell", "-c", $productionConfigCheck)
    Invoke-Check -Name "Production security checks" -Command $python -Arguments @("manage.py", "check", "--deploy")
    Invoke-Check -Name "Static asset collection" -Command $python -Arguments @("manage.py", "collectstatic", "--noinput")
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "ALL REQUESTED PREFLIGHT CHECKS PASSED" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
if (-not $Production) {
    Write-Host "This was the local preflight. Run with -Production only against a staging clone of production; never point the Django test runner at the live production database."
}
