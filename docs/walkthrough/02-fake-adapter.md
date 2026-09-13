# 02 — `adapters/fake.py`: the fake adapter

**File:** [`src/remote_music_control/adapters/fake.py`](../../src/remote_music_control/adapters/fake.py) · 104 lines
**Depends on:** `media_controller.py` only ([page 01](01-media-controller.md))
**Used by:** `server.py` when `RMC_CONTROLLER=fake` (the default), and almost every test

## Where this file sits

```
            api.py, cli.py, tests
                     │  call
                     ▼
            media_controller.py   (the port: MediaController)
               ▲             ▲
    implements │             │ implements
  adapters/fake.py      adapters/windows.py
  (a list in memory)    (SMTC + Core Audio)
```

This is the first **adapter** from page 01: a concrete class that fills in
every abstract method of `MediaController`. Where the Windows adapter talks to
Windows, this one talks to nothing — it keeps a list of invented songs and a
few variables in memory.

It is the reason the project could be built and tested on Ubuntu for three
phases before the studio PC was involved, and why CI can run the test suite on a
Linux machine with no browser and no speakers.

---

## Block 1 — the docstring: what kind of test double this is

```python
"""FakeMediaController: an in-memory player that runs on any operating system.

In testing vocabulary this is a *fake* — a working, simplified implementation
(as opposed to a *mock*, which only records calls, or a *stub*, which only
returns canned answers). ...
"""
```

### The technique: test doubles

A **test double** is any object that stands in for a real dependency during
development or testing — named after a stunt double in films. Gerard Meszaros'
book *xUnit Test Patterns* gave the kinds precise names, and these are the
terms you'll meet in job interviews and code reviews:

| Kind | What it does | Example in this project's terms |
|---|---|---|
| **Dummy** | Passed around but never used | A controller given to code that never touches it |
| **Stub** | Returns fixed answers, no logic | `now_playing()` always returns the same track, `next_track()` does nothing |
| **Spy** | A stub that also records how it was called | Remembers "next_track was called 2 times" so a test can check |
| **Mock** | Pre-programmed with *expected* calls; fails if they don't happen | "Expect exactly one `pause()` call, then nothing" |
| **Fake** | A working, simplified implementation | **This file:** skipping really changes the track, volume is really remembered |

People often say "mock" for all of these. The distinction matters here: a stub
or mock couldn't serve the web page during development, because after you
pressed "next" the page would still show the same song. A fake **behaves**, so
the whole application — server, web page, CLI — can run on it as if it were the
real thing.

**The alternative:** Python's `unittest.mock.MagicMock` can imitate any object
in one line. It would have been quicker to write, but every test would have to
script the player's behaviour again ("when next_track is called, make
now_playing return the second song…"), and nothing could be run by hand.

---

## Block 2 — the relative import

```python
from ..media_controller import (
    MediaController,
    NoMediaSessionError,
    NowPlaying,
    PlaybackStatus,
    validate_volume,
)
```

**What:** imports five names from the port module.

**`..`** is a **relative import**: one dot means "this package"
(`adapters`), two dots mean "the package above" (`remote_music_control`). So
`..media_controller` is `remote_music_control/media_controller.py`.

**Why relative:** the adapter always lives inside this package, next to its
port. If the package were ever renamed, relative imports keep working. The
alternative, `from remote_music_control.media_controller import ...` (an
**absolute import**), is equally valid; PEP 8 accepts both, and the project
uses relative imports inside the package consistently.

**What's *not* imported is the point:** no `fastapi`, no `winrt`, no `asyncio`.
The fake depends only on the port. Adapters depend on the port; the port never
depends on adapters — the arrows from page 01.

**Parentheses** let one `import` statement span several lines, one name per
line, which keeps later changes to a single-line diff.

---

## Block 3 — the demo tracks

```python
# Invented tracks, so screenshots in the public README show no real artists.
DEMO_TRACKS: tuple[tuple[str, str, str], ...] = (
    ("Signal Path", "The Test Patterns", "Loopback"),
    ...
)
```

