# 0007 — Web client served by the server, plain JavaScript, polling

**Status:** Accepted · 2026-09-12

## Context

The controls must be usable from the Ubuntu PC, ideally from a phone too, and
installing anything on the client machines is undesirable. The UI is a single
screen: track info, three transport buttons, a volume slider and three volume
buttons. The server already speaks HTTP.

Options considered for the client:

1. **Native desktop app** (GTK, Qt, Electron): per-platform install and
   packaging, a second codebase for phones.
2. **Web page served by the same server**: any browser on the LAN is a client.

For the page itself:

1. **A framework** (React, Vue, Svelte): needs Node, npm and a build step — a
   second toolchain — to update a few text fields.
2. **Plain HTML, CSS and JavaScript**: edit, reload, done.

For keeping the page up to date:

1. **WebSocket / Server-Sent Events** (server pushes changes): instant, but
   needs connection lifecycle and reconnect handling on both ends, and SMTC
   change events must be wired through the adapter.
2. **Polling** `GET /api/state` every second: trivial on both ends; on a LAN
   the request takes around a millisecond.

## Decision

- The FastAPI app serves the page at `/` and its assets at `/static/`, from a
  `web/` folder shipped inside the Python package.
- Plain HTML, CSS and JavaScript; no framework, no build step, no npm.
- The page polls `GET /api/state` once per second while visible, and refreshes
  immediately after each button press.

## Consequences

- Zero install on clients; phones work too once the server listens on the LAN
  (Phase 5).
- One toolchain (Python + uv) for the whole project.
- A track change made on the studio PC itself can take up to one second to
  appear. Acceptable for this use; revisit with Server-Sent Events if not.
- If the UI grows much bigger (search, queue in Phase 8), plain JavaScript may
  become harder to organize; that is the moment to reconsider a framework.
