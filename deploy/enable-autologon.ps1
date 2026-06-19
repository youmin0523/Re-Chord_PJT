# Re:Chord — enable Windows auto-login so the PC boots straight to the
# desktop (no click), which lets the AtLogon "ReChord Backend/Tunnel" tasks
# start automatically after a reboot. Run ONCE in an ELEVATED PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File deploy\enable-autologon.ps1
#
# Safe for this machine: the account has NO Windows password, so auto-login
# (console logon with a blank password) doesn't lower security — anyone with
# physical access could already sign in with one click. To undo:
#   deploy\disable-autologon.ps1

#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$winlogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"

Set-ItemProperty $winlogon -Name "AutoAdminLogon"    -Value "1"               -Type String
Set-ItemProperty $winlogon -Name "DefaultUserName"   -Value $env:USERNAME     -Type String
Set-ItemProperty $winlogon -Name "DefaultDomainName" -Value $env:COMPUTERNAME -Type String
Set-ItemProperty $winlogon -Name "DefaultPassword"   -Value ""               -Type String
# Clear any leftovers that would limit auto-login to N boots.
Remove-ItemProperty $winlogon -Name "AutoLogonCount" -ErrorAction SilentlyContinue
Remove-ItemProperty $winlogon -Name "AutoLogonSID"   -ErrorAction SilentlyContinue

Write-Host "=== Auto-login enabled ===" -ForegroundColor Green
Get-ItemProperty $winlogon | Select-Object AutoAdminLogon, DefaultUserName, DefaultDomainName | Format-List
Write-Host "Reboot to confirm: the PC should land on the desktop with no sign-in"
Write-Host "click, and https://api.youmin.site/health should return 200 shortly after." -ForegroundColor Cyan
