# 0008 — Absorbing Chrome's SMTC session gap in the Windows adapter

**Status:** Accepted · 2026-09-13

## Context

Testing the Windows adapter against YouTube Music in Chrome showed that
**Chrome deletes its SMTC media session on every track change and creates a new
one about 0.8–1 s later**. Sampling SMTC every 100 ms around a skip:

```
    13 ms  sessions=[('chrome.exe', PLAYING, 'Last Exit - A Bit Of Peace…')]
  2127 ms  sessions=[]                                  ← skip sent at ~2000 ms
  2907 ms  sessions=[('chrome.exe', PLAYING, 'Macroblank - 深淵に…')]
```

Reported literally, every skip made the player look closed for a second: the
web page flashed "Nothing playing" and disabled its buttons, `GET /api/state`
could fail with 409 when the session vanished between two reads, a second
"next" pressed quickly was rejected, and `music next` printed the *old* track.

The same testing confirmed ADR 0003: a process started over SSH runs in
session 0 and SMTC answers "access denied"; started through a Task Scheduler
task in the desktop session, it works.

## Decision

Handle it inside `WindowsMediaController`, keeping the port and everything
above it unaware of the quirk:

1. **Grace period.** A session missing for less than 2 s is treated as a track
   change, not a closed player. `now_playing()` keeps returning the last known
   track; commands wait (polling every 100 ms) for the session to return
   before raising `NoMediaSessionError`.
2. **Volume uses only the audio session.** Chrome's Core Audio session survives
   the gap, so volume calls no longer depend on the SMTC session.
3. **Commands settle before returning.** Chrome applies a command at once but
   publishes the result later: ~0.15–0.4 s for play/pause, ~1 s for a skip.
   Every transport command waits (up to 2 s) until its effect is readable —
   `play` until playing, `pause` until paused, `toggle` until the opposite
   status, `next`/`previous` until a different track — so a client reading
   state right after the command sees the new state. (Found when `music pause`
   printed ▶ because it read the state before Chrome had published it.)

## Consequences

- No flicker in the UI and no spurious 409s during skips (verified live).
- Closing the browser is reported up to 2 s late. Acceptable.
- Commands answer later than before: ~0.2–0.4 s for play/pause, ~1 s for a
  skip. The command itself is sent immediately, so the sound changes just as
  fast; only the reply waits.
- "Previous" late in a song restarts the same track, so there is no change to
  detect and the reply waits the full 2 s.
- The 2 s values are based on measurements of one Chrome version; they are
  named constants at the top of the adapter in case Chrome's behaviour changes.
- **Firefox** (tested the same day) registers as `firefox.exe` and keeps its
  session across skips — no gap — but briefly reports "paused" while changing
  tracks. The same code handles it: `next` answers in ~0.4 s. `previous` took
  ~2 s to show the new track, so its reply usually hits the timeout.

## Addendum — 2026-09-13: audio session released while paused

A second, slower gap was found later. **About 3 minutes (measured 193–194 s)
after pausing, Chrome releases its audio session**, while its media session —
the paused track — remains. Volume can't be read or changed without an audio
session, so `GET /api/state` answered 409 and the web page and `music now`
stopped showing the paused track.

Measured as well: **when playback resumes, Windows restores the application's
previous volume and mute state.**

Decision, again inside the Windows adapter:

- `get_volume()` / `is_muted()` remember the last values read or written. With
  no audio session but a media session present (i.e. paused), they return
  those remembered values.
- `set_volume()` / `set_muted()` can't work without an audio session; they
  raise `NoMediaSessionError` (409) with an actionable message: *press play,
  then change the volume*.
- If the server started while the player was already paused, no value is known
  yet, and volume reads answer 409 until playback resumes. Accepted as rare.

Verified live: paused for over 3 minutes, state still showed the track with
volume 30; setting the volume gave the new message; after play, volume was 30.

