# 10 — `scripts/windows/`: starting at logon

**Files:**
[`install-autostart.ps1`](../../scripts/windows/install-autostart.ps1) (~160 lines) ·
[`uninstall-autostart.ps1`](../../scripts/windows/uninstall-autostart.ps1) (~45 lines)
**Language:** Windows PowerShell 5.1 (built into Windows 10)
**Runs on:** the studio PC, once at install and again after each update
**Decisions:** ADR 0003 (logon task, not a service), ADR 0011 (the watchdog trigger)

## Where these files sit

Everything on pages 01–09 is the program. These two scripts are about **running
it**: making the server start on its own when you log on, restart itself if it
crashes, be reachable from the LAN, and be easy to find for pairing a phone. In
industry terms this is **deployment** or **packaging** — the part of a project
that turns "works when I start it by hand" into "works unattended".

```
Windows logon ─────────┐
every minute (watchdog)┤
                       ▼
            Task Scheduler: "Remote Music Control"
                       │  runs, inside your desktop session:
                       ▼
   .venv\Scripts\pythonw.exe -m remote_music_control.server   (page 06)
                       │
                       ▼
                listens on 0.0.0.0:8000 ◀── Windows Firewall rule (LAN only)
                                        ◀── desktop shortcut → /pair (page 08)
```

**Scripts in the repository, not steps in a document:** the setup is code, kept
in Git next to the program, reviewed and versioned with it. Running the same
script on another PC produces the same result. This is the idea behind
**infrastructure as code** — here at a very small scale, one PC.

---

## Background

### Why not a Windows service (ADR 0003)

The obvious tool for "a server that starts with Windows" is a **Windows
service**: it starts at boot, before anyone logs on. It can't work here.
Services run in **session 0**, which has no desktop — and Windows only exposes
media sessions (SMTC) and per-application audio inside the logged-in user's
**desktop session**. Measured in Phase 4: from session 0, SMTC answers "access
denied" and pycaw sees no browser. And the browser playing the music only exists
after you log on anyway.

So the server must start **when you log on, as you, inside your session**. The
Windows tool for that is **Task Scheduler**.

| Option | Starts | In your session | Restarts after crash | No window |
|---|---|---|---|---|
| Windows service (e.g. via NSSM, WinSW) | At boot | **No** — can't see the player | Yes | Yes |
| Shortcut in the Startup folder | At logon | Yes | **No** | Needs extra work |
| **Task Scheduler task** (chosen) | At logon | Yes | **Yes, with the watchdog** | Yes, with `pythonw` |

### PowerShell in a few paragraphs

**PowerShell** is Windows' shell and scripting language. Three things make it
different from Bash:

- **Commands are *cmdlets* named `Verb-Noun`:** `Get-ScheduledTask`,
  `Register-ScheduledTask`, `New-NetFirewallRule`. The verbs come from a fixed
  list (`Get`, `Set`, `New`, `Remove`, `Start`, `Stop`…), so you can often guess
  a command's name.
- **The pipeline passes objects, not text.** `Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*server*' }` filters process *objects* by a
  property; no parsing of text columns.
- **Variables start with `$`**, `$_` is "the current item" in a pipeline, and
  `$env:APPDATA` reads an environment variable.

**Windows PowerShell 5.1** ships with Windows 10 and is what these scripts
target, so nothing extra has to be installed. (PowerShell 7 is the newer,
cross-platform version; it would need installing.)

### Task Scheduler's model

A scheduled task has four parts, each built by one cmdlet in the script:

| Part | Question it answers | Cmdlet |
|---|---|---|
| **Action** | What program to run? | `New-ScheduledTaskAction` |
| **Triggers** | When to run it? | `New-ScheduledTaskTrigger` |
| **Principal** | As which user, with what rights, in which kind of session? | `New-ScheduledTaskPrincipal` |
| **Settings** | Time limits, retries, concurrency, priority… | `New-ScheduledTaskSettingsSet` |

`Register-ScheduledTask` combines them into a task. You can see the result in
the Task Scheduler app (`taskschd.msc`) under "Remote Music Control".

---

# Part 1 — `install-autostart.ps1`

## Block 1 — comment-based help and running the script

```powershell
<#
.SYNOPSIS
    Start the Remote Music Control server automatically when you log on.
.DESCRIPTION
    Registers a Task Scheduler task for the current user that: ...
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1
#>
```

