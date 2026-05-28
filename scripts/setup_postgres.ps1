# Re:Chord Postgres bootstrap (Windows / PowerShell).
#
# Creates the ``rechord`` role + database if they don't exist, then runs
# Alembic migrations. Idempotent — safe to re-run after schema bumps.
#
# Requires the PostgreSQL admin password (`postgres` superuser by default).
# Local PostgreSQL 16 is detected automatically; for a remote DB (Supabase,
# Neon, RDS) pass -Host/-AdminUser explicitly.
#
# Usage:
#   .\scripts\setup_postgres.ps1                                # local default
#   .\scripts\setup_postgres.ps1 -DbPassword 'mySafePwd'        # custom rechord pw
#   .\scripts\setup_postgres.ps1 -PgHost db.abc.supabase.co `
#                                -AdminUser postgres `
#                                -AdminPassword '...' `
#                                -DbName postgres        # Supabase: schema lives in 'postgres' db

[CmdletBinding()]
param (
    [string]$PgHost = "localhost",
    [int]$Port = 5432,
    [string]$AdminUser = "postgres",
    [string]$AdminPassword = "",
    [string]$DbName = "rechord",
    [string]$DbUser = "rechord",
    [string]$DbPassword = "rechord_dev"
)

$ErrorActionPreference = "Stop"

# --- locate psql -------------------------------------------------------
$psql = "C:\Program Files\PostgreSQL\16\bin\psql.exe"
if (-not (Test-Path $psql)) {
    $psql = (Get-Command psql -ErrorAction SilentlyContinue).Source
}
if (-not $psql) { throw "psql.exe not found. Install PostgreSQL 16 or add it to PATH." }
Write-Host "[setup_postgres] using: $psql" -ForegroundColor Cyan

# --- collect admin password (interactive if not provided) --------------
if (-not $AdminPassword) {
    $secure = Read-Host "Postgres admin ($AdminUser) password" -AsSecureString
    $AdminPassword = [System.Net.NetworkCredential]::new("", $secure).Password
}
$env:PGPASSWORD = $AdminPassword

function Invoke-Psql {
    param([string]$DbConnect, [string]$Sql)
    & $psql -h $PgHost -p $Port -U $AdminUser -d $DbConnect -v ON_ERROR_STOP=1 -c $Sql
    if ($LASTEXITCODE -ne 0) { throw "psql failed (db=$DbConnect): $Sql" }
}

# --- ensure role -------------------------------------------------------
Write-Host "[setup_postgres] ensuring role '$DbUser'..." -ForegroundColor Cyan
$roleCheck = & $psql -h $PgHost -p $Port -U $AdminUser -d postgres -tAc `
    "SELECT 1 FROM pg_roles WHERE rolname='$DbUser'"
if ($roleCheck.Trim() -ne "1") {
    Invoke-Psql -DbConnect postgres -Sql "CREATE ROLE $DbUser LOGIN PASSWORD '$DbPassword';"
    Write-Host "  ✓ role created" -ForegroundColor Green
} else {
    Write-Host "  ✓ role already exists" -ForegroundColor Yellow
}

# --- ensure database ---------------------------------------------------
Write-Host "[setup_postgres] ensuring database '$DbName'..." -ForegroundColor Cyan
$dbCheck = & $psql -h $PgHost -p $Port -U $AdminUser -d postgres -tAc `
    "SELECT 1 FROM pg_database WHERE datname='$DbName'"
if ($dbCheck.Trim() -ne "1") {
    Invoke-Psql -DbConnect postgres -Sql "CREATE DATABASE $DbName OWNER $DbUser ENCODING 'UTF8';"
    Write-Host "  ✓ database created" -ForegroundColor Green
} else {
    Write-Host "  ✓ database already exists" -ForegroundColor Yellow
}

# Grant just in case (no-op when already owner).
Invoke-Psql -DbConnect $DbName -Sql "GRANT ALL PRIVILEGES ON DATABASE $DbName TO $DbUser;"

# --- run alembic -------------------------------------------------------
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

$dbUrl = "postgresql+asyncpg://$DbUser`:$DbPassword@$PgHost`:$Port/$DbName"
Write-Host "[setup_postgres] running alembic upgrade head..." -ForegroundColor Cyan
Write-Host "  DATABASE_URL=$dbUrl" -ForegroundColor DarkGray

$env:DATABASE_URL = $dbUrl
& uv run alembic -c backend/app/db/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }

Write-Host ""
Write-Host "[setup_postgres] DONE" -ForegroundColor Green
Write-Host "Add this to your .env:" -ForegroundColor Cyan
Write-Host "  DATABASE_URL=$dbUrl" -ForegroundColor White
