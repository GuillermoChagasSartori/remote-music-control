# Remote Music Control

[![CI](https://github.com/GuillermoChagasSartori/remote-music-control/actions/workflows/ci.yml/badge.svg)](https://github.com/GuillermoChagasSartori/remote-music-control/actions/workflows/ci.yml)

Control YouTube Music playing in a browser on a Windows PC — play/pause, skip,
volume, now-playing — from a web page or a CLI on any other device on the same
home network.

> **Status:** Phases 0–7 complete. Works end to end over the LAN with token
> authentication, against YouTube Music in Chrome or Firefox on Windows; the
> server starts at logon and restarts itself after a crash. Automated tests run
> on Linux and Windows.

<p align="center">
  <img src="docs/images/web-ui.png" alt="Web UI showing the current track, playback buttons and volume controls" width="320">
</p>

## Why

The speakers are on the studio PC (Windows 10). The work happens on another PC
(Ubuntu) with only Bluetooth headphones. This project removes the walk between
the two.

## Architecture

```
 Ubuntu PC / phone                         Windows PC
┌──────────────────┐   HTTP + token   ┌───────────────────────────────────────┐
│ web page  or CLI │ ───────────────▶ │ FastAPI server                        │
└──────────────────┘       LAN        │   └─ MediaController  (port)          │
                                      │        ├─ WindowsMediaController      │
                                      │        │    SMTC (winrt) + pycaw      │
                                      │        └─ FakeMediaController         │
                                      │             in-memory, runs anywhere  │
                                      └───────────────────────────────────────┘
```

The server talks to an abstract `MediaController` interface. The real Windows
implementation and an in-memory fake are interchangeable by configuration, so
everything except one adapter is developed and tested on Linux. See
[ADR 0001](docs/decisions/0001-ports-and-adapters-with-fake-controller.md).

## Repository layout

```
src/remote_music_control/   application package
  media_controller.py       the port: MediaController interface and data types
  adapters/fake.py          in-memory adapter (any OS)
  adapters/windows.py       real adapter: SMTC + Core Audio (Windows only)
  api.py                    HTTP API, authentication, error handling
  config.py                 environment variables and the config file
  server.py                 `music-server`: wiring, logging, `init`
  cli.py                    `music` command-line client
  pairing.py                the pairing page: QR codes and network details
  web/                      the web pages: player (index.html, app.js), pairing (pair.html), style.css
scripts/windows/            install/uninstall the start-at-logon task
tests/
  unit/                     one module at a time (fake player, config, CLI parsing, server)
  integration/              the real app over HTTP, and the CLI against it, using the fake
  windows/                  smoke tests for the Windows adapter (run only on Windows)
.github/workflows/ci.yml    GitHub Actions: tests on Ubuntu and Windows
docs/decisions/             Architecture Decision Records (ADRs)
docs/testing-on-windows.md  manual checklist for the real Windows adapter
docs/walkthrough/           block-by-block explanation of the code
```

## Installation

Both machines need [Git](https://git-scm.com/) and
[uv](https://docs.astral.sh/uv/getting-started/installation/); uv installs the
right Python version (pinned in `.python-version`) by itself.

```bash
git clone https://github.com/GuillermoChagasSartori/remote-music-control.git
cd remote-music-control
uv sync          # creates .venv; Windows-only packages install only on Windows
```

### On the Windows PC (the server)

1. **Create the config file and token:**

   ```powershell
   uv run music-server init
   ```

   This writes `%APPDATA%\remote-music-control\config.env` and prints the
   token and a pairing link. Open that file and uncomment:

   ```ini
   RMC_CONTROLLER=windows
   RMC_HOST=0.0.0.0
   ```

2. **Install the start-at-logon task.** In PowerShell **as administrator** the
   first time (so it can also create the firewall rule), from the repository
   folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1
   ```

   This registers a Task Scheduler task that starts the server when you log
   on — with no console window — and checks every minute, starting it again
   if it has stopped. It starts the server right away and confirms it answers.
   It also creates a firewall rule allowing TCP 8000 only from the local subnet
   on *Private* networks, so the Wi-Fi/Ethernet connection must use the
   *Private* network profile. Re-running the script is safe.

   Why a logon task and not a Windows service: Windows only exposes media
   sessions and per-app audio inside the logged-in user's session; a service
   (or anything started over SSH) gets "access denied"
   ([ADR 0003](docs/decisions/0003-logon-task-instead-of-windows-service.md),
   [ADR 0011](docs/decisions/0011-logon-task-with-watchdog-trigger.md)).

3. **Open YouTube Music** in Chrome or Firefox.

To stop and remove the task:
`powershell -ExecutionPolicy Bypass -File scripts\windows\uninstall-autostart.ps1`
(the config file, log and firewall rule are kept).

To run the server by hand instead (for development), stop the task and run
`uv run music-server` from a terminal on the Windows desktop.

**Updating** the Windows PC to a newer version: in the repository folder run
`git pull`, `uv sync`, then the install script again (it restarts the server).

**Surviving a reboot:** the task starts at logon, so after a reboot nothing
runs until someone logs on. For a studio PC that should recover unattended,
enable Windows automatic sign-in — preferably with Microsoft's Sysinternals
[Autologon](https://learn.microsoft.com/sysinternals/downloads/autologon),
which stores the password encrypted rather than in plain text in the registry.
This lets anyone who can switch the PC on use your account, so it is a
deliberate trade-off.

### On a client

- **Phone or browser — easiest:** on the Windows PC, double-click the desktop
  shortcut **"Remote Music Control - pair a device"** (or open
  `http://127.0.0.1:8000/pair` there) and scan a QR code with the phone. The
  page opens the remote and stores the token on the device.
  - The **"Any phone"** code uses the PC's IP address. It's needed on
    **Android**, whose browsers can't resolve `.local` names.
  - The **"iPhone or computer"** code uses the PC's name and keeps working if
    the IP changes.
  - If the PC's IP changes, phones paired by IP stop connecting: scan again.
    The same page explains how to prevent that with a DHCP reservation on the
    router, filled in with this PC's details.

  The pairing page opens only on the Windows PC itself, because it contains
  the token ([ADR 0012](docs/decisions/0012-pairing-page-on-the-server-pc.md)).
  `music-server init` also prints the same links as text.
- **CLI:** create `~/.config/remote-music-control/config.env` (Linux) readable
  only by you (`chmod 600`):

  ```ini
  RMC_SERVER_URL=http://desktop-name.local:8000
  RMC_TOKEN=<the token from the server's config file>
  ```

  Then `uv run music health` should print `server ok` and `token accepted`.

### Development without Windows

The fake adapter runs anywhere. Run `uv run music-server init` once (it creates
the config file with a token and the default `RMC_CONTROLLER=fake`), then:

```bash
uv run music-server        # serves http://127.0.0.1:8000/ with the fake player
uv run music now           # in a second terminal
```

Interactive API docs are at <http://127.0.0.1:8000/docs> (use **Authorize**
with the token).

## Tests

```bash
uv run pytest                # all tests, with a coverage report
uv run pytest tests/unit     # only the unit tests
uv run pytest -k volume      # only tests whose name contains "volume"
```

- **Unit tests** check one module in isolation: the fake player, config
  parsing, CLI argument parsing and output, server startup.
- **Integration tests** run the real FastAPI app in-process against the fake
  player — authentication, every endpoint, validation, error responses,
  security headers, logging — and the `music` CLI against that app.
- **Windows smoke tests** check that the real adapter's packages install and
  import; they are skipped on other systems.
- Warnings fail the tests, so deprecations are noticed when they appear.

CI runs the suite on Ubuntu and Windows for every push. The real adapter's
behaviour needs a desktop session with a browser, so it is checked by hand:
[docs/testing-on-windows.md](docs/testing-on-windows.md).

## Usage

### Web page

Open the server's address in any browser. The page refreshes itself every
second while visible, works on phones, and follows the system light/dark
theme. Design rationale: [ADR 0007](docs/decisions/0007-web-client-served-by-server.md).

### CLI

```text
music now              show current track and volume
music play | pause     resume / pause
music toggle           play if paused, pause if playing
music next | prev      skip forward / back
music vol [LEVEL]      show the volume, or set it (0–100)
music up | down [STEP] change the volume by STEP points (default 5)
music mute | unmute
music health           check the server is reachable and the token accepted
```

### HTTP API

All `/api` routes require `Authorization: Bearer <token>`.

| Method & path | Body / query | Response |
|---|---|---|
| `GET /health` (public) | | `{"status": "ok"}` |
| `GET /api/state` | | track, volume, muted (`null`s if nothing is open) |
| `POST /api/play` · `/pause` · `/play-pause` · `/next` · `/previous` | | `204 No Content` |
| `GET /api/volume` | | `{"volume": 40, "muted": false}` |
| `PUT /api/volume` | `{"level": 40}` | same as above |
| `POST /api/volume/up` · `/api/volume/down` | `?step=5` (optional) | same as above |
| `PUT /api/mute` | `{"muted": true}` | same as above |

| Status | Meaning |
|---|---|
| `401` | missing or wrong token |
| `409` | no media session (e.g. the browser is closed) |
| `422` | invalid input |
| `502` | the player rejected the command |
| `500` | unexpected server error (details only in the server log) |

Transport commands reply once their effect is visible — up to ~2 s for a skip
([ADR 0008](docs/decisions/0008-absorbing-chrome-smtc-session-gaps.md)). API
design rationale: [ADR 0006](docs/decisions/0006-http-api-shape.md).

## Configuration

Settings come from environment variables, then the config file, then defaults
([twelve-factor](https://12factor.net/config) style; all in
`src/remote_music_control/config.py`). The config file is `KEY=VALUE` lines:

- Windows: `%APPDATA%\remote-music-control\config.env`
- Linux: `~/.config/remote-music-control/config.env`

| Variable | Used by | Default | Meaning |
|---|---|---|---|
| `RMC_TOKEN` | both | — (required by the server) | Shared secret; at least 32 characters |
| `RMC_CONTROLLER` | server | `fake` | Media adapter: `fake` or `windows` |
| `RMC_HOST` | server | `127.0.0.1` | Address to listen on; `0.0.0.0` for the LAN |
| `RMC_PORT` | server | `8000` | Port to listen on |
| `RMC_PLAYER_APPS` | server | `chrome.exe,firefox.exe` | Windows adapter: executables whose media and volume are controlled |
| `RMC_LOG_LEVEL` | server | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `RMC_LOG_FILE` | server | stderr, or `server.log` next to the config file without a console | Write the log to this file (rotated at 1 MB) |
| `RMC_SERVER_URL` | CLI | `http://127.0.0.1:8000` | Where the CLI sends requests (`--url` overrides) |
| `RMC_CONFIG_FILE` | both | see above | Use a different config file |

## Security

Anyone on the home network can reach the server, so every command requires a
shared bearer token, compared in constant time. The token travels in a header
(which also blocks cross-site requests from web pages), is stored outside the
repository, and is never logged. The firewall rule limits the port to the local
subnet on private networks. Traffic is plain HTTP: someone able to decrypt the
Wi-Fi could read the token — an accepted risk for a home music remote. Full
threat model: [ADR 0009](docs/decisions/0009-bearer-token-on-the-lan.md).

## Logging

The server logs startup, every command (`POST /api/next -> 204 in 950 ms (from
192.168.1.20)`), rejected tokens, player failures and unexpected errors with
tracebacks. Polling requests are not logged.

- Started from a terminal: to the terminal (stderr).
- Started by the logon task (no console): to `server.log` next to the config
  file, e.g. `%APPDATA%\remote-music-control\server.log`, rotated at 1 MB with
  3 old files kept.
- `RMC_LOG_FILE` sends the log to a specific file in either case.

On Windows, follow it live with
`Get-Content "$env:APPDATA\remote-music-control\server.log" -Wait -Tail 20`.

## License

[MIT](LICENSE)
