<#
.SYNOPSIS
    Start the Remote Music Control server automatically when you log on.

.DESCRIPTION
    Registers a Task Scheduler task for the current user that:
      - starts the server when this user logs on to Windows,
      - runs it inside the desktop session, where Windows exposes media
        sessions and per-app audio (a Windows service could not see them),
      - uses pythonw.exe, so no console window appears,
      - checks every minute and starts it again if it has stopped (crash,
        killed process), for as long as the user is logged on.
    See docs/decisions/0003-logon-task-instead-of-windows-service.md.

    It also puts a "pair a device" shortcut on the desktop, which opens the
    page with QR codes for connecting a phone.

    Safe to run again: it replaces the task with the current settings.
    Run as administrator, it also creates the LAN-only firewall rule.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1
#>

# Stop at the first error instead of carrying on with a half-done install.
$ErrorActionPreference = "Stop"

$TaskName = "Remote Music Control"

# --- Check what the task needs ----------------------------------------------

# $PSScriptRoot is the folder of this script; the repository is two levels up.
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
# pythonw.exe is the Python that runs without opening a console window.
$Pythonw = Join-Path $Repo ".venv\Scripts\pythonw.exe"
$ConfigFile = Join-Path $env:APPDATA "remote-music-control\config.env"

if (-not (Test-Path $Pythonw)) {
    throw "Python environment not found. Run 'uv sync' in $Repo first."
}
if (-not (Test-Path $ConfigFile)) {
    throw "Config file not found. Run 'uv run music-server init' first, then edit $ConfigFile."
}

$Config = Get-Content $ConfigFile
if (-not ($Config -match '^\s*RMC_CONTROLLER\s*=\s*windows\s*$')) {
    Write-Warning "RMC_CONTROLLER=windows is not set in $ConfigFile - the server would control the fake player."
}
if (-not ($Config -match '^\s*RMC_HOST\s*=')) {
    Write-Warning "RMC_HOST is not set in $ConfigFile - the server would only be reachable from this PC."
}
$Port = 8000
$PortLine = $Config -match '^\s*RMC_PORT\s*=\s*\d+\s*$' | Select-Object -First 1
if ($PortLine) { $Port = [int]($PortLine -split '=')[1].Trim() }

# --- Stop a server that is already running ---------------------------------------

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName
}
# Also stop copies started some other way (e.g. by hand), which would hold the port.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*remote_music_control.server*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# --- Register the logon task ------------------------------------------------------------

# Ask Windows for the current account ("COMPUTER\user"). $env:USERDOMAIN is not
# reliable: in some sessions (e.g. over SSH) it says "WORKGROUP", which Task
# Scheduler can't match to any account.
$User = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m remote_music_control.server" -WorkingDirectory $Repo
# Two triggers:
# 1. At logon: start the server as soon as this user logs on.
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $User
# 2. Watchdog: a clock-based trigger that fires every minute, indefinitely,
#    starting now. Because MultipleInstances is IgnoreNew (below), each firing
#    does nothing while the server runs; if the server has stopped (crashed,
#    process killed), the next firing starts it again.
#    Two approaches that looked simpler were tested and do NOT work:
#    - the "restart on failure" setting only retries when the task fails to
#      launch, not when the program exits with an error later;
#    - a repetition on the logon trigger only starts at the next logon, so it
#      doesn't protect the session in which the task was installed.
#    Omitting -RepetitionDuration means "repeat indefinitely".
$WatchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
$Triggers = @($LogonTrigger, $WatchdogTrigger)
# Interactive = run only while this user is logged on, inside their desktop session.
# Limited = no administrator rights are needed or used.
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited

# A hashtable passed with @ ("splatting") lets each option carry a comment.
$SettingsOptions = @{
    ExecutionTimeLimit         = [TimeSpan]::Zero         # never stop it (the default stops tasks after 3 days)
    RestartCount               = 3                        # retry if Windows fails to *launch* it...
    RestartInterval            = (New-TimeSpan -Minutes 1) # ...after 1 minute (crashes are handled by the watchdog)
    MultipleInstances          = "IgnoreNew"              # never run two servers; makes the watchdog repeats harmless
    Priority                   = 5                        # normal priority (the task default, 7, is below normal)
    StartWhenAvailable         = $true                    # start as soon as possible if a start was missed
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
}
$Settings = New-ScheduledTaskSettingsSet @SettingsOptions

Register-ScheduledTask -TaskName $TaskName `
    -Description "Remote Music Control server: control browser music from other devices on the LAN." `
    -Action $Action -Trigger $Triggers -Principal $Principal -Settings $Settings -Force | Out-Null
Write-Host "Registered task '$TaskName': starts at logon of $User and restarts the server within a minute if it stops."

# --- Firewall rule (needs administrator) ----------------------------------------------------

$FirewallRuleName = "Remote Music Control (TCP $Port, LAN only)"
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue) {
    Write-Host "Firewall rule '$FirewallRuleName' already exists."
} elseif ($IsAdmin) {
    New-NetFirewallRule -DisplayName $FirewallRuleName `
        -Description "Inbound access to the Remote Music Control server from the local subnet on private networks." `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -Profile Private -RemoteAddress LocalSubnet | Out-Null
    Write-Host "Created firewall rule '$FirewallRuleName'."
} else {
    Write-Warning "No firewall rule for port $Port. Run this script once as administrator so other devices can connect."
}

# --- Desktop shortcut to the pairing page ---------------------------------------------------

# A .url file is Windows' "Internet shortcut": double-clicking it opens the
# address in the default browser. The pairing page only opens on this PC.
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Remote Music Control - pair a device.url"
Set-Content -Path $ShortcutPath -Encoding ASCII -Value @("[InternetShortcut]", "URL=http://127.0.0.1:$Port/pair")
Write-Host "Desktop shortcut: $ShortcutPath"

# --- Start it now and check it answers ----------------------------------------------------------

Start-ScheduledTask -TaskName $TaskName
$Healthy = $false
foreach ($Attempt in 1..20) {
    Start-Sleep -Milliseconds 500
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$Port/health"
        if ($Response.StatusCode -eq 200) { $Healthy = $true; break }
    } catch {
        # Not listening yet; try again.
    }
}

$LogFile = Join-Path $env:APPDATA "remote-music-control\server.log"
if ($Healthy) {
    Write-Host "Server is running: http://127.0.0.1:$Port/health answers."
} else {
    Write-Warning "The server did not answer within 10 seconds. Check the log: $LogFile"
}
Write-Host "Log file: $LogFile"
Write-Host "To connect a phone: open the desktop shortcut, or http://127.0.0.1:$Port/pair, and scan a QR code."
Write-Host "To remove: powershell -ExecutionPolicy Bypass -File scripts\windows\uninstall-autostart.ps1"