`<# ... #>` is a block comment. With keywords like `.SYNOPSIS` and `.EXAMPLE`, it
becomes **comment-based help**: `Get-Help .\install-autostart.ps1 -Full` prints
it like the documentation of a built-in command.

### Execution policy

Why `powershell -ExecutionPolicy Bypass -File ...` and not just
`.\install-autostart.ps1`? By default Windows refuses to run downloaded or
unsigned PowerShell scripts. This PC refused to run even uv's installer
in Phase 4 for that reason. The **execution policy** is that setting.

It is **not a security boundary** — Microsoft's own documentation says so: it's a
safety net against running scripts by accident. `-ExecutionPolicy Bypass` on the
command line applies **only to that one PowerShell process**, leaving the
machine's policy unchanged. That's better than changing the policy for your user
permanently just to run one script.

### ASCII only

Windows PowerShell 5.1 reads a script file **without a BOM** (the invisible
marker from page 04) as the old Windows-1252 encoding. A single "—" or "→" in the
file would be read as garbage characters. Both scripts are therefore plain ASCII
— checked with a `grep` before every commit that touched them.

## Block 2 — stop at the first error

```powershell
$ErrorActionPreference = "Stop"
```

By default, many PowerShell errors are **non-terminating**: the command prints
red text and the script **carries on** to the next line. For an installer that's
dangerous — a failed registration followed by "Server is running!" would be a
lie, and a half-done install is harder to fix than a clean failure.

Setting `$ErrorActionPreference = "Stop"` turns errors into **terminating** ones,
like exceptions in Python: the script stops where the problem happened, showing
it. **Fail fast**, the same principle as the Python code (page 02).

Where an error is *expected* and harmless, a single command opts out with
`-ErrorAction SilentlyContinue` — for example `Get-ScheduledTask` for a task that
may not exist yet.

## Block 3 — finding the repository and checking prerequisites

```powershell
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Pythonw = Join-Path $Repo ".venv\Scripts\pythonw.exe"
$ConfigFile = Join-Path $env:APPDATA "remote-music-control\config.env"

if (-not (Test-Path $Pythonw)) {
    throw "Python environment not found. Run 'uv sync' in $Repo first."
}
if (-not (Test-Path $ConfigFile)) {
    throw "Config file not found. Run 'uv run music-server init' first, then edit $ConfigFile."
}
```

**`$PSScriptRoot`** is the folder containing the running script. Paths are built
from it, so the script works **wherever the repository was cloned** and whatever
folder you run it from. A script that assumes it's run from a particular
directory breaks the first time someone runs it from somewhere else.

**`Join-Path`** combines path parts with the right separator; **`Resolve-Path`**
turns `...\scripts\windows\..\..` into a clean absolute path.

**Prerequisite checks with actionable messages:** the task would register fine
even if Python or the config file were missing — and then fail silently at every
logon. Checking **before** changing anything, and saying exactly which command
fixes the problem, turns a mystery into one step. `throw` stops the script
(terminating error).

## Block 4 — reading the config file (warnings, not errors)

```powershell
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
```

- **`Get-Content`** returns the file as an **array of lines**. Applied to an
  array, **`-match`** returns the lines that match the regular expression — an
  empty array (false) if none. So one expression means "does any line say this?"
- **The regular expressions** tolerate spaces (`\s*`) around `=`, matching what the
  Python parser accepts (page 04), and ignore commented lines, because `^\s*RMC_`
  can't match a line starting with `#`.
- **Warnings, not errors:** a fake-player server or a loopback-only server is a
  valid configuration (for testing), just not the usual one on the studio PC.
  The installer points it out and continues.
- **The port** is read so the firewall rule, desktop shortcut and health check
  use the configured port, not an assumed 8000. `-split '='` splits the line;
  `[int]` converts the text to a number.

**A known simplification:** the script reads the *file*, not environment
variables, so it doesn't see a port set only in the environment. For a logon
task that reads the config file, the file is what matters.

## Block 5 — stopping a server that's already running

```powershell
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName
}
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*remote_music_control.server*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
```

The installer is run again after every update, so it must first stop the old
server — otherwise the new one couldn't bind port 8000.

- **Stop the task** — ends the process Task Scheduler started.
- **Stop any other copy** — for example `uv run music-server` started by hand,
  which also holds the port. **`Get-CimInstance Win32_Process`** asks Windows
  (through WMI/CIM, its management interface) for every process with its full
  command line; the filter keeps only ours. `-like` with `*` is wildcard
  matching.

