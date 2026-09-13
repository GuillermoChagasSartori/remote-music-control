# 05 — `cli.py`: the command-line client

**File:** [`src/remote_music_control/cli.py`](../../src/remote_music_control/cli.py) · ~250 lines
**Depends on:** `httpx2`, `config.py` ([page 04](04-configuration.md)), two constants from `media_controller.py`
**Used by:** the `music` command; `tests/unit/test_cli_parsing_and_output.py` and `tests/integration/test_cli.py`

## Where this file sits

```
 your terminal                          studio PC
┌──────────────┐    HTTP + token    ┌──────────────────────────┐
│ music next   │ ─────────────────▶ │ api.py → port → adapter  │
│  (cli.py)    │ ◀───────────────── │                          │
└──────────────┘    JSON / status   └──────────────────────────┘
```

The CLI is a **thin client**: it turns a command into an HTTP request, sends it
to the server, and turns the answer into text. It contains **no media logic**.

**Why not call the port directly**, like `api.py` does? Because the CLI runs on
a *different computer* from the player. It can only reach it over the network,
through the same API the web page and phone use. That has a useful side effect:
the CLI and the web page **can't disagree** about behaviour (volume clamping,
token rules, error handling), because the server does all of it. The CLI is
also a second, independent client that exercises the API — which is how several
server bugs were found during development.

### How `music` becomes a command

`pyproject.toml` declares:

```toml
[project.scripts]
music = "remote_music_control.cli:main"
```

This is a **console script entry point**. When `uv sync` installs the project,
it generates a small executable named `music` in `.venv/bin` (Linux) or
`.venv\Scripts` (Windows) that imports this module and runs
`sys.exit(main())`. `uv run music …` finds it there. No shell script or `PATH`
editing is involved.

---

## Block 1 — docstring and imports

```python
import argparse
import sys
from typing import Any

import httpx2

from .config import ConfigError, default_config_path, load_client_settings
from .media_controller import MAX_VOLUME, MIN_VOLUME
```

**`argparse`** is the standard library's command-line parser. The plan asked
for "plain httpx + argparse; no CLI framework unless you justify it". The
popular alternatives:

| Library | What it adds | Why not here |
|---|---|---|
| **Click** | Decorators per command, nice help, prompts, colours | An extra dependency for ~12 simple commands |
| **Typer** | Commands generated from type hints (built on Click) | Same, plus a second layer to learn |

argparse is more verbose, but everything it does is visible in one function
(Block 7), and it's always available.

**`httpx2`** is the HTTP client (ADR 0010): the maintained successor of `httpx`,
with the same API, chosen because FastAPI's test client uses it too — which is
what lets the tests run the CLI against the real app (Block 8).

**`from .media_controller import MAX_VOLUME, MIN_VOLUME`** — the CLI imports
the port module only for these two constants, so "0–100" is defined in one
place. It doesn't use anything else from the port.

**`Any`** is the type hint for "any type at all". JSON answers are nested
dicts, lists, strings and numbers whose exact shape Python's type system can't
express simply; `dict[str, Any]` says "a dictionary with string keys" and
stops there.

---

## Block 2 — constants

### 2a. Timeouts

```python
REQUEST_TIMEOUT = httpx2.Timeout(10.0, connect=3.0)
```

A **timeout** is how long to wait before giving up. Without one, a request to
a PC that's switched off could leave your terminal frozen indefinitely.

There are really two different waits, and they deserve different limits:

| Phase | Limit | Why |
|---|---|---|
| **Connect** — reaching the server | 3 s | On a home LAN, connecting takes milliseconds. If nothing answers in 3 s, the PC is off or unreachable: say so quickly. |
| **Read** — waiting for the answer | 10 s | On the real player, commands wait until their effect is visible (ADR 0008): `next` measured ~2.3 s, and up to ~4.5 s during Chrome's track-change gap. |

This file originally used a single 3-second limit. It worked against the fake,
where everything is instant. While writing this page, `music next` was timed on
the real player at **2.29 s** — leaving 0.7 s of margin before a false "did not
answer in time" for a command that had actually worked. Splitting the two
limits fixed it without making a dead server slower to detect.

**The lesson generalizes:** timeouts must be set from **measurements of the
real system**, not from how the test double behaves.

### 2b. A table of commands

