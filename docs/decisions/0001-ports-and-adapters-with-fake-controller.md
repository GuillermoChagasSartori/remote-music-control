# 0001 — Ports and adapters with a fake media controller

**Status:** Accepted · 2026-09-12

## Context

The server must run on Windows because it controls media through Windows-only
APIs (SMTC and the Core Audio API). The libraries for those APIs do not install
on Linux. Development happens mostly on an Ubuntu PC, and CI runners are Linux.
A design that calls Windows APIs directly from the HTTP handlers could only be
run or tested on the studio PC.

## Decision

Use **ports and adapters** (hexagonal architecture):

- A **port** `MediaController` — an abstract interface declaring what the
  application needs: `play_pause()`, `next()`, `previous()`, `set_volume()`,
  `now_playing()`, and so on.
- Two **adapters** implementing it:
  - `FakeMediaController` — pure Python, in-memory track list, runs anywhere.
  - `WindowsMediaController` — real implementation using SMTC and pycaw.
- The API layer depends only on the port. The adapter is chosen once at
  startup from configuration (an environment variable).

## Consequences

- The server, web UI, CLI and the whole test suite run on Ubuntu and in Linux CI.
- Windows is only needed to write and verify one module.
- The fake must behave like the real thing closely enough that bugs don't hide
  in the gap. Integration behaviour specific to Windows (e.g. no browser open)
  still needs manual checks on the Windows PC.
- One small extra layer of indirection to read through.