**Why both `python.exe` and `pythonw.exe`, and why several processes:** a
`.venv` created by uv contains a small **launcher** named `python.exe` or
`pythonw.exe` that starts the real interpreter as a **child process**. One server
therefore appears as **two** processes in Task Manager (seen in Phase 4). The
filter matches both.

## Block 6 — who the task runs as

```powershell
$User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
```

**`[Type]::Method()`** calls a static method of a **.NET** class — PowerShell can
use the whole .NET library directly. `WindowsIdentity.GetCurrent().Name` asks
Windows for the account running the script, as `COMPUTER\user`.

**The bug behind this line (Phase 7):** the first version used
`"$env:USERDOMAIN\$env:USERNAME"`. Run over SSH, `USERDOMAIN` was `WORKGROUP`
instead of the computer name, and registration failed with *"No mapping between
account names and security IDs was done"*. From a desktop terminal it would have
worked — so the bug would have appeared only in some contexts. **Environment
variables describe the session; the identity API describes the account.** Ask the
authority rather than a variable that usually happens to agree.

## Block 7 — the action

```powershell
$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m remote_music_control.server" -WorkingDirectory $Repo
```

- **`pythonw.exe`** — the Windows Python without a console window. With
  `python.exe`, a black console window would sit on the studio desktop for as
  long as the server runs, and closing it would stop the server. The cost —
  there's no stderr — is handled by logging to a file (page 06).
- **`-m remote_music_control.server`** runs the module as a program, the same
  thing `music-server` does, without depending on the console-script launcher.
- **`-WorkingDirectory $Repo`** — a predictable current folder for the process.

## Block 8 — the triggers, and the two that didn't work

```powershell
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$WatchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
$Triggers = @($LogonTrigger, $WatchdogTrigger)
```

**Trigger 1 — at logon** of this user: the server starts within seconds of
signing in. Verified by signing out and in: new server processes appeared at
11:01:12 in the new session, before the desktop had finished loading.

**Trigger 2 — the watchdog:** a time-based trigger starting "now" and repeating
every minute, with no end (`-RepetitionDuration` omitted means indefinitely).
Combined with the setting `MultipleInstances = IgnoreNew` (Block 10):

- **Server running** → the task is already running → the new start is ignored.
- **Server stopped** (crashed, killed) → the task isn't running → it starts.

A **watchdog** is a mechanism that periodically checks something is alive and
restarts it if not — named after the embedded-systems timer that resets a
frozen device.

### The two approaches tested first (ADR 0011)

Both looked right, both were tested by **killing the server process on the
studio PC**, and both failed:

1. **Task Scheduler's "If the task fails, restart every 1 minute" setting.**
   After the kill, the task went back to *Ready* with last result `4294967295`
   (exit code −1) — and nothing happened for over two minutes. That setting only
   retries when the task **fails to launch**. A program that starts successfully
   and exits with an error later doesn't count.
2. **A repetition on the logon trigger** ("repeat every minute"). Also no
   restart. A trigger's repetition only begins **when the trigger fires** — at the
   *next* logon — so it didn't protect the session in which the task was
   installed.

The clock-based trigger was then tested the same way: the server came back **44
seconds** after being killed, and two further firings left exactly one server
running.

**Two lessons in one:** documentation phrases like "restart on failure" describe
what the *author* meant by failure, which may not be yours; and a recovery
mechanism that has never been seen recovering is only a hope.

### Side effect worth knowing

Every minute while the server runs, the watchdog's ignored start is recorded as
the task's "last run result": **`0x800710E0`** ("the operator or administrator
has refused the request"). It looks alarming in the Task Scheduler window. It's
the expected sign that `IgnoreNew` did its job.

After signing out and back in, the task's last run showed 11:02:02 — a minute
after logon — so the watchdog keeps firing across logons.

## Block 9 — the principal

```powershell
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
```

- **`-LogonType Interactive`** — "run only when the user is logged on", **inside
  their desktop session**. This single option is what gives the server access to
  SMTC and the browser's audio. Other logon types (such as running whether the
  user is logged on or not) run in a non-interactive session and would hit the
  same "access denied" as a service.
- **`-RunLevel Limited`** — run **without administrator rights**, even when the
  installing account is an administrator. The server needs no admin rights, so
  it doesn't get them. If a bug in the server were ever exploited over the
  network, the attacker would get a normal user's rights, not an administrator's.
  **Least privilege**, as in CI (page 09).

