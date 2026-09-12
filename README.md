# Remote Music Control

Control YouTube Music playing in a browser on a Windows PC — play/pause, skip,
volume, now-playing — from a web page or a CLI on any other machine on the same
home network.

> **Status:** early development (Phase 0 — scaffold). Nothing runs yet.

## Why

The speakers are on the studio PC (Windows 10). The work happens on another PC
(Ubuntu) with only Bluetooth headphones. This project removes the walk between
the two.

## Architecture (planned)

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
src/remote_music_control/   application package (server, core, adapters, CLI)
tests/                      unit and integration tests (from Phase 1)
docs/decisions/             Architecture Decision Records (ADRs)
docs/walkthrough/           block-by-block explanation of the code
```

## Development setup

Requires [uv](https://docs.astral.sh/uv/), which also installs the right Python
version (pinned in `.python-version`).

```bash
git clone git@github.com:GuillermoChagasSartori/remote-music-control.git
cd remote-music-control
uv sync          # creates .venv and installs the locked dependencies
```

Install steps for the Windows server, configuration, and usage will be added as
the phases land.

## License

[MIT](LICENSE)
