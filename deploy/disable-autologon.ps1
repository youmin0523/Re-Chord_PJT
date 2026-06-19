# Re:Chord — disable Windows auto-login (reverse of enable-autologon.ps1).
# Run in an ELEVATED PowerShell.
#
#   powershell -ExecutionPolicy Bypass -File deploy\disable-autologon.ps1

#Requires -RunAsAdministrator
$ErrorActionPreference = "SilentlyContinue"
$winlogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
Set-ItemProperty $winlogon -Name "AutoAdminLogon" -Value "0" -Type String
Remove-ItemProperty $winlogon -Name "DefaultPassword"
Write-Host "Auto-login disabled."