## Block 10 — settings, and splatting

```powershell
$SettingsOptions = @{
    ExecutionTimeLimit         = [TimeSpan]::Zero
    RestartCount               = 3
    RestartInterval            = (New-TimeSpan -Minutes 1)
    MultipleInstances          = "IgnoreNew"
    Priority                   = 5
    StartWhenAvailable         = $true
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
}
$Settings = New-ScheduledTaskSettingsSet @SettingsOptions
```

### Splatting

`@{ ... }` is a **hashtable** (a dictionary). Passing it with **`@` instead of
`$`** — `@SettingsOptions` — is called **splatting**: each key becomes a
parameter name. It's equivalent to a very long command line, but each option
sits on its own line with room for a comment explaining it. (Backtick line
continuations, the other way to break long commands, can't be followed by a
comment.)

### Each setting

| Setting | Value | Why |
|---|---|---|
| `ExecutionTimeLimit` | `0` (none) | **The default stops a task after 72 hours** — the server would silently die every three days |
| `RestartCount` / `RestartInterval` | 3 × 1 min | Retries a *failed launch* only (Block 8); crashes are the watchdog's job |
| `MultipleInstances` | `IgnoreNew` | Never two servers; makes watchdog firings harmless |
| `Priority` | 5 | Task Scheduler's default, 7, is *below normal* CPU priority; 5 is normal, so the server stays responsive while the PC is busy |
| `StartWhenAvailable` | on | If a start was missed (PC asleep), start as soon as possible |
| `AllowStartIfOnBatteries`, `DontStopIfGoingOnBatteries` | on | Defaults would refuse to start, or stop the task, on battery power — irrelevant to a desktop, but surprising on a laptop |

**`[TimeSpan]::Zero`** — a .NET value meaning "zero duration", which Task
Scheduler interprets as "no limit".

## Block 11 — registering: safe to run again

```powershell
Register-ScheduledTask -TaskName $TaskName `
    -Description "Remote Music Control server: control browser music from other devices on the LAN." `
    -Action $Action -Trigger $Triggers -Principal $Principal -Settings $Settings -Force | Out-Null
```

**`-Force`** replaces an existing task of the same name instead of failing.
Combined with Block 5 (stop first) and the checks in Blocks 12–13 (create only if
missing), the whole script is **idempotent**: running it once or five times
leaves the PC in the same state. That's what lets "run the installer again" be
the update procedure — no separate update script, no "did I already do step 3?".

**Idempotency** (from mathematics: applying an operation twice equals applying it
once) is one of the most valuable properties an installation or deployment
script can have. The HTTP API uses the same word for `PUT` (page 03).

