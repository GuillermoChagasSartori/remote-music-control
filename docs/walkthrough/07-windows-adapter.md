# 07 — `adapters/windows.py`: the Windows adapter

**File:** [`src/remote_music_control/adapters/windows.py`](../../src/remote_music_control/adapters/windows.py) · ~300 lines
**Depends on:** `winrt-*` (pywinrt), `pycaw` (+ `comtypes`), `psutil`, `media_controller.py` ([page 01](01-media-controller.md))
**Used by:** `server.py` when `RMC_CONTROLLER=windows` ([page 06](06-server.md)); `tests/windows/` (import smoke tests only)
**Runs only:** on Windows, inside the logged-in user's desktop session

## Where this file sits

This is the second driven adapter, the real counterpart of the fake
([page 02](02-fake-adapter.md)). It implements the same ten methods, and the
code above it can't tell the two apart. That's the whole promise of ports and
adapters — and this file is where the promise was tested against reality.

Every other module in the project could be designed at a desk. This one
couldn't. **Almost every non-obvious line here exists because a measurement on
the studio PC contradicted an assumption.** Keep that in mind while reading: the
constants and extra code paths are documented findings, not guesses.

| Finding (measured) | Where it's handled |
|---|---|
| SMTC denies access outside the desktop session | Documented; the server runs as a logon task (ADR 0003) |
| Chrome's SMTC app id is `chrome.exe`; Firefox's is `firefox.exe` | `_find_session` filter, `RMC_PLAYER_APPS` |
| SMTC reports `""` when there's no album | `now_playing` |
| Chrome deletes its media session for ~0.8–1 s on every skip | Grace period (Blocks 7–9, 15) |
| Chrome publishes new state 0.15–0.4 s (play/pause) to ~1 s (skip) after a command | Command settling (Block 13) |
| "Previous" late in a song restarts the same song | Settling timeout |
| Chrome releases its **audio** session ~3 min after pausing; Windows restores the volume on resume | Remembered volume (Block 11) |
| SMTC and pycaw work in either COM apartment | Comment on the COM flag (Block 3) |

---

## Background: four Windows technologies

The file combines several layers of Windows. A short map first.

### SMTC — System Media Transport Controls

When you press a media key or open the little media pop-up next to the volume
slider, Windows shows what's playing and lets you pause or skip. The API behind
that is **SMTC**. Applications that play media — including browsers — publish a
**media session** to it: title, artist, playback status, and which commands
they accept.

Browsers do this through the web's **Media Session API**: YouTube Music tells
Chrome what's playing, Chrome forwards it to SMTC. So SMTC can both **read** the
state and **send** commands, which is why it was chosen over simulating
key presses (ADR 0002).

The class names are long:
`GlobalSystemMediaTransportControlsSessionManager` gives access to all sessions;
each `GlobalSystemMediaTransportControlsSession` is one application's session.

### WinRT and pywinrt

SMTC is part of the **Windows Runtime (WinRT)**, the modern Windows API
introduced with Windows 8. WinRT is designed to be used from many languages
through **language projections**: generated wrappers that make the API look
natural in C#, C++, JavaScript — or Python. **pywinrt** is the Python
projection, distributed as one package per namespace (`winrt-Windows.Media.Control`
and so on, ADR 0002).

WinRT operations that might take time are **asynchronous**
(`IAsyncOperation`). pywinrt makes them *awaitable* in Python, which is why the
port is `async` (ADR 0005): `await manager.request_async()`. Method names are
converted from `RequestAsync` to Python style, `request_async`.

### COM and apartments

Underneath both WinRT and the audio API is **COM** (Component Object Model),
Windows' decades-old system for objects shared across components and
languages. One COM rule appears in this file: before a thread uses COM, it
joins an **apartment**, which governs which threads may use which objects:

- **STA (single-threaded apartment):** objects are used only by the thread that
  created them; calls from other threads must be passed through a message queue.
- **MTA (multi-threaded apartment):** any thread in the apartment may use them.

### Core Audio and pycaw

Windows keeps a separate volume for each application — what you see in the
**Volume Mixer**. The **Core Audio API** exposes it: each application that
outputs sound owns one or more **audio sessions**, and each session has a
`SimpleAudioVolume` interface with the volume and mute. SMTC has no volume
control, so volume comes from here. **pycaw** (Python Core Audio Windows) is a
small library over **comtypes**, which lets Python call COM interfaces.

