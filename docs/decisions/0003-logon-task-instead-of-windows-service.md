# 0003 — Start at logon with Task Scheduler, not as a Windows service

**Status:** Superseded by [0014](0014-own-player-window-instead-of-the-browser.md) · 2026-09-12

## Context

The server should start automatically on the studio PC. The original plan was
a Windows service that runs at boot without anyone logging in.

Windows services run in **Session 0**, an isolated session with no desktop.
SMTC media sessions and per-application audio sessions belong to the
interactive user's session. A service would see no browser, no media session
and no browser audio. And the browser playing YouTube Music can't run until a
user is logged in anyway.

## Decision

Register the server as a **Task Scheduler task triggered "At log on"** for the
user, running without a console window and configured to restart on failure.
If the PC must recover unattended after a reboot, enable Windows automatic
sign-in for that user.

## Consequences

- The server runs in the same session as the browser, so SMTC and pycaw work.
- "Starts on boot" becomes "starts at logon"; with auto sign-in the practical
  result is the same.
- Auto sign-in stores the password in a way a local attacker could recover; an
  acceptable trade-off for a studio PC at home, but it is opt-in.
- Task Scheduler is built into Windows; no extra service wrapper (NSSM, WinSW)
  is needed.
