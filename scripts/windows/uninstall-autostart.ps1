<#
.SYNOPSIS
    Stop the Remote Music Control server and remove its logon task.

.DESCRIPTION
    Undoes install-autostart.ps1. The config file (with the token), the log
    file and the firewall rule are kept, so reinstalling needs no setup.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\uninstall-autostart.ps1
#>

$ErrorActionPreference = "Stop"

$TaskName = "Remote Music Control"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
} else {
    Write-Host "Task '$TaskName' is not installed."
}

# Make sure no server process is left running.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*remote_music_control.server*' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped server process $($_.ProcessId)."
    }

Write-Host "Kept: the config file and log in $env:APPDATA\remote-music-control, and the firewall rule."
Write-Host "To remove the firewall rule (as administrator): Remove-NetFirewallRule -DisplayName 'Remote Music Control (TCP 8000, LAN only)'"
