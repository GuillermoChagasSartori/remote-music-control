# 0012 — Pairing page served only to the server PC

**Status:** Accepted · 2026-09-13

## Context

Connecting a phone requires the server's address and the token. `music-server
init` printed pairing links once, in a terminal, which leaves two problems:

- Getting a link onto a phone meant typing it, sending it through a chat app
  (the token then sits on a third-party server) or generating a QR code by hand.
- Android browsers can't resolve `.local` names, so phones use the IP address,
  which the router may change. After a change, every phone must be paired again
  — and the original links are long gone from the terminal.

A DHCP reservation on the router prevents address changes, but it depends on
the router: some make it a two-minute job, some hide or lock the setting.

## Decision

- A page at **`/pair`** shows QR codes of both pairing links (by IP, by name),
  generated on the server as inline SVG with `segno` (pure Python, no
  dependencies, works offline and under the page's Content-Security-Policy).
- The same page explains the DHCP reservation, filled in with this PC's name,
  MAC address (found with `psutil`), current IP and likely router address,
  and says plainly that skipping it is fine: come back and scan again.
- The installer puts a **"Remote Music Control - pair a device"** shortcut on
  the studio PC's desktop.
- Because the page contains the token, it is served **only to the server PC**:
  1. the connection must come from a loopback address (`127.0.0.1`, `::1`), so
     no other device on the network can open it; and
  2. the `Host` header must be a loopback name (`127.0.0.1`, `localhost`,
     `::1`). This blocks **DNS rebinding**, where a malicious site opened in
     the PC's browser points its own domain at `127.0.0.1` to read local pages
     as if they were its own; such requests carry the attacker's domain in
     `Host`.
  Anything else gets `403` with an explanation and no token. The page is sent
  with `Cache-Control: no-store`, and the token never appears as text — only
  inside the QR codes.

Alternatives considered: showing the QR codes in the terminal (needs a console,
and the logon task has none); a token-protected API route returning the QR
codes (a new device doesn't have the token yet — that's the point of pairing).

## Consequences

- Re-pairing after an address change is: walk to the studio PC, double-click
  the shortcut, scan. No router access needed.
- Anyone with access to the studio PC's desktop can open the page and read the
  token. They could equally read the config file, so this adds no new exposure.
- A photo of the screen leaks the token; the page warns about it.
- Two new dependencies: `segno`, and `psutil` on every OS (it was Windows-only).
