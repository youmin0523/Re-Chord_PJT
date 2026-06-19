# Re:Chord — remove the always-on scheduled tasks (reverse of
# install-services.ps1). Run in an ELEVATED PowerShell.
#
#   powershell -ExecutionPolicy Bypass -File deploy\uninstall-services.ps1
#
# Does NOT recreate the logon-only Startup launchers — if you want that mode
# back, ask the assistant or recreate ReChord-Backend.vbs / ReChord-Tunnel.vbs.

#Requires -RunAsAdministrator
$ErrorActionPreference = "SilentlyContinue"
foreach ($t in "ReChord Backend", "ReChord Tunnel") {
    Stop-ScheduledTask -TaskName $t
    Unregister-ScheduledTask -TaskName $t -Confirm:$false
    Write-Host "removed task: $t"
}
Get-NetTCPConnection -LocalPort 7860 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Get-Process cloudflared | Stop-Process -Force
Write-Host "Re:Chord always-on tasks removed and processes stopped."
