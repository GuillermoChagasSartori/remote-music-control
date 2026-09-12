# 0002 — SMTC via `winrt-*` packages instead of media keys or `winsdk`

**Status:** Accepted · 2026-09-12

## Context

We need to control and *read* the playback state of YouTube Music running in
Firefox or Chrome on Windows 10. Options considered:

1. **Simulate media keypresses** (send virtual Play/Next keys). Write-only: it
   cannot tell us what is playing or whether playback is paused, and the key
   goes to whichever app Windows decides owns media keys.
2. **System Media Transport Controls (SMTC)** — the OS media API behind the
   Windows volume/media flyout. Firefox and Chrome register their media
   sessions with it, so it exposes play/pause/next/previous *and* title,
   artist, playback status and thumbnail.
3. For Python access to SMTC, the plan originally named `winsdk`. That project
   has been archived by its maintainers and replaced by the modular `winrt-*`
   packages (pywinrt), which expose the same WinRT APIs.

## Decision

Use SMTC, accessed through the `winrt-*` packages
(`winrt-Windows.Media.Control` and the few namespaces it needs). Per-application
volume is handled separately by `pycaw`, since SMTC has no volume control.

## Consequences

- We can both send commands and read state, which the web UI needs.
- We depend on a maintained package instead of an archived one.
- SMTC only sees sessions in the logged-in user's desktop session — this
  directly shapes how the server is started (see ADR 0003).
- If several apps publish media sessions, we must pick the right one (the
  browser playing YouTube Music) rather than blindly using the "current" one.