```python
TRANSPORT_COMMANDS = (
    ("play", "/api/play", "resume playback"),
    ("pause", "/api/pause", "pause playback"),
    ("toggle", "/api/play-pause", "play if paused, pause if playing"),
    ("next", "/api/next", "skip to the next track"),
    ("prev", "/api/previous", "go back to the previous track"),
)
```

Five commands that differ only in their name, path and help text are written
as **data**, and one loop (Block 7) turns them into commands. Adding a
transport command means adding a line to this table. This is called
**table-driven** or **data-driven** design: when many pieces of code differ
only in values, put the values in a table and write the code once.

Note that CLI names and API paths don't have to match: the user types `prev`
and `toggle`; the API says `/previous` and `/play-pause`. The table is where
that translation lives.

### 2c. Status symbols

```python
STATUS_SYMBOLS = {"playing": "▶", "paused": "⏸", "stopped": "■"}
```

Used with `STATUS_SYMBOLS.get(status, "?")`: if a future server version
reports a status this CLI doesn't know, it prints `?` instead of crashing.
Tolerating unknown values from another program is a small case of
**forward compatibility**.

---

## Block 3 — formatting: pure functions

```python
def format_state(state: dict[str, Any]) -> str:
    track = state["now_playing"]
    if track is None:
        return "nothing playing (no media session — is the player open?)"
    symbol = STATUS_SYMBOLS.get(track["status"], "?")
    line = f"{symbol} {track['title']} — {track['artist']}"
    if track["album"]:
        line += f" ({track['album']})"
    return f"{line}\n{format_volume(state)}"


def format_volume(volume: dict[str, Any]) -> str:
    text = f"volume {volume['volume']}%"
    if volume["muted"]:
        text += " (muted)"
    return text
```

These take JSON-shaped data and **return** a string. They don't print, don't
send requests, don't read settings. A function whose result depends only on its
arguments and that changes nothing outside itself is a **pure function**.

**Why that matters:** pure functions are trivial to test — call, compare the
string — with no server, no captured output, no network. The unit tests in
`test_cli_parsing_and_output.py` do exactly that. The code that *does* have side
effects (printing, HTTP) is kept in thin handlers around them. This split is
often called **functional core, imperative shell**: logic in pure functions at
the centre, input/output at the edges.

**Small details:**

- **`if track["album"]:`** is false for both `None` and `""`, so a missing album
  prints nothing in either form.
