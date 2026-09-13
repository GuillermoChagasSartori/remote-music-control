# 01 — `media_controller.py`: the port

**File:** [`src/remote_music_control/media_controller.py`](../../src/remote_music_control/media_controller.py) · 125 lines
**Depends on:** only the Python standard library
**Used by:** every other module — the adapters implement it, the API and tests call it

## Where this file sits

```
            api.py ─────────┐        (knows HTTP)
            tests ──────────┤
                            ▼
                 media_controller.py         ← this file: knows only "a media player"
                            ▲
       adapters/fake.py ────┤        (knows nothing but memory)
       adapters/windows.py ─┘        (knows SMTC, pycaw, Windows)
```

The arrows point **towards** this file. Everything depends on it; it depends on
nothing in the project. That direction is the whole idea of the architecture,
and it's worth understanding before any line of code.

### The technique: ports and adapters

**Ports and adapters** (also called **hexagonal architecture**, coined by
Alistair Cockburn) splits a program into:

- a **core** that contains the application's rules and talks only through
  interfaces it defines itself — the **ports**;
- **adapters** that connect those ports to the outside world (a database, a
  web framework, an operating system API).

The analogy is a power socket. The socket (port) defines a shape. A lamp, a
laptop charger or a tester (adapters) all fit it. The wiring in the wall
doesn't care which one is plugged in.

Here the port is `MediaController`: "something that can play, pause, skip,
change volume and tell me what's playing". The real Windows player and the fake
in-memory player both plug into it.

A closely related principle is the **Dependency Inversion Principle** (the "D"
in SOLID): *high-level code should not depend on low-level details; both should
depend on abstractions.* Without it, `api.py` would import the Windows code
directly, and the whole server would be impossible to run on Linux.

**Why it matters in this project specifically** (ADR 0001): the Windows
libraries don't install on Linux. Because the API depends on this file and not
on Windows code, the server, web page, CLI and the whole test suite run on Ubuntu and
in CI. Only `adapters/windows.py` needed the studio PC.

**The alternative** would have been to call Windows APIs straight from the HTTP
handlers. Less code on day one — and then nothing could be tested without
walking to the studio.

---

## Block 1 — the module docstring

```python
"""The MediaController port: everything the application needs from a media player.

This module is the *port* in ports-and-adapters (hexagonal) architecture: an
...
"""
```

**What:** a string literal as the first statement of a file is its
**docstring**. Python stores it in `media_controller.__doc__`, and tools like
`help()` and editors show it.

**Why written this way:** the first thing a reader needs is "what is this file
for and what is it *not* allowed to know". The sentence *"Nothing in this file
knows about HTTP, Windows, or any library"* is a rule for future changes: if
you ever feel like importing `fastapi` or `winrt` here, the design is being
broken.

---

## Block 2 — imports and constants

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

