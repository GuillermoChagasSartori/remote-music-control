# Manual tests on the Windows PC

The automated suite (`uv run pytest`) covers everything except the real Windows
adapter's behaviour: that needs a logged-in desktop session with a browser
playing, which CI machines don't have. CI only checks that the adapter's
packages install and that it imports (`tests/windows/`).

Run this checklist after changing `adapters/windows.py`, updating the Windows
dependencies, or updating Chrome/Firefox significantly. It takes about 10 minutes.

## Setup

1. The server runs **in the desktop session** — normally the logon task from
   `scripts\windows\install-autostart.ps1` — with `RMC_CONTROLLER=windows`.
   Not over SSH, where Windows denies access to media sessions.
2. YouTube Music is playing in Chrome.
3. On a client machine, `music health` prints `server ok` and `token accepted`.

## Checklist

Run each command from the client and compare with what the studio speakers do.
"Correct" means the printed state matches reality immediately — not the state
from before the command.

| # | Action | Expected |
|---|---|---|
| 1 | `music now` | Current title and artist; album line absent if YouTube Music has none |
| 2 | `music pause`, then `music play` | Sound stops/resumes; output shows ⏸ then ▶ |
| 3 | `music toggle` twice | Pauses, then resumes; output matches each time |
| 4 | `music next` | Next song plays; output shows the **new** title (~1 s) |
| 5 | `music prev` early in a song | Previous song; output shows its title |
| 6 | `music prev` late in a song (> 5 s in) | Same song restarts; command returns within ~2 s |
| 7 | `music vol 40`, `music up`, `music down 10` | Browser volume in the Windows volume mixer follows (40, 45, 35); system volume unchanged |
| 8 | `music mute`, `music unmute` | Browser muted in the volume mixer, then unmuted |
| 9 | Web page: press next repeatedly | The page never flashes "Nothing playing" |
| 10 | Close the browser completely, wait 5 s | `music now` → "nothing playing"; `music play` → HTTP 409 |
| 11 | Reopen the browser and start YouTube Music | `music now` works again **without restarting the server** |
| 12 | Repeat 1–8 in **Firefox** (Chrome closed) | Same results; `next` is faster, `prev` may take ~2 s |
| 13 | Check `%APPDATA%\remote-music-control\server.log` | Commands logged with client IP; no tracebacks |
| 14 | End the `pythonw.exe` server processes in Task Manager | `music now` fails, then works again within ~1 minute |
| 15 | Sign out and sign in again (or reboot and sign in) | Server answers shortly after logon, with no window on the desktop |

## Results log

| Date | Chrome | Firefox | Result | Notes |
|---|---|---|---|---|
| 2026-09-13 | ✓ | ✓ | Pass (1–13) | Found and fixed stale state after play/pause (ADR 0008); Firefox reports "paused" briefly during skips |
| 2026-09-13 | ✓ | — | Pass (14) | Watchdog restarted a killed server in 44 s; no duplicate instances. Item 15 pending |