**What:** five invented songs, each a `(title, artist, album)` triple.

**The type hint** reads from the inside out: `tuple[str, str, str]` is one
song (exactly three strings); `tuple[..., ...]` with a literal `...` means "a
tuple of any length whose items all have that type".

**Why a tuple and not a list:** tuples are **immutable** (page 01, Block 4).
This matters for a module-level constant that's also used as a default
argument — see Block 5.

**Why invented names:** the README screenshot comes from this data, and the
repository is public. Real artists and titles in a portfolio screenshot invite
questions nobody needs. The names are also small jokes about the architecture
("Port and Adapter", "Walking Skeleton"), which makes test output recognisable
at a glance.

---

## Block 4 — the class line and the concurrency comment

```python
class FakeMediaController(MediaController):
    # No locking is needed: the server runs these coroutines on a single event
    # loop, and no method awaits in the middle of changing state, so two
    # requests can never interleave inside one method.
```

**`(MediaController)`** makes this class a **subclass** of the port. Python
checks at creation time that every `@abstractmethod` is implemented (page 01,
7a); forget one and `FakeMediaController()` raises `TypeError`.

**The comment answers a question a careful reader would ask:** "the server
handles requests concurrently — can two requests corrupt the state?"

Recall from page 01 that async code only switches between tasks **at `await`
points**. Look at any method below: none contains an `await`. So once
`next_track()` starts, it runs to the end before anything else can happen. Its
change of state is effectively **atomic** (indivisible), and no lock is needed.

Compare the Windows adapter, whose methods *do* await (WinRT calls). That's why
page 01's warning about `change_volume` — a read, an `await`, then a write —
applies to the real player but not in practice to the fake: with the fake,
awaiting a coroutine that never awaits internally doesn't give other tasks a
chance to run.

**Why the comment matters:** if someone later adds an `await` inside one of
these methods (say, `await asyncio.sleep(0.1)` to imitate a slow player), the
guarantee disappears. The comment records the assumption so it isn't broken
silently.

---

## Block 5 — the constructor

```python
    def __init__(
        self,
        tracks: tuple[tuple[str, str, str], ...] = DEMO_TRACKS,
        session_open: bool = True,
    ) -> None:
        if not tracks:
            raise ValueError("FakeMediaController needs at least one track")
        self._tracks = tracks
        self._index = 0
        self._status = PlaybackStatus.PAUSED
        self._volume = 50
        self._muted = False
        # Public on purpose: set it to False to simulate the browser being
        # closed, so the "no media session" path can be exercised on Linux.
        self.session_open = session_open
```

### 5a. Default arguments, and why the default is a tuple

`tracks` defaults to `DEMO_TRACKS`, so the server just writes
`FakeMediaController()`, while tests pass their own short list
(`test_fake_controller.py` uses three tracks named First, Second, Third).

Python evaluates a default value **once, when the function is defined**, and
reuses the same object on every call. With a *mutable* default like a list,
one instance modifying it would change it for every future instance — a
classic Python bug known as the **mutable default argument** pitfall. A tuple
can't be modified, so sharing it is safe. The fake never modifies `tracks`
anyway, but the choice makes the mistake impossible rather than merely absent.

### 5b. Validating in the constructor: fail fast

`if not tracks: raise ValueError(...)` rejects an empty track list
immediately. Without it, the object would be created fine and then crash later
in `now_playing()` with a confusing `ZeroDivisionError` from the modulo in
`next_track()`, or an `IndexError`, far from the actual mistake.