MIN_VOLUME = 0
MAX_VOLUME = 100
```

**What:** three standard-library tools (explained below where they're used)
and two constants.

**Why constants instead of writing `0` and `100` everywhere:** the numbers
appear in this file, in `api.py` (request validation), in `cli.py` (argument
checks) and in tests. A named constant says *what* the number means, and there
is one place to change it. Writing the raw number in several places is known as
using **magic numbers** — values whose meaning the reader has to guess.

**Convention:** `UPPER_CASE` names signal "constant" in Python. The language
doesn't enforce it; it's an agreement from **PEP 8**, Python's official style
guide.

---

## Block 3 — `PlaybackStatus`, an enumeration

```python
class PlaybackStatus(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
```

**What:** an **enumeration** (enum) — a fixed set of named values. A track's
status can only be one of these three.

**Why an enum instead of plain strings:** with strings, a typo like
`"payling"` is silently accepted and fails somewhere far away. With an enum,
`PlaybackStatus.PAYLING` is an immediate `AttributeError`, and editors can
autocomplete the valid options. It also documents the complete set of states in
one place.

**Why `StrEnum` specifically** (Python 3.11+): each member *is* a real string.
`PlaybackStatus.PLAYING == "playing"` is `True`, and when FastAPI turns a
response into JSON it writes `"playing"` with no conversion code. A plain
`Enum` would need extra code to serialize.

**Why only three states when Windows has more:** SMTC reports *closed, opened,
changing, stopped, playing, paused*. The port offers only what the *clients*
need to display. Translating Windows' richer set down to these three is the
Windows adapter's job (`STATUS_FROM_SMTC` in `adapters/windows.py`). This is a
recurring theme: **the port is shaped by what the application needs, not by
what one particular technology happens to offer.**

---

## Block 4 — `NowPlaying`, an immutable data class

```python
@dataclass(frozen=True)
class NowPlaying:
    title: str
    artist: str
    album: str | None
    status: PlaybackStatus
```

**What:** a class whose only job is to hold four values.

**`@dataclass`** is a **decorator** — a function that receives the class and
returns a modified version. It reads the annotated fields and writes the
boring methods for you: `__init__` (so `NowPlaying(title=..., artist=..., ...)`
works), `__repr__` (readable printing) and `__eq__` (two snapshots with the
same values are equal — the tests rely on this).

Without it you'd write:

```python
class NowPlaying:
    def __init__(self, title, artist, album, status):
        self.title = title
        self.artist = artist
        ...
    def __eq__(self, other): ...
    def __repr__(self): ...
```

**`frozen=True`** makes instances **immutable**: after creation,
`track.title = "x"` raises an error. Why that matters: a `NowPlaying` is a
*snapshot* of the player at one moment. If some code could change the title
after the fact, the object would claim something the real player never said.
Immutable values are also safe to cache and share — the Windows adapter keeps
the last snapshot (`_last_now_playing`) for its grace period, and nobody can
alter it by accident.

In Domain-Driven Design this kind of object is called a **value object**: it's
defined entirely by its values, has no identity of its own, and doesn't change.

**`str | None`** (Python 3.10+) is a **type hint** meaning "a string, or
`None`". YouTube Music often has no album; `None` says "no album" explicitly,
where an empty string `""` would be ambiguous. (SMTC actually reports `""`; the
Windows adapter converts it to `None`.)

**Type hints don't enforce anything at runtime.** Python will happily create
`NowPlaying(title=42, ...)`. They're documentation that editors and type
checkers read — and FastAPI *does* use them to validate and describe JSON.

**Alternatives:** a plain `dict` (no names checked, easy to misspell keys), a
`NamedTuple` (also immutable, but behaves like a tuple, e.g. `track[0]`), or a
pydantic model (validation built in, but that would make this file depend on a
library — breaking the rule from Block 1).

---

## Block 5 — the exceptions

```python
class MediaControllerError(Exception):
    """Base class for every error an adapter is allowed to raise."""


class NoMediaSessionError(MediaControllerError):
    """Raised by commands when there is nothing to control (e.g. browser closed)."""
```

**What:** two custom exception classes forming a small **exception
hierarchy**: `NoMediaSessionError` *is a* `MediaControllerError`, which *is an*
`Exception`.

**Why custom exceptions:** each adapter fails in its own way — WinRT raises
`OSError`, pycaw raises COM errors, the fake raises nothing. If those leaked
out, `api.py` would need to know every library's error types, which is exactly
the coupling the port exists to prevent. Instead, adapters **translate**
low-level errors into these two types (see `_send()` in the Windows adapter),
and the API handles just these.

**Why two levels:**

- `NoMediaSessionError` — a *normal* situation: the browser is closed. The API
  answers **409 Conflict** with a friendly message.
- `MediaControllerError` — anything else the player got wrong, e.g. it refused
  a command. The API answers **502 Bad Gateway**.

Because of the inheritance, `except MediaControllerError` catches both, while
`except NoMediaSessionError` catches only the specific one. FastAPI picks the
**most specific** handler registered, which is how one error becomes 409 and
the other 502.

**The class body is only a docstring.** That's valid: a class needs at least
one statement, and a docstring counts. No extra behaviour is needed — the
*type* itself carries the meaning.

---

## Block 6 — `validate_volume`, a shared rule

```python
def validate_volume(level: int) -> None:
    """Shared rule for all adapters: volume is an integer percentage 0–100."""
    if not MIN_VOLUME <= level <= MAX_VOLUME:
        raise ValueError(f"volume must be between {MIN_VOLUME} and {MAX_VOLUME}, got {level}")
```

**What:** raises `ValueError` if `level` is outside 0–100; otherwise does
nothing.

**`MIN_VOLUME <= level <= MAX_VOLUME`** is a **chained comparison**, a Python
feature: it means `MIN_VOLUME <= level and level <= MAX_VOLUME`. Most languages
can't write it this way.

**`f"...{level}"`** is an **f-string**: the expressions in braces are inserted
into the text. Including the actual bad value in the message (`got 150`) makes
the error useful without a debugger.

**Why a function here and not inside each adapter:** the rule "volume is
0–100" belongs to the application, not to Windows or to the fake. Both adapters
call this one function, so they can't disagree. This is the **DRY** principle
(*Don't Repeat Yourself*) — applied to a *rule*, which matters more than
applying it to lines of code.

**Why `ValueError` and not `MediaControllerError`:** a volume of 150 isn't a
player failure; it's a caller passing a bad argument, and `ValueError` is
Python's standard exception for that. In practice the API never lets it happen
— pydantic rejects 150 with **422** before any adapter runs — so this is a
**defensive check**: a second line of protection for callers that bypass the
API (tests, scripts).

---

## Block 7 — `MediaController`, the port itself

```python
class MediaController(ABC):
    """Abstract interface for controlling one media player. ..."""

    @abstractmethod
    async def play(self) -> None: ...

    ...

    @abstractmethod
    async def now_playing(self) -> NowPlaying | None:
        """Return the current track, or None if no media session exists. ..."""
```

This is the heart of the file. Several ideas meet here.

### 7a. `ABC` and `@abstractmethod`: an abstract base class

**`ABC`** (from the `abc` module, "Abstract Base Classes") marks a class as a
template that can't be used on its own. **`@abstractmethod`** marks the methods
a subclass *must* provide.

The effect:

```python
MediaController()                  # TypeError: can't instantiate abstract class

class Forgetful(MediaController):
    async def play(self): ...      # implements only one method

Forgetful()                        # TypeError: ... abstract methods next_track, pause, ...
```

The error appears **when the object is created** — at server startup — rather
than minutes later when someone happens to press "next". The test
`test_port_refuses_an_adapter_with_missing_methods` proves it.

**The alternative: `typing.Protocol`** (called *structural typing* or
*duck typing*). A `Protocol` says "anything that has these methods counts",
without inheritance. It's more flexible (a class can satisfy it without knowing
it exists) but it only helps type checkers — at runtime Python doesn't stop you
from creating an incomplete adapter. This project uses `ABC` because the
adapters are written *for* this port on purpose, and a loud error at startup is
the more obvious behaviour (ADR 0001 context; mentioned in Phase 1).

### 7b. `...` as a method body

```python
async def play(self) -> None: ...
```

`...` is Python's **`Ellipsis`** object. As a statement it does nothing — it's
a placeholder meaning "no body here on purpose". `pass` would work the same;
`...` is the common convention for interface declarations. Methods with a
docstring (like `get_volume`) don't even need it — the docstring is the body.

### 7c. `async def`: coroutines

Every method is `async def`. Calling an async function doesn't run it; it
returns a **coroutine** — a task that runs when someone **`await`s** it:

```python
track = await controller.now_playing()
```

While a coroutine waits for something slow (a network reply, a Windows API
call), `await` hands control back to the **event loop**, which runs other
coroutines in the meantime — for instance, another HTTP request. One thread can
thereby serve many requests. This is **cooperative multitasking**: code gives
up control only at `await` points.

**Why the port is async** (ADR 0005): the Windows media API (WinRT) is
asynchronous — its Python calls must be awaited. If the port were synchronous,
the Windows adapter would have to run async code from inside sync code, inside
a server that already runs an event loop — a known source of deadlocks. The
decision had to be made in Phase 1, because changing a port later changes every
adapter and every caller. The fake adapter's methods are `async` too but never
actually wait; that costs nothing.

**The price:** anything calling these methods must itself be async, or use
`asyncio.run(...)`, as the unit tests do.

### 7d. The contract

The class docstring contains a rule that no code enforces:

> when there is nothing to control, every method raises `NoMediaSessionError`
> — except `now_playing()`, which returns `None`.

An interface isn't only method names and types; it's also **behaviour** that
callers rely on. This is called the **contract** of the interface
(*Design by Contract*, Bertrand Meyer). `api.py` relies on it: `/api/state`
checks for `None`, and commands rely on the exception becoming a 409.

The related principle is the **Liskov Substitution Principle** (the "L" in
SOLID): *any implementation must be usable wherever the interface is expected,
without the caller noticing.* If the Windows adapter returned `None` from
`get_volume()` instead of raising, it would satisfy the method *signature* but
break the *contract*, and the API would crash on real hardware while every test
with the fake passed.

That is why `test_closed_player_rejects_every_command` tests the contract on
the fake method by method: the fake must obey the same rules as the real
player, or the tests would be testing against a lie.

**Why `now_playing()` returns `None` instead of raising:** "nothing is playing"
is something the web page *displays*, polled every second. Using an exception
for an expected, frequent situation would turn normal flow into error handling.
Commands are different: asking to skip when nothing is open really is a request
that can't be fulfilled.

### 7e. Grouping and names

The comments `# --- Transport ---`, `# --- Volume ---`, `# --- State ---` group
the ten methods by purpose. The names avoid Python built-ins: `next_track`, not
`next` (which is a built-in function). The comment *"of the player application,
not the whole system"* records a decision from the plan: changing the browser's
volume must not move the Windows master volume.

**What's deliberately *not* in the port:** seek, shuffle, repeat, album art,
search, queue. Those are P1/P2 features. An interface should contain what the
application uses today — adding methods "just in case" forces every adapter to
implement things nobody calls. This is the **Interface Segregation Principle**
(the "I" in SOLID) and, more generally, **YAGNI** (*You Aren't Gonna Need It*).

---

## Block 8 — `change_volume`, application logic built on the port

```python
async def change_volume(controller: MediaController, delta: int) -> int:
    current = await controller.get_volume()
    new_level = max(MIN_VOLUME, min(MAX_VOLUME, current + delta))
    await controller.set_volume(new_level)
    return new_level
```

**What:** "volume up by 5" and "volume down by 10" become: read the current
volume, add `delta` (negative to go down), keep the result inside 0–100, write
it, return it.

**`max(MIN_VOLUME, min(MAX_VOLUME, x))`** is the standard **clamp** idiom:
`min` cuts off anything above 100, `max` lifts anything below 0. At 98, "+5"
gives `min(100, 103) = 100`.

**Why clamp instead of rejecting:** pressing "volume up" near the top should
just land on 100. An error message for "98 + 5" would be technically correct
and annoying. `set_volume(150)` from a *caller* is rejected (Block 6);
*stepping* past the edge is clamped. Different situations, different behaviour.

**Why this function lives here** — not in the API and not in the adapters:

- Not in `api.py`: the rule would then be tied to HTTP. A future client (the
  browser extension in Phase 8) would have to duplicate it.
- Not in each adapter: two copies of the same arithmetic that could drift apart.
- Here: it uses **only port methods**, so it works with every adapter,
  including ones that don't exist yet.

It takes the controller as a **parameter** instead of creating one — the same
**dependency injection** idea used throughout the project. In ports-and-adapters
vocabulary, a function like this that orchestrates port calls to perform one
user action is often called a **use case** or **application service**.

**A limitation worth knowing:** this is a **read–modify–write** sequence, and
it has two `await`s. If two "volume up" requests arrive at the same moment on
the real player, both could read 50, both compute 55, and both write 55 — one
press is lost. This is a **race condition**, specifically a **lost update**.
It's accepted here because a single user clicking a button can't realistically
trigger it, and the effect is one missed step of 5. If it ever mattered, the
fix would be an `asyncio.Lock` held across the read and the write.

---

## How the rest of the project uses this file

| Module | What it uses | Why |
|---|---|---|
| `adapters/fake.py` | subclasses `MediaController`; raises `NoMediaSessionError`; calls `validate_volume` | implements the port in memory |
| `adapters/windows.py` | same, plus `MediaControllerError`; maps SMTC states to `PlaybackStatus` | implements the port with Windows APIs |
| `api.py` | calls the methods and `change_volume`; turns the two exceptions into 409/502; uses `NowPlaying` in the JSON schema | exposes the port over HTTP |
| `cli.py` | `MIN_VOLUME`, `MAX_VOLUME` | checks arguments before sending them |
| `server.py` | the `MediaController` type | `build_controller()` promises to return *some* adapter |
| tests | everything | unit tests of the rules and the contract |

## Glossary

| Term | Meaning here |
|---|---|
| Ports and adapters / hexagonal architecture | Core defines interfaces (ports); outside technologies plug in through adapters |
| Port | `MediaController` — the interface the application depends on |
| Adapter | A concrete implementation: `FakeMediaController`, `WindowsMediaController` |
| Dependency Inversion Principle | Depend on abstractions, not on concrete low-level code |
| Abstract base class (ABC) | A class that can't be instantiated and forces subclasses to implement marked methods |
| Structural typing / `Protocol` | The alternative: "has the right methods" instead of "inherits from" |
| Enumeration (enum) | A fixed set of named values |
| Data class | A class generated from its field list |
| Immutable / value object | An object that can't change after creation and is defined by its values |
| Type hint | An annotation describing expected types; not enforced at runtime |
| Exception hierarchy | Exception classes related by inheritance, caught broadly or narrowly |
| Coroutine / `async` / `await` | A function that can pause at `await` so the event loop can run other work |
| Event loop | The scheduler that runs coroutines, switching at `await` points |
| Contract / Design by Contract | The promised behaviour of an interface, beyond its signatures |
| Liskov Substitution Principle | Every implementation must honour the interface's contract |
| Interface Segregation / YAGNI | Keep interfaces to what's actually used |
| DRY | Don't Repeat Yourself — one authoritative place for each rule |
| Magic number | An unexplained literal value; replaced here by named constants |
| Clamp | Limit a value to a range with `max(low, min(high, x))` |
| Use case / application service | A function that performs one user action using ports |
| Race condition / lost update | Two concurrent read–modify–write sequences overwriting each other |

## Check your understanding

Try answering before re-reading. Mark the ones that aren't clear and send them
back for a deeper pass.

1. Why would importing `fastapi` in this file break the architecture, even if
   the code still ran?
2. What exactly happens, and *when*, if a new adapter forgets to implement
   `set_muted`?
3. `now_playing()` returns `None` for "nothing open", but `play()` raises. Why
   the difference?
4. Suppose someone changed the Windows adapter so that `get_volume()` returns
   `0` when the browser is closed, instead of raising. Which principle would
   that break, and what would go wrong in the API?
5. Why is `change_volume` a function in this file rather than a method of each
   adapter, or code inside the `/api/volume/up` endpoint?
6. What would you change to make two simultaneous "volume up" presses always
   add 10?
