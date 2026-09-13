# Architecture Decision Records

An ADR is a one-page note that captures a single significant design choice:
the **context** that forced a decision, the **decision** itself, and its
**consequences** (good and bad). ADRs are never edited to change history — if
a decision is reversed, a new ADR supersedes the old one.

| # | Title | Status |
|---|---|---|
| [0001](0001-ports-and-adapters-with-fake-controller.md) | Ports and adapters with a fake media controller | Accepted |
| [0002](0002-smtc-via-winrt-over-media-keys.md) | SMTC via `winrt-*` packages instead of media keys or `winsdk` | Accepted |
| [0003](0003-logon-task-instead-of-windows-service.md) | Start at logon with Task Scheduler, not as a Windows service | Accepted |
| [0004](0004-uv-for-python-and-dependencies.md) | uv for Python version, virtualenv and lockfile | Accepted |
| [0005](0005-async-media-controller-port.md) | The MediaController port is asynchronous | Accepted |
| [0006](0006-http-api-shape.md) | HTTP API shape: RPC-style actions, REST-style state | Accepted |
| [0007](0007-web-client-served-by-server.md) | Web client served by the server, plain JavaScript, polling | Accepted |
| [0008](0008-absorbing-chrome-smtc-session-gaps.md) | Absorbing Chrome's SMTC session gap in the Windows adapter | Accepted |
| [0009](0009-bearer-token-on-the-lan.md) | Shared bearer token for LAN access | Accepted |
| [0010](0010-httpx2-for-the-cli-and-tests.md) | httpx2 instead of httpx for the CLI and tests | Accepted |
| [0011](0011-logon-task-with-watchdog-trigger.md) | Logon task with a clock-based watchdog trigger | Accepted |
