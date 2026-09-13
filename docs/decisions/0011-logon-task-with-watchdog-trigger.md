# 0011 — Logon task with a clock-based watchdog trigger

**Status:** Superseded by [0014](0014-own-player-window-instead-of-the-browser.md) · 2026-09-13 · Implements ADR 0003

## Context

ADR 0003 decided to start the server with a Task Scheduler task at logon,
inside the user's desktop session. Implementing it raised three questions:
how to run without a console window, where logs go, and how the server comes
back if it crashes.

**No window.** `python.exe` needs a console; started by a task it opens a
black window on the studio desktop that anyone could close. `pythonw.exe` runs
without one — but then `sys.stderr` is `None`, so logging (or printing) to
stderr would crash the server before it could report anything.

**Crash recovery.** Two approaches that look right were tested by killing the
server process, and **neither restarted it**:

1. Task Scheduler's *"If the task fails, restart every…"* setting. It only
   retries when the task **fails to launch**. A program that starts and later
   exits with an error leaves the task in *Ready*, and nothing happens.
2. A *repetition* on the logon trigger ("repeat every minute"). The repetition
   only begins when the trigger fires — at the **next** logon — so it does not
   protect the session in which the task was installed.

## Decision

- `scripts/windows/install-autostart.ps1` registers one per-user task with:
  - action `pythonw.exe -m remote_music_control.server` (no window);
  - principal: the current user, *Interactive* logon type (desktop session),
    *Limited* run level (no admin);
  - **trigger 1 — at logon**: starts the server when the user logs on;
  - **trigger 2 — watchdog**: a time trigger starting at install time and
    repeating every minute indefinitely;
  - *MultipleInstances = IgnoreNew*: while the server runs, each watchdog
    firing does nothing; once it has stopped, the next firing starts it;
  - no execution time limit, normal priority.
- Without a console, logs go to a rotating file (`server.log` next to the
  config file, 1 MB × 4 files) unless `RMC_LOG_FILE` says otherwise; errors
  before logging is set up are appended to the same file.
- Unexpected errors are logged and the process exits with code 1.
- The installer is idempotent (safe to re-run) and creates the firewall rule
  when run as administrator; `uninstall-autostart.ps1` removes the task.

## Consequences

- Verified: after the server process was killed, the watchdog started it again
  within a minute (44 s in the test); further firings did not create a second
  instance; uninstalling left nothing running.
- Up to one minute of downtime after a crash.
- A server that hangs without exiting is not detected (the process is still
  "running"). Not observed so far; a health-checking watchdog would be the
  next step if it happens.
- Verified after signing out and in: the logon trigger started the server in
  the new desktop session within seconds, with no console window.
- The watchdog wakes Task Scheduler once a minute; the cost is negligible. Each
  firing while the server runs is recorded as last result `0x800710E0`
  ("request refused") — the expected sign that IgnoreNew prevented a second
  copy, not an error.
- Nothing runs until the user logs on. Unattended recovery after a reboot needs
  Windows automatic sign-in (ADR 0003), which stays the owner's choice.
