# Re:Chord — install backend + Cloudflare tunnel as always-on Windows
# scheduled tasks (run at BOOT, whether logged on or not, auto-restart on
# crash). Run this ONCE in an ELEVATED (Administrator) PowerShell.
#
#   powershell -ExecutionPolicy Bypass -File deploy\install-services.ps1
#
# You will be prompted for YOUR Windows password — Task Scheduler stores it
# so the tasks can run without you being logged in. It is entered into the
# standard Windows credential dialog and is never printed or sent anywhere.
#
# This replaces the logon-only Startup-folder launchers (it removes them on
# success). To undo: deploy\uninstall-services.ps1.

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$me   = "$env:USERDOMAIN\$env:USERNAME"

Write-Host "=== Re:Chord always-on install ===" -ForegroundColor Cyan
Write-Host "Tasks will run as: $me (at startup, whether logged on or not)"
$cred = Get-Credential -UserName $me -Message "Enter the Windows password for $me (stored by Task Scheduler so Re:Chord runs without login)"
$pw = $cred.GetNetworkCredential().Password
if (-not $pw) { throw "No password entered — aborting." }

# --- 1) Stop the current logon-launcher processes so the tasks can bind ---
Write-Host "Stopping current backend (7860) + tunnel ..."
Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 2

# --- 2) Register the two tasks ---
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$trigger = New-ScheduledTaskTrigger -AtStartup

function Install-RechordTask($name, $script) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\deploy\$script`""
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -User $cred.UserName -Password $pw -RunLevel Highest -Force | Out-Null
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
Write-Host ("Local backend /health 200: {0}" -f $ok) -ForegroundColor ($(if($ok){"Green"}else{"Red"}))

# --- 4) On success, retire the logon-only Startup launchers ---
if ($ok) {
    $startup = [Environment]::GetFolderPath('Startup')
    Remove-Item "$startup\ReChord-Backend.vbs","$startup\ReChord-Tunnel.vbs" -ErrorAction SilentlyContinue
    Write-Host "Removed Startup-folder launchers (tasks replace them)." -ForegroundColor Green
    Write-Host ""
    Write-Host "DONE. Re:Chord now starts at boot without login." -ForegroundColor Cyan
    Write-Host "Verify public:  https://api.youmin.site/health  and  https://youmin.site"
    Write-Host "IMPORTANT: reboot once and (without logging in for a few min) check"
    Write-Host "https://api.youmin.site/health returns 200 — that proves the no-login"
    Write-Host "path works. If a conversion fails only after a no-login reboot, GPU may"
    Write-Host "need an interactive session; re-run with AtLogon and tell the assistant."
} else {
    Write-Host "Backend did not come up — keeping the Startup launchers as fallback." -ForegroundColor Yellow
    Write-Host "Check: Task Scheduler > 'ReChord Backend' > Last Run Result, and run-backend.ps1."
}
Get-ScheduledTask -TaskName "ReChord*" | Select-Object TaskName, State | Format-Table -AutoSize