The **backtick** (`` ` ``) at a line end continues a command on the next line.
**`| Out-Null`** discards the task object the cmdlet returns, so it isn't printed.

## Block 12 — the firewall rule

```powershell
$FirewallRuleName = "Remote Music Control (TCP $Port, LAN only)"
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue) {
    Write-Host "Firewall rule '$FirewallRuleName' already exists."
} elseif ($IsAdmin) {
    New-NetFirewallRule -DisplayName $FirewallRuleName ... `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
        -Profile Private -RemoteAddress LocalSubnet | Out-Null
} else {
    Write-Warning "No firewall rule for port $Port. Run this script once as administrator so other devices can connect."
}
```

**Windows Firewall** blocks incoming connections that no rule allows. For phones
and the Ubuntu PC to reach port 8000, a rule is needed. It is made as **narrow**
as the use requires:

| Condition | Value | Effect |
|---|---|---|
| `-Direction Inbound`, `-Protocol TCP`, `-LocalPort $Port` | only this port | Nothing else on the PC is opened |
| `-Profile Private` | only on networks marked Private | On a café or hotel Wi-Fi (marked *Public*), the port stays closed |
| `-RemoteAddress LocalSubnet` | only from the same subnet | Even on a private network, only local devices (`192.168.1.x`) can connect |

Together with the token (ADR 0009), that's **defence in depth**: the rule limits
*who can reach* the server; the token limits *who can use* it.

**Admin rights:** creating firewall rules needs them; registering a task for
yourself doesn't. So the script checks (`IsInRole(Administrator)`) and, without
admin rights, **warns and continues** — the task still installs; only LAN access
is missing. That's why the README says to run it as administrator the first time.
The rule then exists, and later runs (as a normal user) just report it.

**`[Type]` casts:** `[Security.Principal.WindowsPrincipal](...)` converts the
identity into a principal object that can answer role questions — PowerShell's
syntax for .NET type conversion.

## Block 13 — the desktop shortcut

```powershell
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Remote Music Control - pair a device.url"
Set-Content -Path $ShortcutPath -Encoding ASCII -Value @("[InternetShortcut]", "URL=http://127.0.0.1:$Port/pair")
```

A **`.url` file** is Windows' Internet Shortcut format — two lines of text.
Double-clicking it opens the address in the default browser. Simpler than a
`.lnk` shortcut, which is a binary format needing a COM object to create.

**`GetFolderPath("Desktop")`** asks Windows where the desktop really is, rather
than assuming `C:\Users\<name>\Desktop` — the desktop can be redirected, for
example into OneDrive. Asking the system instead of guessing paths is the same
lesson as Block 6.

Writing the file again on every install overwrites it with the current port —
idempotent again.

## Block 14 — start, then check it really works

```powershell
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
if ($Healthy) {
    Write-Host "Server is running: http://127.0.0.1:$Port/health answers."
} else {
    Write-Warning "The server did not answer within 10 seconds. Check the log: $LogFile"
}
```

**The installer doesn't trust its own success.** Registering and starting a task
only proves Task Scheduler accepted it; the server might still fail on a typo in
the config file. So the script polls `/health` — the liveness check from page 03
— every half second for up to 10 seconds (`1..20` is a range of numbers).

- **`Invoke-WebRequest`** makes an HTTP request (PowerShell's `curl`).
  `-UseBasicParsing` avoids depending on Internet Explorer's HTML engine, which
  Windows PowerShell 5.1 otherwise tries to use.
- **`try/catch`** — a refused connection throws; that just means "not yet".
- **On failure, the message says where to look** — the log file path — instead of
  only "failed".

This pattern — after deploying, check the thing actually answers — is a
**post-deployment health check**, standard practice in real deployments.

**A known limitation:** the check always uses `127.0.0.1`. If `RMC_HOST` were set
to a *specific* LAN address instead of `0.0.0.0`, the server would work but not
answer on loopback, and the installer would wrongly warn. With the recommended
`0.0.0.0`, it's accurate.

---

# Part 2 — `uninstall-autostart.ps1`

```powershell
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
} else {
    Write-Host "Task '$TaskName' is not installed."
}

$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Remote Music Control - pair a device.url"
if (Test-Path $ShortcutPath) { Remove-Item $ShortcutPath; ... }

Get-CimInstance Win32_Process ... | ForEach-Object { Stop-Process ... }

Write-Host "Kept: the config file and log in $env:APPDATA\remote-music-control, and the firewall rule."
Get-NetFirewallRule -DisplayName "Remote Music Control (TCP *" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "To remove the firewall rule (as administrator): Remove-NetFirewallRule -DisplayName '$($_.DisplayName)'"
}
```

The reverse of the installer, in the same safe style:

- **Idempotent too:** each step checks before acting, so running it when nothing
  is installed just reports that.
- **`-Confirm:$false`** skips the "are you sure?" prompt, so the script can run
  unattended.
- **Stop leftover processes** — verified in Phase 7: after uninstalling and waiting
  past a watchdog interval, no server process remained.
- **What it deliberately keeps:** the **config file** (with the token), the
  **log**, and the **firewall rule**. Deleting the token would unpair every phone;
  an uninstall followed by a reinstall should need no setup. Removing user data or
  security settings is left as an explicit, separate choice — the **principle of
  least surprise**.
- **Naming the actual firewall rule:** the rule's name contains the port chosen at
  install time. An earlier version always printed the command for `TCP 8000`,
  which would remove nothing if another port had been configured. It now looks up
  existing rules by the prefix `Remote Music Control (TCP *` and prints the exact
  command for each (fixed while writing this page, and verified on the studio PC).
- **`$($_.DisplayName)`** — inside a double-quoted string, `$(...)` evaluates an
  expression (a property of the current object); a plain `$_.DisplayName` would
  insert `$_` followed by the text `.DisplayName`.

---

## How this was verified

These scripts have no automated tests — they need a real Windows logon and Task
Scheduler. Every behaviour was checked on the studio PC instead, and recorded in
[`docs/testing-on-windows.md`](../testing-on-windows.md):

| Check | Result |
|---|---|
| Install over SSH (session 0) | Failed on `WORKGROUP\pedrinho` → fixed with `WindowsIdentity` |
| Server runs in the desktop session, no window | `pythonw.exe` in session 2 (later 3), log in `%APPDATA%` |
| Kill the server, "restart on failure" setting | **Not restarted** → setting abandoned |
| Kill the server, repetition on logon trigger | **Not restarted** → approach abandoned |
| Kill the server, clock-based watchdog | Restarted in 44 s; still one instance after more firings |
| Uninstall, wait past a watchdog tick | No task, no processes, port free |
| Sign out and back in | Server started 11:01:12 in the new session; watchdog kept firing |
| Reinstall after changes (many times) | Same final state every time |

## Known limitations

- **Runs only while you're logged on.** After a power cut or a Windows Update
  restart, nothing runs until someone signs in. Automatic sign-in would close
  that gap; you chose to sign in yourself.
- **A hung server isn't detected.** The watchdog restarts a server that has
  *exited*. A process that's alive but not answering keeps the task "running", so
  the watchdog ignores it. A health-checking watchdog (poll `/health`, restart on
  failure) would be the next step if that ever happens.
- **The repository clone is the installation.** `git pull` changes the files the
  running server uses; the new code takes effect when the installer restarts it.
  Pushing work-in-progress branches to the studio PC's clone therefore affects
  what the next restart runs.
- **The health check assumes loopback** (Block 14).
- **Not tested as a non-administrator.** Every run so far was from an account with
  admin rights; registering a per-user task without them is standard Windows
  behaviour, but hasn't been exercised here.

## Glossary

| Term | Meaning here |
|---|---|
| Deployment / packaging | Making a program run unattended where it's used |
| Infrastructure as code | Setup steps written as versioned scripts, not manual instructions |
| Windows service / session 0 | Background process started at boot / its desktop-less session |
| Task Scheduler / action / trigger / principal / settings | Windows' job runner and the four parts of a task |
| PowerShell / cmdlet / pipeline of objects | Windows shell / `Verb-Noun` command / passing objects between commands |
| Comment-based help | `<# .SYNOPSIS ... #>` read by `Get-Help` |
| Execution policy | Safety setting against accidental script runs; not a security boundary |
| Terminating vs non-terminating error | Stops the script vs prints and continues |
| `$PSScriptRoot` | The running script's folder |
| Prerequisite check | Verifying requirements before changing anything |
| WMI / CIM (`Get-CimInstance`) | Windows' management interface for querying the system |
| Launcher / child process | Small program that starts the real interpreter |
| .NET static method (`[Type]::Method()`) | Calling the .NET library from PowerShell |
| `pythonw.exe` | Python without a console window |
| Watchdog | Periodic check that restarts something that stopped |
| `IgnoreNew` / `0x800710E0` | Don't start a second instance / the result code recorded when that happens |
| Interactive logon type / run level | Run in the user's desktop session / with or without admin rights |
| Least privilege | Giving a process only the rights it needs |
| Hashtable / splatting | PowerShell dictionary / passing it as named parameters with `@` |
| Idempotent | Running it again leaves the same state |
| Firewall profile / `LocalSubnet` | Private/Public/Domain network category / only addresses on the same network |
| Defence in depth | Several independent protections (firewall + token) |
| Internet Shortcut (`.url`) | Two-line text file that opens an address |
| Post-deployment health check | Confirming the deployed service really answers |
| Principle of least surprise | Don't delete data or settings the user wouldn't expect removed |

## Check your understanding

1. Why can't the server run as a Windows service, even though that's the usual
   way to start a server with Windows?
2. What would go wrong without `$ErrorActionPreference = "Stop"` if
   `Register-ScheduledTask` failed?
3. The first installer used `$env:USERDOMAIN\$env:USERNAME`. When did that fail,
   and why is `WindowsIdentity.GetCurrent()` the better source?
4. Explain how the watchdog trigger and `MultipleInstances = IgnoreNew` together
   restart a crashed server without ever starting a second one.
5. Describe the two restart approaches that were tried first. Why did each fail?
   How was that discovered?
6. What happens after three days if `ExecutionTimeLimit` is left at its default?
7. The firewall rule has three restrictions. Name them and what each protects
   against.
8. What makes the installer idempotent, and why does that make "run it again"
   a valid update procedure?
9. Why does the uninstaller keep the config file and the firewall rule?
10. The server process is alive but stuck and not answering. Does the watchdog
    help? What would?
