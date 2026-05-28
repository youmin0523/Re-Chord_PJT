# Re:Chord Postgres backup — gzip'd pg_dump rotated by date (Windows).
#
# Usage:
#   .\scripts\backup_postgres.ps1
#   .\scripts\backup_postgres.ps1 -DumpDir D:\backups -RetainDays 14
#   $env:PGPASSWORD = '...'; .\scripts\backup_postgres.ps1 -PgHost db.foo.supabase.co

[CmdletBinding()]
param (
    [string]$PgHost = "localhost",
    [int]$Port = 5432,
    [string]$User = "rechord",
    [string]$DbName = "rechord",
    [string]$DumpDir = ".\backups",
    [int]$RetainDays = 30
)

$ErrorActionPreference = "Stop"

# --- locate pg_dump ---------------------------------------------------
$pgDump = "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
if (-not (Test-Path $pgDump)) {
    $pgDump = (Get-Command pg_dump -ErrorAction SilentlyContinue).Source
}
if (-not $pgDump) { throw "pg_dump.exe not found. Install PostgreSQL 16 or add to PATH." }

New-Item -ItemType Directory -Force -Path $DumpDir | Out-Null

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$out = Join-Path $DumpDir "${DbName}_${stamp}.sql.gz"

Write-Host "[backup] dumping $DbName@$PgHost → $out" -ForegroundColor Cyan

# pg_dump → stdout, piped through gzip via .NET (no external gzip dep).
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pgDump
$psi.Arguments = "--host=$PgHost --port=$Port --username=$User --dbname=$DbName --no-owner --no-privileges --serializable-deferrable"
$psi.RedirectStandardOutput = $true
$psi.UseShellExecute = $false
$p = [System.Diagnostics.Process]::Start($psi)

$outStream = [System.IO.File]::Create($out)
$gzip = New-Object System.IO.Compression.GZipStream($outStream, [System.IO.Compression.CompressionLevel]::Optimal)
$p.StandardOutput.BaseStream.CopyTo($gzip)
$gzip.Close()
$outStream.Close()
$p.WaitForExit()

if ($p.ExitCode -ne 0) { throw "pg_dump failed with exit $($p.ExitCode)" }

$size = (Get-Item $out).Length
Write-Host "[backup] OK ($([math]::Round($size/1MB,2)) MB)" -ForegroundColor Green

# --- retention --------------------------------------------------------
Write-Host "[backup] expiring dumps older than $RetainDays days..." -ForegroundColor Cyan
Get-ChildItem $DumpDir -Filter "${DbName}_*.sql.gz" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$RetainDays) } |
    ForEach-Object {
        Write-Host "  removing $($_.Name)" -ForegroundColor Yellow
        Remove-Item $_.FullName -Force
    }

# --- freshness sentinel for monitoring ------------------------------
$out | Out-File -Encoding utf8 (Join-Path $DumpDir ".last_successful_dump")
(Get-Date -Format "o") | Out-File -Encoding utf8 (Join-Path $DumpDir ".last_successful_dump_ts")