- **`format_volume(state)`** works on the full state *and* on a volume response,
  because both contain `volume` and `muted` keys. Relying on an object having
  the needed keys rather than being a specific type is **duck typing** ("if it
  walks like a duck…").
- **Mixed quotes in f-strings** — `f"{track['title']}"` — single quotes inside
  double quotes, so the string doesn't end early.

---

## Block 4 — command handlers

```python
def run_health(client: httpx2.Client, args: argparse.Namespace) -> None:
    request(client, "GET", "/health")  # public: is the server up at all?
    print(f"server ok at {args.url}")
    request(client, "GET", "/api/state")  # requires the token: is ours accepted?
    print("token accepted")


def run_now(client, args) -> None:
    print(format_state(request(client, "GET", "/api/state")))


def run_transport(client, args) -> None:
    request(client, "POST", args.path)
    run_now(client, args)
```

**Every handler has the same signature**: `(client, args) -> None`. That
uniformity is what makes the dispatch table in Block 7 possible — `main()` can
call any of them the same way without knowing which command ran.

**`run_health` checks two things in order**, printing after each: first the
public `/health` (is the server there?), then a token-protected route (is our
token right?). If the second fails, you already saw "server ok", so the error
clearly points at the token, not the network. Designing a diagnostic command so
each step narrows the problem is a small, useful habit.

**`run_transport` reuses `run_now`** to print the state after the command, so
`music next` shows the new song. It can do that immediately because the server
replies only once the change is visible (ADR 0008) — an earlier version printed
the *old* song on the real player, found in Phase 4.

```python
def run_volume(client, args) -> None:
    if args.level is None:
        data = request(client, "GET", "/api/volume")
    else:
        data = request(client, "PUT", "/api/volume", json={"level": args.level})
    print(format_volume(data))


def run_volume_step(client, args) -> None:
    params = {} if args.step is None else {"step": args.step}
    print(format_volume(request(client, "POST", args.path, params=params)))


def run_mute(client, args) -> None:
    print(format_volume(request(client, "PUT", "/api/mute", json={"muted": args.muted})))
```

- **One command, two meanings:** `music vol` reads; `music vol 40` sets. The
  optional argument decides which request to send.
- **`json={...}`** makes httpx2 encode the dict as JSON and set
  `Content-Type: application/json`. **`params={...}`** becomes the query string
  (`?step=10`).
- **`run_volume_step` sends no `step` when you don't give one.** The default of
  5 then comes from the server (`DEFAULT_VOLUME_STEP` in `api.py`). If the CLI
  sent its own 5, there would be two defaults to keep in sync — a duplicated
  **source of truth**.
- **`{} if ... else {...}`** is a **conditional expression** (Python's
  one-line if/else).

---

## Block 5 — `request`: one place for HTTP

```python
def request(client: httpx2.Client, method: str, path: str, **kwargs: Any) -> Any:
    """Send one request; return the JSON body (or None for 204 No Content)."""
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    if response.status_code == httpx2.codes.NO_CONTENT:
        return None
    return response.json()
```

Every handler goes through this helper, so every request gets the same
treatment:

- **`**kwargs`** collects any extra keyword arguments (`json=`, `params=`) into
  a dict and passes them straight on. The helper doesn't need to know about each
  option — it **forwards** them.
- **`raise_for_status()`** raises `HTTPStatusError` for any 4xx or 5xx answer.
  Handlers therefore never check status codes: if the request failed, the code
  after it simply doesn't run, and `main()` deals with the error. It's the same
  idea as the API's exception handlers: **don't check for errors on every
  line; let them propagate to one place** that knows what to do.
- **204 has no body**, so calling `.json()` on it would fail; returning `None`
  instead makes "no content" explicit.

---

## Block 6 — argument converters

```python
def volume_level(text: str) -> int:
    """argparse `type=` converter: reject bad input before any request is sent."""
    try:
        level = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if not MIN_VOLUME <= level <= MAX_VOLUME:
        raise argparse.ArgumentTypeError(f"must be between {MIN_VOLUME} and {MAX_VOLUME}")
    return level


def volume_step(text: str) -> int:
    step = volume_level(text)
    if step == 0:
        raise argparse.ArgumentTypeError("step must be at least 1")
    return step
```

argparse passes each argument to its `type=` function as a string. A converter
returns the converted value or raises **`ArgumentTypeError`**, which argparse
turns into a standard usage error:

```
usage: music vol [-h] [level]
music vol: error: argument level: must be between 0 and 100
```

**Validation on both sides:** the server rejects 150 too (with 422). The CLI
checks anyway because a local, immediate, specific message is a better
experience than a network round trip and a JSON error. The rule of thumb:
**client-side validation is for the user's convenience; server-side validation
is for correctness and security.** The server can never skip its own checks —
other clients (curl, a modified page) don't validate at all.

**`volume_step` builds on `volume_level`** — a step is a level with one extra
rule — instead of repeating the number parsing.

**`from None`** hides the original `ValueError` from `int()` (page 04, Block
11): argparse only needs the friendly message.

---

## Block 7 — `build_parser`: subcommands and the dispatch table

```python
def build_parser(default_url: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="music", description="Control music on the studio PC.")
    parser.add_argument(
        "--url",
        default=default_url,
        help=f"server address (default: $RMC_SERVER_URL or {default_url})",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    ...
    return parser
```

### 7a. The top-level parser

- **`prog="music"`** fixes the name in help and error messages (otherwise it
  would show the script's file name).
- **`--url`** is an **option** (starts with `--`, optional). Its default comes
  from the settings — so the precedence is: `--url` on the command line, then
  `RMC_SERVER_URL`, then the config file, then the built-in default.
- **Building the parser in a function** (not at module level) lets tests create
  one with any default URL and inspect the result without running anything.

### 7b. Subcommands

`add_subparsers` creates **subcommands** — the `git commit` / `git push` style,
where the first word chooses an action with its own arguments and help:

```
$ music --help          # lists all commands
$ music vol --help      # help for one command
```

`required=True` makes `music` with no command an error instead of silently
doing nothing; `metavar="COMMAND"` shows that word in the usage line instead of
a long `{health,now,play,...}` list.

### 7c. The dispatch table

```python
    commands.add_parser("now", help="show the current track and volume").set_defaults(handler=run_now)

    for name, path, help_text in TRANSPORT_COMMANDS:
        commands.add_parser(name, help=help_text).set_defaults(handler=run_transport, path=path)
```

**`set_defaults(handler=run_now)`** stores an extra value in the parsed result:
after `parse_args(["now"])`, `args.handler` *is* the function `run_now`. In
Python, functions are ordinary objects — they can be stored, passed and called
later (**first-class functions**).

So `main()` doesn't need:

```python
if args.command == "now":
    run_now(client, args)
elif args.command == "play":
    ...                      # twelve branches
```

It just calls `args.handler(client, args)`. Mapping names to functions this way
is a **dispatch table**. Adding a command touches one place — where it's
declared — instead of a declaration *and* a branch that could get out of sync.

The loop also stores **`path`** per command, so the single `run_transport`
handler knows which endpoint to call. One function plus data replaces five
nearly identical functions.

### 7d. Optional positional arguments

```python
    vol = commands.add_parser("vol", help="show the volume, or set it: music vol 40")
    vol.add_argument("level", nargs="?", type=volume_level, help="new volume, 0–100")
    vol.set_defaults(handler=run_volume)
```

**`nargs="?"`** means "zero or one value". Without a value, `args.level` is
`None` — which is how `run_volume` tells "read" from "set".

### 7e. Why `up`/`down` and not `vol +5`

```python
    # Separate `up`/`down` commands instead of `vol +5`/`vol -5`, because
    # argparse would read "-5" as an unknown option flag.
```

To argparse, anything starting with `-` looks like an option (`-h`, `--url`).
`music vol -5` fails with "unrecognized arguments". Two subcommands with a
positive step are clearer anyway, and they map directly to the two API routes.

### 7f. Mute and unmute

```python
    commands.add_parser("mute", help="mute the player").set_defaults(handler=run_mute, muted=True)
    commands.add_parser("unmute", help="unmute the player").set_defaults(handler=run_mute, muted=False)
```

Two commands, one handler, a different stored value. The same dispatch idea,
again with data doing the varying.

---

## Block 8 — `make_client`: the test seam

```python
def make_client(url: str, token: str | None) -> httpx2.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.Client(base_url=url, headers=headers, timeout=REQUEST_TIMEOUT)
```

**What it builds:** an `httpx2.Client` configured once — base URL (so handlers
write `/api/next`, not the full address), the token header, the timeouts — and
used for every request of the command.

A `Client` also keeps connections open between requests (**connection
pooling** / HTTP **keep-alive**). `music health` makes two requests; the second
reuses the first connection instead of opening a new one.

**Why the token never comes from a command-line option:** anything on a command
line is saved in your shell history (`~/.bash_history`) and visible to other
users of the machine while the command runs (`ps aux`). A `--token` option
would leak it in both places. Environment variables and a `0600` config file
don't.

**Why this is a separate function** — the most important reason: it's a
**test seam** (page 02). The integration tests replace it:

```python
monkeypatch.setattr(cli, "make_client",
                    lambda url, token: TestClient(app, headers=...))
```

FastAPI's `TestClient` *is* an `httpx2.Client` that sends requests straight into
the app in memory. So `cli.main(["next"])` in a test runs the real argument
parsing, the real handler, a real HTTP request through the real API, the real
fake player, and the real output formatting — with no server process and no
network. The unreachable-server and timeout tests replace it with a client whose
transport raises the error to simulate.

This only works because the CLI and `TestClient` use the **same library** —
the reason for switching to `httpx2` (ADR 0010).

---

## Block 9 — turning server errors into messages

```python
def server_error_message(response: httpx2.Response) -> str:
    """Prefer the server's own explanation ("detail") over a bare status code."""
    try:
        detail = response.json().get("detail")
    except ValueError:  # body wasn't JSON
        detail = None
    if isinstance(detail, str):
        return f"server returned HTTP {response.status_code}: {detail}"
    return f"server returned HTTP {response.status_code}"
```

The API puts human-readable explanations in `{"detail": "..."}` (page 03,
Block 11). This shows them: `server returned HTTP 409: no media session from
chrome.exe, firefox.exe — is the player open?`.

**Defensive about the shape**, because error responses aren't always ours:

- The body might not be JSON at all (a proxy's HTML error page) —
  `response.json()` raises `ValueError` (its JSON decoding error is a subclass
  of it), handled by falling back.
- For a 422, `detail` is a *list* of validation problems, not a string —
  `isinstance(detail, str)` falls back to the bare code.

**`try` first, handle the failure** instead of checking in advance
("is this JSON?") is the Pythonic style known as **EAFP** — *easier to ask
forgiveness than permission*. The opposite, checking first, is **LBYL** —
*look before you leap*.

---

## Block 10 — UTF-8 output

```python
def use_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
```

**The problem it solves** (found and fixed while writing this page): text
must be **encoded** into bytes to be written anywhere. On Windows, when Python's
output goes to a real console it uses UTF-8, but when it's **redirected** —
`music now > file.txt`, or piped into another program — Python falls back to
the system's legacy **code page**, `cp1252` on this PC. That encoding has no "▶"
character, so `print` raised `UnicodeEncodeError` and the CLI crashed with a
traceback. Tested on the studio PC before the fix: crash; after: `▶ The Missing
Piece — ProleteR`, exit code 0.

**The fix:** switch both streams to UTF-8 at startup. `errors="replace"` means
that if something still can't be encoded, it becomes `?` instead of crashing.

**Context:** Python has been moving to UTF-8 everywhere. **PEP 686** makes UTF-8
the default on all systems from Python 3.15; until then, programs that print
non-ASCII text do this themselves. The server does the same for its log
(page 06).

**`hasattr(stream, "reconfigure")`** — some tools replace `sys.stdout` with
objects that aren't real text streams. Checking for the method before calling
it (duck typing again) keeps the CLI working under them.

---

## Block 11 — `main`: exit codes and error translation

```python
def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    try:
        settings = load_client_settings()
    except ConfigError as error:
        print(f"music: configuration error: {error}", file=sys.stderr)
        return 1
    args = build_parser(settings.server_url).parse_args(argv)

    try:
        with make_client(args.url, settings.token) as client:
            args.handler(client, args)
    except (httpx2.ConnectError, httpx2.ConnectTimeout):
        print(f"music: cannot connect to server at {args.url} — is it running and reachable?", file=sys.stderr)
        return 1
    except httpx2.TimeoutException:  # connected, but the answer took too long
        print(f"music: server at {args.url} did not answer in time", file=sys.stderr)
        return 1
    except httpx2.HTTPStatusError as error:
        if error.response.status_code == httpx2.codes.UNAUTHORIZED:
            ...  # explains which file to put the token in
        else:
            print(f"music: {server_error_message(error.response)}", file=sys.stderr)
        return 1
    except httpx2.HTTPError as error:
        print(f"music: request failed: {error}", file=sys.stderr)
        return 1
    return 0
```

### 11a. `argv` for testability

`parse_args(None)` reads the real command line (`sys.argv`); tests pass a list:
`cli.main(["vol", "40"])`. Same technique as `environ` on page 04.

### 11b. Exit codes

A program tells the shell whether it succeeded through its **exit code**:

| Code | Meaning | From |
|---|---|---|
| 0 | Success | `return 0` |
| 1 | Failed: server down, token wrong, player closed… | `return 1` |
| 2 | Wrong usage: unknown command, `vol 150` | argparse, automatically |

This is how scripts and shells know what happened: `music pause && echo done`
only prints if pausing worked. Using 2 for usage errors is a long-standing
Unix convention that argparse follows.

### 11c. stdout vs stderr

Results go to **stdout** (`print(...)`); errors go to **stderr**
(`print(..., file=sys.stderr)`). They're separate streams: `music now >
song.txt` puts the song in the file while errors still appear in the terminal,
and a script can capture one without the other.

### 11d. Error translation, and why the order matters

The handler code just makes requests; every failure surfaces here as an
exception and becomes **one clear line** instead of a traceback. The exceptions
form a hierarchy (verified):

```
HTTPError
├── HTTPStatusError                     ← server answered 4xx/5xx
└── RequestError
    └── TransportError
        ├── NetworkError
        │   └── ConnectError            ← nothing listening
        ├── TimeoutException
        │   ├── ConnectTimeout          ← no reply at all: PC off/unreachable
        │   └── ReadTimeout             ← connected, answer too slow
        └── ProtocolError ...
```

Python checks `except` clauses **top to bottom** and uses the first match. So
specific cases must come before general ones — if `except httpx2.HTTPError`
were first, it would catch everything and the specific messages would never be
reached.

**`ConnectTimeout` is grouped with `ConnectError`**, even though the library
classifies it as a timeout. For you, "the server process is stopped" and "the
PC is switched off" are the same problem — *can't reach it* — and "did not
answer in time" would suggest the server is slow rather than absent. This was
found while writing this page by timing a request to an unreachable address:
it raised `ConnectTimeout` after 3 s, and the message was misleading.
**Error messages should describe the user's situation, not the library's
taxonomy.**

**401 gets its own message**, because it's the most common setup mistake and
has a precise fix: it says whether the token is *missing* or *rejected*, and
names the config file path on this machine.

**`with make_client(...) as client:`** closes the client's connections when the
command finishes — even if it raised.

### 11e. Entry point

```python
if __name__ == "__main__":
    sys.exit(main())
```

When a file is run directly (`python -m remote_music_control.cli`), Python sets
its `__name__` to `"__main__"`; when it's imported (by the tests, or by the
`music` launcher), `__name__` is the module name and this block doesn't run.
`sys.exit(code)` ends the process with that exit code.

---

## Known limitations

- **A broken config file blocks `music --help`**, because settings are loaded
  before arguments are parsed (the parser needs the default URL). The error
  message names the file, so it's fixable, but help should arguably always work.
- **Ctrl+C during a slow command** prints a Python traceback instead of a quiet
  exit. Catching `KeyboardInterrupt` in `main()` would fix it.
- **No machine-readable output.** Scripts parsing `▶ Title — Artist` would be
  fragile; a `--json` option would be the proper way to support them.

## How it's tested

| Test file | What it checks |
|---|---|
| `tests/unit/test_cli_parsing_and_output.py` | Pure formatting, converters, parser wiring, error message fallbacks |
| `tests/integration/test_cli.py` | `cli.main([...])` end to end against the real app (via `make_client` → `TestClient`): output of each command, missing/wrong token messages, 409 message, argparse exit code 2, unreachable server, timeouts, network failures, UTF-8 output into a cp1252 stream |

## Glossary

| Term | Meaning here |
|---|---|
| Thin client | A client that only sends requests and shows results; all logic lives on the server |
| Console script entry point | `[project.scripts]` entry that installs a command calling a Python function |
| Timeout (connect / read) | Maximum wait to reach the server / to receive its answer |
| Table-driven design | Varying values kept in a table, processed by one piece of code |
| Forward compatibility | Tolerating values a newer version might send |
| Pure function | Result depends only on arguments; no side effects |
| Functional core, imperative shell | Logic in pure functions, input/output at the edges |
| Duck typing | Relying on an object's methods/keys rather than its type |
| `**kwargs` forwarding | Passing unknown keyword arguments on unchanged |
| Client- vs server-side validation | For user convenience vs for correctness and security |
| Subcommand | `tool action [args]` style, like `git commit` |
| First-class functions | Functions as values: stored, passed, called later |
| Dispatch table | A mapping from names to the functions that handle them |
| Source of truth | The single place a value or rule is defined |
| Connection pooling / keep-alive | Reusing an open connection for several requests |
| Test seam | A replaceable point where tests inject a different implementation |
| EAFP / LBYL | Try and handle failure / check before acting |
| Encoding / code page | Mapping text to bytes; `cp1252` is Windows' legacy Western code page |
| Exit code | Number a process returns to the shell: 0 success, 1 failure, 2 usage |
| stdout / stderr | Separate output streams for results and errors |
| Exception hierarchy | Exception classes related by inheritance, matched top-down |

## Check your understanding

1. `music next` against the fake takes milliseconds; against the studio PC,
   about 2.3 s. Why is it wrong to choose the timeout by testing only with the
   fake? What would a single 3-second timeout have caused?
2. Why does `run_volume_step` avoid sending `step=5` when no step is given?
3. Rewrite the command handling in `main()` without `set_defaults(handler=...)`.
   What becomes easier to get wrong when a new command is added?
4. What would happen if `except httpx2.HTTPError` were moved to be the first
   `except` clause?
5. Your studio PC is switched off. Which exception does `httpx2` raise, after
   how long, and what does the CLI print?
6. Why can't the token be a `--token` option? Name both places it would leak.
7. The server already rejects volume 150. Why does the CLI check it too — and
   why must the server *never* rely on the CLI's check?
8. How can `tests/integration/test_cli.py` test the CLI against the real API
   without starting a server? Which design choice in this file makes it
   possible?
9. `music now > song.txt` crashed on Windows but worked on Ubuntu. Explain why,
   in terms of encodings.
