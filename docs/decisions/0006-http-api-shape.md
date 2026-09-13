# 0006 — HTTP API shape: RPC-style actions, REST-style state, one state endpoint

**Status:** Accepted · 2026-09-12

## Context

The API must expose playback actions (play, pause, next, previous), settable
values (volume, mute) and a read of the current state, to two clients: the
CLI and a web page that refreshes itself regularly.

Strict REST models everything as resources whose representation you read or
replace. "Skip to the next track" isn't naturally a resource; forcing it into
one (e.g. `PUT /api/queue/position`) makes the API harder to read and requires
the client to know things (the current position) it doesn't need to know.

## Decision

- **Actions** are `POST` to a verb-like path: `/api/play`, `/api/pause`,
  `/api/play-pause`, `/api/next`, `/api/previous`. They return `204 No Content`
  because the real player applies changes asynchronously; clients read the
  result from the state endpoint.
- **Settable values** use `PUT` with the new value: `PUT /api/volume
  {"level": 40}`, `PUT /api/mute {"muted": true}`. `PUT` is idempotent, so a
  retried request can't change the result. Relative changes are actions:
  `POST /api/volume/up?step=5`. Volume endpoints return the resulting volume.
- **`GET /api/state`** returns track, volume and mute together, so a polling
  client needs one request per refresh.
- **No media session** (e.g. browser closed) → `409 Conflict` for commands;
  `GET /api/state` returns `200` with `null` fields, since "nothing playing" is
  a normal thing to display.
- Everything lives under `/api`, leaving `/` for the web page.

## Consequences

- The API reads like the buttons on the UI, which keeps both clients simple.
- It is a pragmatic mix, not textbook REST; this ADR is where that is explained.
- Request bodies are validated by FastAPI (bad input → `422`) before reaching
  the controller.