Note there are **two unrelated kinds of session** in this file: SMTC *media*
sessions (the track, the commands) and Core Audio *audio* sessions (the volume).
Chrome manages them independently — which matters a lot in Blocks 11 and 13.

### Desktop session vs session 0

A Windows **logon session** is an isolated environment for one user login.
Services and SSH connections run in **session 0**, which has no desktop. SMTC
and the per-application audio sessions exist only inside the interactive
desktop session. Measured in Phase 4: from SSH, `request_async()` raised
*"Acesso negado"* (access denied) and pycaw saw no browser at all. That's why
the server runs as a logon task (ADR 0003, page 06).

---

## Block 1 — the module docstring

It names both APIs and what each is used for, and — most importantly for a
future reader — the session-0 limitation. Someone who tries to run the server
over SSH and sees "access denied" should find the explanation at the top of the
file they're debugging.

---

## Block 2 — the platform guard

```python
import sys

if sys.platform != "win32":
    raise ImportError("the Windows media adapter can only be used on Windows")
```

**The very first thing the module does** is refuse to load on other systems,
with a message that says why. Without it, importing on Linux would fail a few
lines later with `ModuleNotFoundError: No module named 'winrt'` — true, but it
suggests a missing installation rather than the wrong machine.

This is **fail fast** again, applied to a whole module. `server.py` turns this
`ImportError` into a configuration error (page 06, Block 2), and the test suite
on Linux checks exactly that message.

---

## Block 3 — the COM flag

```python
sys.coinit_flags = 0  # 0 = COINIT_MULTITHREADED
```

**What it does:** `comtypes` (used by pycaw) initializes COM for the main thread
**when it's imported**, and reads `sys.coinit_flags` to decide the apartment.
Without the flag it chooses a single-threaded apartment; `0` means
`COINIT_MULTITHREADED`, the MTA. That's why it must run **before** `pycaw` is
imported.

**Measured on the studio PC while writing this page**, by asking Windows which
apartment the thread was in (`CoGetApartmentType`):

| Situation | Apartment |
|---|---|
| After importing `winrt` only | Not initialized yet — pywinrt sets up COM on first use, not on import |
| After importing `pycaw` without the flag | STA ("main STA") |
| After importing the adapter (flag set first) | MTA |
| SMTC + pycaw calls, **without** the flag | Both work |
| SMTC + pycaw calls, **with** the flag | Both work |

So the flag **isn't fixing a failure** — an earlier version of the code comment
implied a conflict that the measurement didn't show. It's a **precaution**: in
an STA, COM objects may only be used by the thread that created them. Today the
server calls everything from its single event-loop thread, so either apartment
works. ADR 0005 names moving pycaw calls to a worker thread as the remedy if
they're ever too slow; in the MTA that change would just work, in an STA it
could fail in confusing ways. The comment in the code now says exactly this.

**The broader lesson:** a comment that explains *why* is valuable only if the
why is true. When a reason can be checked cheaply, check it.

**`# noqa: E402`** on the imports below: `E402` is the linter rule "module-level
import not at top of file". These imports are deliberately after a statement,
and `noqa` ("no quality assurance") tells linters that's intended.

---

## Block 4 — imports and aliases

```python
from winrt.windows.media.control import (  # noqa: E402
    GlobalSystemMediaTransportControlsSession as SmtcSession,
)
...
from ..media_controller import (MediaController, MediaControllerError, NoMediaSessionError,
                                NowPlaying, PlaybackStatus, validate_volume)
```

**`as SmtcSession`** gives the 50-character WinRT names short local aliases,
so the code below stays readable. The alias names say what the thing *is* in
this project's vocabulary.

**`psutil`** is imported only for its exception type (Block 10). **`asyncio`**
provides `sleep` for polling; **`time`** provides `monotonic` for deadlines.

---

## Block 5 — translating SMTC's status

```python
STATUS_FROM_SMTC = {
    SmtcStatus.PLAYING: PlaybackStatus.PLAYING,
    SmtcStatus.PAUSED: PlaybackStatus.PAUSED,
}
```

SMTC reports six states: **closed** (0), **opened** (1), **changing** (2),
**stopped** (3), **playing** (4), **paused** (5). The port has three
(page 01, Block 3). The dictionary maps the two that matter; everything else
becomes *stopped* via `.get(..., PlaybackStatus.STOPPED)` in `now_playing`.

