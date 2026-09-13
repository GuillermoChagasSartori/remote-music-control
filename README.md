# Remote Music Control

Control YouTube Music playing in a browser on a Windows PC — play/pause, skip,
volume, now-playing — from a web page or a CLI on any other device on the same
home network.

> **Status:** early development (Phase 5). Works end to end over the LAN with
> token authentication, against YouTube Music in Chrome or Firefox on Windows.
> Automated tests and CI (Phase 6) and start-at-logon packaging (Phase 7) are next.

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
  web/                      the web page: index.html, style.css, app.js
docs/decisions/             Architecture Decision Records (ADRs)
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

2. **Allow the port on the local network only** (PowerShell as administrator):

   ```powershell
   New-NetFirewallRule -DisplayName "Remote Music Control (TCP 8000, LAN only)" `
     -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 `
     -Profile Private -RemoteAddress LocalSubnet
   ```

   The Wi-Fi/Ethernet connection must be set to the *Private* network profile.

3. **Start the server from a terminal in the desktop session** (not over SSH),
   with YouTube Music open in Chrome or Firefox:

   ```powershell
   uv run music-server
   ```

   The server must run in the logged-in user's session: Windows only exposes
   media sessions and per-app audio there. A process started over SSH or as a
   Windows service gets "access denied"
   ([ADR 0003](docs/decisions/0003-logon-task-instead-of-windows-service.md)).
   Automatic start at logon comes in Phase 7.

### On a client

- **Browser or phone:** open the pairing link printed by `init`, e.g.
  `http://desktop-name.local:8000/#token=…`. The page stores the token and
  removes it from the address bar. Without the link, the page asks for the
  token. If `.local` names don't resolve on your network, use the PC's IP
  address, ideally reserved in the router.
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

The server logs to stderr: startup, every command (`POST /api/next -> 204 in
950 ms (from 192.168.1.20)`), rejected tokens, player failures and unexpected
errors with tracebacks. Polling requests are not logged.

## License

[MIT](LICENSE)