Raising the error at the point where the bad value enters is called
**fail fast**. The general idea — make invalid objects impossible to create —
is also described as keeping a **class invariant**: a condition that is true
for every instance for its whole life ("there is at least one track, and
`_index` points at one of them").

`if not tracks` works because empty collections are **falsy** in Python:
`()`, `[]`, `""`, `0` and `None` all count as false in a condition.

### 5c. The state

Five **instance attributes** hold everything a player needs to remember:
which song (`_index`), playing or paused (`_status`), volume, mute. They start
in a realistic state: first track, paused, volume 50, unmuted. Tests rely on
these starting values (`test_starts_paused_on_first_track_at_half_volume`).

### 5d. The leading underscore: a naming convention

`_tracks`, `_index`, `_status`… start with an underscore. In Python this means
**"internal — don't touch from outside"**. The language doesn't enforce it
(there's no `private` keyword); it's a convention from PEP 8 that tools and
readers respect. The public way to change the volume is `set_volume()`, which
validates; writing `player._volume = 900` bypasses the rules, and the
underscore warns you that you're doing that.

This is **encapsulation**: the object controls its own state, and the outside
world goes through methods.

### 5e. `session_open`: public on purpose — a test seam

`session_open` is the one attribute **without** an underscore, and the comment
says why. It lets a test (or a developer at a Python prompt) simulate "the
browser was closed":

```python
fake.session_open = False
client.post("/api/next")   # → 409 Conflict
```

Without it, the entire "no media session" path — the 409 responses, the web
page's "Nothing playing" screen, the CLI's error message — could only be tested
on Windows by actually closing Chrome.

A deliberate point where tests can control or observe behaviour that's
otherwise hidden is called a **test seam** (a term from Michael Feathers,
*Working Effectively with Legacy Code*). Here it's also a **test hook**: an
attribute that exists mainly to make testing possible.

**The trade-off:** the real Windows adapter has no such switch — its "session"
is whatever Windows reports. So this attribute is a feature of the fake only;
nothing outside tests and the fake should rely on it.

---

## Block 6 — `_require_session`: a guard clause helper

```python
    def _require_session(self) -> None:
        if not self.session_open:
            raise NoMediaSessionError("no media session (the player is closed)")
```

**What:** raises the port's `NoMediaSessionError` if the "browser" is closed;
otherwise returns and lets the caller continue.

**Why it exists:** the port's **contract** (page 01, 7d) says *every* method
except `now_playing()` must raise `NoMediaSessionError` when there's nothing to
control. Nine methods need the same check. Writing the `if … raise` nine times
would work until someone changes the message in eight places and forgets the
ninth. One helper, called on the first line of each method, keeps them
identical (DRY again).

A check at the top of a function that exits early when a precondition fails is
called a **guard clause**. It keeps the "happy path" — the actual work — flat
and unindented below it.

**Why it's a plain `def`, not `async def`:** it doesn't wait for anything and
returns nothing to await. Async methods can call ordinary functions freely; only
calling *async* functions requires `await`.

---

## Block 7 — transport methods

```python
    async def play(self) -> None:
        self._require_session()
        self._status = PlaybackStatus.PLAYING

    async def pause(self) -> None:
        self._require_session()
        self._status = PlaybackStatus.PAUSED

    async def toggle_play_pause(self) -> None:
        self._require_session()
        if self._status == PlaybackStatus.PLAYING:
            self._status = PlaybackStatus.PAUSED
        else:
            self._status = PlaybackStatus.PLAYING
```

**What:** each method first applies the guard, then changes one attribute.

**`async def` with no `await` inside** is allowed and deliberate. The port
declares these methods `async` because the Windows adapter needs it (ADR
0005); the fake must match the signature so callers can `await` either adapter
the same way. Calling `await fake.play()` simply runs the body and returns.

**`toggle_play_pause` when stopped:** the `else` branch covers both *paused*
and *stopped*, so toggling from stopped starts playback — the same thing a
media key does. (The fake never actually enters *stopped*; the branch keeps it
correct if a test sets that state.)

### Wrap-around with modulo

```python
    async def next_track(self) -> None:
        self._require_session()
        # Modulo wraps from the last track back to the first, like a looping queue.
        self._index = (self._index + 1) % len(self._tracks)

    async def previous_track(self) -> None:
        self._require_session()
        self._index = (self._index - 1) % len(self._tracks)
```

**`%` is the modulo operator**: the remainder after division. With 5 tracks
(indexes 0–4):

| Current index | `next` computes | Result |
|---|---|---|
| 3 | `(3 + 1) % 5` | 4 |
| 4 (last) | `(4 + 1) % 5` = `5 % 5` | **0** (back to first) |

`previous_track` from the first song computes `(0 - 1) % 5` = `-1 % 5`.

**Here is a Python detail worth remembering:** in Python, `-1 % 5` is **4**,
because the result of `%` always takes the sign of the divisor. In C, C++,
Java, JavaScript and C#, `-1 % 5` is **-1**, and the same line would produce an
invalid index. Python's behaviour is what makes this one-liner correct; ported
to another language it would need `(i - 1 + n) % n`.

This pattern — an index that wraps around a fixed-size sequence — is often
called a **circular buffer** or **ring** index. It keeps `_index` always valid,
preserving the class invariant from Block 5b without any `if`.

**Why loop at all?** A real YouTube Music queue doesn't loop by default. The
fake loops so it never runs out of songs during development, however many
times you press next. That's a deliberate difference from the real player —
see Block 10.

---

## Block 8 — volume methods

```python
    async def get_volume(self) -> int:
        self._require_session()
        return self._volume

    async def set_volume(self, level: int) -> None:
        self._require_session()
        validate_volume(level)
        self._volume = level

    async def is_muted(self) -> bool:
        self._require_session()
        return self._muted

    async def set_muted(self, muted: bool) -> None:
        self._require_session()
        self._muted = muted
```

**Why `set_volume` calls the shared `validate_volume`:** the rule "0–100"
belongs to the port (page 01, Block 6), and both adapters call it, so they
can't disagree. The test `test_set_volume_rejects_out_of_range_and_keeps_old_value`
checks that a rejected value leaves the old volume untouched — which holds
because validation happens **before** the assignment. Swap the two lines and
the test would fail.

**The order of the checks is a small design decision too:** the session check
comes first. With the player closed, `set_volume(150)` raises
`NoMediaSessionError`, not `ValueError` — "there's nothing to control" is the
more fundamental problem. The real adapter behaves the same way.

**Mute is separate from volume:** muting doesn't set the volume to 0, and
unmuting restores it. That mirrors how Windows (and every media player) works:
the volume mixer keeps a volume level and a mute flag independently. The API
test `test_mute_and_unmute` checks that volume stays 50 while muted.

---

## Block 9 — `now_playing`

```python
    async def now_playing(self) -> NowPlaying | None:
        if not self.session_open:
            return None
        title, artist, album = self._tracks[self._index]
        return NowPlaying(title=title, artist=artist, album=album, status=self._status)
```

**No `_require_session()` here** — this is the one method the contract treats
differently: "nothing open" returns `None` instead of raising (page 01, 7d).

**`title, artist, album = ...`** is **tuple unpacking** (also called
*destructuring*): the three-item tuple is split into three variables in one
line. If a track had two or four items, it would raise `ValueError` — another
early failure instead of silent wrong data.

**A new `NowPlaying` on every call:** each call builds a fresh immutable
snapshot. Callers can keep it as long as they like; later changes to the fake
don't alter snapshots already handed out — exactly the property that
`frozen=True` promised on page 01.

**Keyword arguments** (`title=title, ...`) instead of positional ones
(`NowPlaying(title, artist, album, ...)`): if someone ever reorders the fields
of `NowPlaying`, positional calls would silently put the artist in the title;
keyword calls keep working.

---

## Block 10 — how faithful is the fake?

A fake is only useful if it behaves like the real thing *in the ways the rest
of the code depends on*. Where it differs, bugs can hide in the gap — tests
pass on the fake and fail on real hardware. This risk has a name: the fake
**drifting** from the real implementation.

| Behaviour | Fake | Real Windows player | Consequence |
|---|---|---|---|
| Contract: `NoMediaSessionError` / `None` | ✓ same | ✓ same | Guaranteed by tests on the fake + manual checks |
| State after a command | Immediate | Published 0.15–1 s later | The Windows adapter waits for it (ADR 0008), so callers see the same thing |
| Session during track change | Always present | Chrome drops it for ~1 s | Hidden by the Windows adapter's grace period |
| End of queue | Loops forever | Depends on YouTube Music | Only matters for manual testing |
| "Previous" late in a song | Always previous track | Restarts the same song | Windows adapter handles it with a timeout |
| Album | Always a string | Often `""`, converted to `None` | Page and CLI handle both |
| Volume | One number | Every audio session of the browser | Hidden by the Windows adapter |

The pattern in that table is the design working as intended: **every quirk of
the real player is absorbed inside the Windows adapter**, so the fake only has
to implement the *contract*, not the quirks. When Phase 4 found real-world
surprises, the fixes went into `windows.py`, and nothing about the fake or the
code above it had to change.

Two safeguards keep drift in check:

1. **The contract is tested on the fake**, method by method
   (`test_closed_player_rejects_every_command`).
2. **The real adapter is checked by hand** against a written checklist
   ([testing-on-windows.md](../testing-on-windows.md)), because CI has no
   desktop session to run it.

A stronger technique, not used here, is **contract testing**: one shared test
suite that runs against *both* adapters, so they're proven to behave the same.
It would need a Windows machine with a real browser in CI, which is why the
manual checklist exists instead.

---

## How the rest of the project uses this file

| Where | How |
|---|---|
| `server.py` | `build_controller()` returns `FakeMediaController()` when `RMC_CONTROLLER=fake` (the default) |
| `tests/conftest.py` | The `fake` fixture: a fresh instance per test, injected into the app |
| `tests/unit/test_fake_controller.py` | Tests the fake itself, including the contract |
| `tests/integration/*` | Sets `fake.session_open = False`, or replaces one method with `monkeypatch` to simulate failures (409, 502, 500) |
| Development | `uv run music-server` on Ubuntu serves the web page and CLI with these songs |
| README screenshot | The track shown is one of `DEMO_TRACKS` |

## Glossary

| Term | Meaning here |
|---|---|
| Adapter | A concrete implementation of the port |
| Test double | Any stand-in for a real dependency |
| Dummy / stub / spy / mock / fake | Kinds of test double, from "unused" to "working implementation" |
| Relative / absolute import | `from ..module` vs `from package.module` |
| Subclass | A class that inherits from another (`FakeMediaController(MediaController)`) |
| Atomic operation | A change that happens completely or not at all, with nothing interleaving |
| Mutable default argument pitfall | A list/dict default shared across calls; avoided with immutable defaults |
| Fail fast | Reject bad input where it enters, not later where it breaks |
| Class invariant | A condition true for every instance for its whole life |
| Falsy | Values that count as false: `()`, `[]`, `""`, `0`, `None` |
| Encapsulation / leading underscore | An object guards its own state; `_name` marks internals by convention |
| Test seam / test hook | A deliberate point where tests can control hidden behaviour |
| Guard clause | An early check that exits before the main work |
| Modulo / circular index | `%` remainder, used to wrap an index around a sequence |
| Tuple unpacking | `a, b, c = triple` |
| Keyword arguments | `f(name=value)`, robust to parameter reordering |
| Drift (of a fake) | The fake and the real implementation behaving differently over time |
| Contract testing | One test suite run against every implementation of an interface |

## Check your understanding

1. The real YouTube Music player doesn't loop forever. Why is it fine — even
   useful — that the fake does? When would that difference become a problem?
2. What would break, and where would you notice, if `_require_session()` were
   removed from `get_volume()` only?
3. Why is `session_open` public when every other attribute starts with `_`?
   Should the web page or the API ever use it?
4. `previous_track()` on the first song gives index 4 in Python. What would the
   same line give in JavaScript, and how would you fix it there?
5. A colleague adds `await asyncio.sleep(0.2)` at the start of `next_track()` to
   make the fake "feel more realistic". Which comment in the file is now wrong,
   and what could go wrong with two quick presses of "next"?
6. In `set_volume`, what test would fail if `validate_volume(level)` and
   `self._volume = level` swapped places? Why?
7. Chrome drops its media session for a second on every skip. Why didn't the
   fake need to imitate that?