This small translation is an example of what Domain-Driven Design calls an
**anti-corruption layer**: code at the edge that converts a foreign system's
model into your own, so the foreign concepts ("opened", "changing") don't leak
into the rest of the application. Here the whole adapter plays that role; this
dictionary is its simplest piece.

---

## Block 6 — timing constants

```python
SESSION_GAP_GRACE_SECONDS = 2.0
SESSION_WAIT_POLL_SECONDS = 0.1
COMMAND_SETTLE_TIMEOUT_SECONDS = 2.0
```

Each comes with the **measurement it's based on** in its comment:

- **Grace 2.0 s:** Chrome's skip gap measured ~0.8–1 s; 2 s is about double,
  absorbing slower moments without hiding a real browser close for long.
- **Poll 0.1 s:** how often to look again while waiting. Each look is a local
  call taking milliseconds; 100 ms keeps waits responsive without busy-looping.
- **Settle 2.0 s:** the slowest observed state publication was ~1 s (skips).

Named constants rather than numbers in the code (page 01's magic numbers): if
Chrome's behaviour changes after an update, these are the three lines to
revisit, and ADR 0008 records how they were measured.

---

## Block 7 — the constructor: what the adapter remembers

```python
    def __init__(self, player_apps: tuple[str, ...]) -> None:
        if not player_apps:
            raise ValueError("WindowsMediaController needs at least one player app name")
        self._player_apps = tuple(name.lower() for name in player_apps)
        self._manager: SmtcSessionManager | None = None
        self._last_seen_at = 0.0
        self._last_now_playing: NowPlaying | None = None
        self._last_volume: int | None = None
        self._last_muted: bool | None = None
```

**`player_apps`** comes from `RMC_PLAYER_APPS` (page 04). Lowercased once here,
so every comparison below is case-insensitive.

**What is kept, and what deliberately isn't:**

- **The session manager is kept.** Requesting it is an async call; it
  represents "SMTC on this PC" and stays valid.
- **Sessions are *not* kept.** A session object belongs to one run of the
  browser. If the adapter stored it, closing and reopening Chrome would leave
  it holding a dead object — a **stale reference**. Instead, every call looks
  the session up again (Block 8). That single choice is why the server
  recovers when the browser restarts, verified in Phase 4 without restarting
  the server.

**The remaining four attributes are memory for workarounds:** when a session
was last seen and what it showed (grace period), and the last volume and mute
(paused audio). The fake adapter is pure state; this adapter's own state exists
only to smooth over the real player's gaps.

**`time.monotonic()`** is a clock that only moves forward and isn't affected if
the system time is changed (by the user, or by network time sync). Wall-clock
time (`time.time()`) can jump backwards, which would break "has 2 seconds
passed?". For measuring durations and deadlines, always use a monotonic clock.

---

## Block 8 — finding the player's media session

```python
    async def _find_session(self) -> SmtcSession | None:
        if self._manager is None:
            self._manager = await SmtcSessionManager.request_async()

        candidates = [
            session
            for session in self._manager.get_sessions()
            if session.source_app_user_model_id.lower() in self._player_apps
        ]
        if not candidates:
            return None
        self._last_seen_at = time.monotonic()
        for session in candidates:
            if session.get_playback_info().playback_status == SmtcStatus.PLAYING:
                return session
        return candidates[0]
```

**Lazy initialization:** the manager is requested on first use rather than in
the constructor, because constructors can't `await`. After that it's reused.

**`get_sessions()`** returns every media session on the PC — a video player,
Spotify, a browser. Each has a **`source_app_user_model_id`** (AUMID), Windows'
identifier for the application. For Chrome and Firefox it was measured to be
simply `chrome.exe` / `firefox.exe` — the same names the audio side uses, so one
setting (`RMC_PLAYER_APPS`) serves both.

**Filtering by app** means media keys on your studio PC controlling, say, a
video player won't hijack the remote. **Preferring the playing session** handles
two matching apps with sessions at once (Chrome and Firefox both open): the one
actually making sound wins.

**`self._last_seen_at = time.monotonic()`** records "a player existed right
now" for the grace period — set every time any matching session is found.

---

## Block 9 — `_require_session`: waiting through the gap

```python
    async def _require_session(self) -> SmtcSession:
        session = await self._find_session()
        while session is None and self._in_grace_period():
            await asyncio.sleep(SESSION_WAIT_POLL_SECONDS)
            session = await self._find_session()
        if session is None:
            raise NoMediaSessionError(f"no media session from {', '.join(self._player_apps)} — is the player open?")
        return session
```

Used by commands. If the session is missing but was seen less than 2 s ago, the
browser is almost certainly in the middle of a track change, so the command
**waits for the session to come back** instead of failing. Pressing "next" twice
quickly works because of this.

**`await asyncio.sleep(...)`**, not `time.sleep(...)`: `time.sleep` would block
the whole event loop, freezing every other request (including the web page's
polling) while this one waits. `asyncio.sleep` pauses only this coroutine.

### Polling vs events

This is **polling**: look, wait a bit, look again. SMTC also offers **events**
(`SessionsChanged`, `PlaybackInfoChanged`, `MediaPropertiesChanged`) that call
you back when something changes. Events are more efficient and react instantly.
They were not used because they bring callbacks arriving from WinRT's threads,
subscriptions to manage per session (which Chrome recreates on every skip), and
harder tests — while polling every 100 ms, only during a short wait, costs
almost nothing and was measured to work. Plain over clever.

---

## Block 10 — finding the audio sessions

```python
    def _audio_controls(self) -> list:
        controls = []
        for audio_session in AudioUtilities.GetAllSessions():
            try:
                process = audio_session.Process
                name = process.name().lower() if process is not None else ""
            except psutil.Error:
                continue
            if name in self._player_apps:
                controls.append(audio_session.SimpleAudioVolume)
        return controls
```

**`AudioUtilities.GetAllSessions()`** lists the audio sessions on the default
output device. Each knows the process that owns it; pycaw uses `psutil` to get
the process object. System sounds have no process (`None`).

**Why a list, not the first match:** one application can own several audio
sessions (Chrome sometimes does). Setting only one would leave others at the old
volume. All matching sessions are changed together, so the user sees one volume.

**`except psutil.Error: continue`** handles a **race condition**: between
listing the sessions and asking for a process name, that process might exit
(a tab playing a sound closes). Skipping it is the right outcome — it has no
volume to control anymore.

**It returns an empty list instead of raising** since today's fix: the callers
decide what "no audio session" means, because it means different things for
reading and for writing (Block 11).

**Synchronous:** pycaw calls are plain COM calls that take about a millisecond,
so this is a normal `def` called from async methods — the choice recorded in
ADR 0005. Measured: listing all sessions takes ~30 ms.

---

## Block 11 — volume while paused

```python
    async def _remembered_while_paused(self, value: int | bool | None) -> int | bool:
        if value is not None and await self._find_session() is not None:
            return value
        raise NoMediaSessionError(f"no audio session from {', '.join(self._player_apps)} — is the player open?")

    def _require_audio_controls(self) -> list:
        controls = self._audio_controls()
        if not controls:
            raise NoMediaSessionError(
                f"no audio session from {', '.join(self._player_apps)}: browsers release it "
                "a few minutes after pausing — press play, then change the volume"
            )
        return controls
```

### The finding

While writing page 06, `music now` suddenly failed with "no audio session".
Chrome was open, the track paused. Measurements on the studio PC showed:

1. **About 3 minutes (193–194 s) after pausing, Chrome releases its audio
   session** — it stops outputting sound entirely — while its *media* session,
   with the paused track, stays.
2. **When playback resumes, Windows restores the application's previous volume
   and mute state** (set to 23 before pausing; read 23 after resuming).

Before the fix, reading the volume failed after 3 minutes of pause, so
`GET /api/state` answered 409, the web page couldn't show the paused track, and
`music now` failed. None of the earlier tests paused for that long.

### The handling

- **Reading** (`get_volume`, `is_muted`): if there's no audio session **but** a
  media session exists, the player is paused, not closed — so return the last
  value seen. Finding 2 guarantees it's still the right answer. If no value was
  ever seen (the server started while already paused), there's nothing honest
  to return, so it's still 409.
- **Writing** (`set_volume`, `set_muted`): impossible without an audio session.
  Answer 409 with a message that says what to do.

This is a **cache used as a fallback**. Caches are dangerous when they can go
stale; this one is safe precisely because of finding 2 — which is why the
measurement came before the code. The rule "check the media session first" keeps
it from reporting a volume for a browser that has actually been closed.

**A good error message names the remedy.** Compare the generic "is the player
open?" (used for reading, where "closed" is the likely cause) with "press play,
then change the volume" (used for writing, where "paused too long" is).

---

## Block 12 — `_send`: running one SMTC command

```python
    async def _send(self, action: str, command: Callable[[SmtcSession], Awaitable[bool]]) -> None:
        session = await self._require_session()
        try:
            accepted = await command(session)
        except OSError as error:
            raise MediaControllerError(f"'{action}' failed: {error}") from error
        if not accepted:
            raise MediaControllerError(f"the player refused '{action}'")
```

### A function that takes a function

`command` is a **callable** — something that, given a session, returns an
awaitable `bool`. Each transport method passes a small **lambda** (an anonymous
one-line function):

```python
await self._send("play", lambda session: session.try_play_async())
```

`_send` finds the session, then calls the lambda with it. A function that takes
another function as an argument is a **higher-order function**. It lets one
place hold the shared procedure — find session, run, translate errors, check the
answer — while each caller supplies only the part that differs. The type hint
`Callable[[SmtcSession], Awaitable[bool]]` reads: "takes a session, returns
something awaitable that produces a bool".

### Translating failures into the port's language

SMTC commands fail in two different ways:

- **WinRT errors raise `OSError`** — pywinrt converts the Windows error code
  (`HRESULT`) into a Python `OSError` subclass. The session-0 "access denied"
  seen in Phase 4 arrived as `PermissionError`, which is one. Translated to
  `MediaControllerError` → **502**, with `from error` keeping the original
  attached for debugging.
- **The player refuses:** `try_play_async()` and friends return `False` when the
  application doesn't accept the command (for instance a disabled control).
  Treating `False` as success would make the API answer 204 for a command that
  did nothing. Translated to **502** too.

This is the **exception translation** the port asked for (page 01, Block 5):
nothing outside this file ever sees an `OSError` from WinRT.

---

## Block 13 — transport: waiting until the change is visible

```python
    async def play(self) -> None:
        await self._send("play", lambda session: session.try_play_async())
        await self._wait_until(lambda now: now.status == PlaybackStatus.PLAYING)

    async def toggle_play_pause(self) -> None:
        before = await self.now_playing()
        was_playing = before is not None and before.status == PlaybackStatus.PLAYING
        await self._send("play/pause", lambda session: session.try_toggle_play_pause_async())
        expected = PlaybackStatus.PAUSED if was_playing else PlaybackStatus.PLAYING
        await self._wait_until(lambda now: now.status == expected)

    async def next_track(self) -> None:
        before = await self.now_playing()
        await self._send("next", lambda session: session.try_skip_next_async())
        await self._wait_until(lambda now: _is_different_track(now, before))

    async def _wait_until(self, condition: Callable[[NowPlaying], bool]) -> None:
        deadline = time.monotonic() + COMMAND_SETTLE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            now = await self.now_playing()
            if now is None or condition(now):
                return
            await asyncio.sleep(SESSION_WAIT_POLL_SECONDS)
```

### The problem: accepted is not the same as visible

`try_pause_async()` returns `True` as soon as Chrome *accepts* the command. The
new status appears in SMTC 0.15–0.4 s later, a new track about 1 s later. A
client that pauses and immediately reads the state sees "playing". That's what
happened in Phase 4: `music pause` printed ▶.

In distributed-systems terms, SMTC is **eventually consistent**: after a change,
reads return the new value *eventually*, not immediately. What clients want is
**read-your-writes consistency**: after I do something, my next read reflects
it. The adapter provides that by not returning until the change is readable.

### How

Each command passes `_wait_until` a **predicate** — a function returning
true/false — describing "the change is visible":

| Command | Condition |
|---|---|
| `play` | status is *playing* |
| `pause` | status is *paused* |
| `toggle` | status is the **opposite** of what it was before (computed first) |
| `next`, `previous` | title or artist differs from before |

`toggle` and the skips read the state **before** sending the command; lambdas
then **capture** `before` and `expected` from the surrounding function (a
closure, as on page 03).

**The timeout is not an error.** The command already succeeded. If the change
doesn't become visible in 2 s — "previous" late in a song restarts the *same*
track, so there's no difference to see — the method just returns. Raising would
report a failure for a command that worked.

**`now is None` also ends the wait**: if the browser was closed meanwhile,
there's nothing more to wait for.

**The cost**, recorded in ADR 0008: commands answer later — ~0.4 s for
play/pause, ~1–2 s for skips. The sound changes just as fast; only the reply
waits. The CLI's read timeout was raised to 10 s because of this (page 05).

---

## Block 14 — volume methods

```python
    async def get_volume(self) -> int:
        controls = self._audio_controls()
        if not controls:
            return await self._remembered_while_paused(self._last_volume)
        self._last_volume = round(controls[0].GetMasterVolume() * 100)
        return self._last_volume

    async def set_volume(self, level: int) -> None:
        validate_volume(level)
        for control in self._require_audio_controls():
            control.SetMasterVolume(level / 100, None)
        self._last_volume = level
```

(`is_muted` and `set_muted` follow the same pattern.)

- **Units:** Windows stores volume as a float from 0.0 to 1.0 (a **scalar**);
  the port uses integers 0–100. `round(x * 100)` and `level / 100` convert.
  `round` rather than `int` avoids 0.29999 becoming 29.
- **Reading from the first session** is enough: they were all set together.
- **`SetMasterVolume(level, None)`**: the second argument is an **event context
  GUID**, an optional identifier that lets the application that changed the
  volume recognize its own change when notified. `None` means "no context".
- **The cache is updated on every successful read and write**, so it always
  holds the latest value for Block 11.
- **`validate_volume` first**, as in the fake — the shared rule from the port.

---

## Block 15 — `now_playing`

```python
    async def now_playing(self) -> NowPlaying | None:
        session = await self._find_session()
        if session is not None:
            try:
                properties = await session.try_get_media_properties_async()
                smtc_status = session.get_playback_info().playback_status
            except OSError:
                session = None
            else:
                self._last_now_playing = NowPlaying(
                    title=properties.title,
                    artist=properties.artist,
                    album=properties.album_title or None,
                    status=STATUS_FROM_SMTC.get(smtc_status, PlaybackStatus.STOPPED),
                )
                return self._last_now_playing

        if self._in_grace_period():
            return self._last_now_playing
        self._last_now_playing = None
        return None
```

**`try / except / else`:** the `else` block runs only if the `try` raised
nothing. Keeping the successful path in `else` means the `except` covers only the
two calls that can fail, not the object construction after them.

**The race handled by `except OSError`:** the session can vanish between
finding it and reading it (Chrome's skip gap starts at exactly the wrong
moment). That's treated like "no session found" and falls through to the grace
period.

**`properties.album_title or None`** — SMTC gives `""` for "no album" (measured
on the first probe in Phase 4); the port uses `None`.

**The grace period, from the reading side:** with no session but one seen less
than 2 s ago, return the **last snapshot** — so a skip never makes the web page
flash "Nothing playing". The snapshot is immutable (`frozen=True`, page 01), so
returning the same object again is safe. After the grace period, the adapter
forgets it and reports `None`: the browser really is closed.

This is a form of **debouncing**: short-lived changes are ignored unless they
last. The term comes from electronics — a physical switch "bounces" on and off
for a few milliseconds when pressed, and circuits wait for it to settle.

---

## Block 16 — `_is_different_track`

```python
def _is_different_track(now: NowPlaying, before: NowPlaying | None) -> bool:
    return before is None or (now.title, now.artist) != (before.title, before.artist)
```

A **module-level helper** (not a method: it doesn't need `self`), named with a
leading underscore because it's internal to this module.

**Title *and* artist:** two different songs can share a title. Comparing
**tuples** compares element by element, so one expression covers both. It still
can't detect the same song queued twice in a row — then the settle wait simply
times out after 2 s, which is harmless.

**`before is None`** — if nothing was playing before, any track counts as a
change.

---

## Timelines: what the code absorbs

**Pressing "next" in Chrome** (measured in Phase 4):

```
t = 0.00 s  POST /api/next arrives
            _send → try_skip_next_async() → True (accepted)
t ≈ 0.15 s  Chrome deletes its media session          ← _find_session → None
            _wait_until → now_playing(): grace period → last snapshot (old title)
t ≈ 1.00 s  Chrome creates a new session              ← new title visible
            condition "different track" true → return
t ≈ 1.05 s  204 No Content — client reads the NEW track
```

**Pausing and leaving it** (measured today):

```
t = 0 s     pause → media session: paused, audio session: present
t ≈ 194 s   Chrome releases the audio session         ← _audio_controls → []
            GET /api/state → now_playing: paused track (media session still there)
                           → get_volume: remembered value (Block 11)
            PUT /api/volume → 409 "press play, then change the volume"
play        audio session returns; Windows restores the volume
```

---

## How it's tested — and why mostly by hand

**CI can't test behaviour** here: GitHub's Windows runners have no logged-in
desktop session and no browser playing YouTube Music. What the `windows-latest`
job does check (`tests/windows/`, page 09):

- the Windows-only packages install and the module imports (a **smoke test**);
- the adapter can be constructed and satisfies the port;
- `_is_different_track`.

**Behaviour is verified two ways:**

1. **The manual checklist**, [docs/testing-on-windows.md](../testing-on-windows.md)
   — 20 steps with expected results and a dated results log.
2. **Measurement probes** during development: small throwaway scripts run on
   the studio PC through a temporary scheduled task (so they execute in the
   desktop session), sampling SMTC or Core Audio every 100 ms while a command
   happens. Every finding in the table at the top came from one.

This is the price of the architecture's benefit: one module that can't be
automatically tested, kept as small and as well-documented as possible, while
everything above it is tested against the fake.

## Known limitations

- **It controls Chrome's media session, not specifically YouTube Music.** If
  another tab in Chrome plays a video, Chrome decides which one its session
  represents.
- **The server started while already paused** can't report the volume until
  playback resumes (Block 11).
- **The session manager is requested once.** If Windows' media service were
  restarted while the server runs, the manager might need requesting again.
  Not observed; the watchdog would not notice, since the process stays alive.
- **Timing constants are measured on one PC, one Chrome version.** A slower
  machine or a changed browser could need different values.

## Glossary

| Term | Meaning here |
|---|---|
| SMTC | System Media Transport Controls: Windows' media sessions and commands |
| Media Session API | The web API through which a page tells the browser what's playing |
| WinRT / language projection / pywinrt | Modern Windows API / generated per-language wrappers / the Python one |
| COM | Component Object Model, Windows' component system under WinRT and Core Audio |
| Apartment (STA / MTA) | COM's rule for which threads may use an object |
| Core Audio / audio session / pycaw | Per-application audio API / one app's audio stream / Python library for it |
| Logon session / session 0 | Isolated login environment / the one for services, with no desktop |
| AUMID | Application User Model ID, Windows' app identifier (`chrome.exe`) |
| Anti-corruption layer | Code translating a foreign model into your own |
| Stale reference | Holding an object that no longer represents anything live |
| Monotonic clock | A clock that never goes backwards; for durations and deadlines |
| Lazy initialization | Creating something on first use |
| Polling vs events | Checking repeatedly vs being called back on change |
| Higher-order function / lambda / callable | Function taking a function / anonymous function / anything callable |
| Exception translation | Converting low-level errors into the interface's own errors |
| HRESULT | Windows' numeric error code, surfaced in Python as `OSError` |
| Eventual consistency | Reads return the new value after some delay |
| Read-your-writes consistency | After a change, your next read reflects it |
| Predicate | A function returning true or false |
| Cache as fallback | Last known value used when the live value is unavailable |
| Debouncing / grace period | Ignoring changes that don't last |
| Smoke test | A basic check that something starts or loads |

## Check your understanding

1. Why does the adapter keep the session *manager* but look up the *session* on
   every call? What would break if it stored the session?
2. What exactly did the COM measurement show, and why is the flag still there?
3. Chrome deletes its media session during a skip. Follow a `POST /api/next`
   through `_send`, `_wait_until` and `now_playing`: which code keeps the web
   page from showing "Nothing playing"?
4. Why must `toggle_play_pause` read the status *before* sending the command?
5. `_wait_until` times out after 2 s without raising. Give a real situation where
   raising would be wrong.
6. After 3 minutes of pause, `get_volume` returns a remembered value, but
   `set_volume` answers 409. Why can one work and not the other? Which
   measurement makes the remembered value trustworthy?
7. Why `await asyncio.sleep(0.1)` and never `time.sleep(0.1)` in this file?
8. SMTC offers change events. Give two reasons the adapter polls instead.
9. Why does `_send` treat a `False` return value as an error?
