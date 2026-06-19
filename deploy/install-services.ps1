# Re:Chord — install backend + Cloudflare tunnel as auto-start, crash-
# restarting scheduled tasks. Run this ONCE in an ELEVATED (Administrator)
# PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File deploy\install-services.ps1
#
# No password needed: the tasks run at LOGON as the current user (Interactive
# logon type) with auto-restart on crash. This is the right mode for an
# account with NO Windows password — Windows blocks blank-password "run
# whether logged on or not" tasks, so we use the logon-triggered variant.
# Practically identical for a passwordless account (login is instant / can be
# automatic). The only thing it can't do is start BEFORE any login — for that
# you'd need to set a Windows password (then switch to -LogonType Password).
#
# This replaces the Startup-folder .vbs launchers (removes them on success).
# Undo with deploy\uninstall-services.ps1.

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$me   = "$env:USERDOMAIN\$env:USERNAME"

Write-Host "=== Re:Chord auto-start install (no password / logon mode) ===" -ForegroundColor Cyan
Write-Host "Tasks run as: $me  (at logon, hidden, auto-restart on crash)"

# --- 1) Stop the current logon-launcher processes so the tasks can bind ---
Write-Host "Stopping current backend (7860) + tunnel ..."
Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2

# --- 2) Register the two tasks (Interactive logon — no password) ---
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Highest

function Install-RechordTask($name, $script) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\$script`""
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force | Out-Null
    Write-Host "  registered: $name" -ForegroundColor Green
}
Install-RechordTask "ReChord Backend" "run-backend.ps1"
Install-RechordTask "ReChord Tunnel"  "run-tunnel.ps1"

# --- 3) Start them now + verify ---
Start-ScheduledTask -TaskName "ReChord Backend"
Start-ScheduledTask -TaskName "ReChord Tunnel"
Write-Host "Waiting for backend health (up to 60s) ..."
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep 2
    try { if ((Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7860/health -TimeoutSec 3).StatusCode -eq 200) { $ok = $true; break } } catch {}
}
Write-Host ("Local backend /health 200: {0}" -f $ok) -ForegroundColor $(if($ok){"Green"}else{"Red"})

# --- 4) On success, retire the logon-only Startup launchers (avoid double-run) ---
if ($ok) {
    $startup = [Environment]::GetFolderPath('Startup')
    Remove-Item "$startup\ReChord-Backend.vbs","$startup\ReChord-Tunnel.vbs" -ErrorAction SilentlyContinue
    Write-Host "Removed Startup-folder launchers (tasks replace them)." -ForegroundColor Green
    Write-Host ""
    Write-Host "DONE. Re:Chord now auto-starts at logon and auto-restarts on crash." -ForegroundColor Cyan
    Write-Host "Verify:  https://api.youmin.site/health   and   https://youmin.site"
    Write-Host "(For unattended reboots with zero clicks, optionally enable Windows"
    Write-Host " auto-login, or set a password and ask to switch to no-login mode.)"
} else {
    Write-Host "Backend did not come up — keeping the Startup launchers as fallback." -ForegroundColor Yellow
    Write-Host "Check Task Scheduler > 'ReChord Backend' > Last Run Result."
}
Get-ScheduledTask -TaskName "ReChord*" | Select-Object TaskName, State | Format-Table -AutoSize
