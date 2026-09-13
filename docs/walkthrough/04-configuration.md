# 04 — `config.py`: configuration

**File:** [`src/remote_music_control/config.py`](../../src/remote_music_control/config.py) · ~210 lines
**Depends on:** only the Python standard library
**Used by:** `server.py` (server settings, `init`, log path), `cli.py` (client settings), the tests

## Where this file sits

Every other module needs a few facts that differ between machines: which
adapter to load, which address to listen on, the token, where the server is.
This file is the **one place** those facts are read, checked and turned into
plain Python objects. Nothing else in the project touches `os.environ` or
reads the config file.

```
 environment variables ─┐
                        ├──▶ config.py ──▶ ServerSettings ──▶ server.py
 config.env file ───────┤     (merge,       ClientSettings ──▶ cli.py
                        │      validate)
 defaults in the code ──┘
```

Two ideas from the project plan shape the whole file: *"one file, one place"*
and *"the twelve-factor convention of environment variables with sane
defaults"*.

### The technique: twelve-factor configuration

**The Twelve-Factor App** (twelve-factor.net) is a short methodology, written
by engineers at Heroku, for building services that are easy to deploy and run.
Its **factor III, "Config"**, says:

> Store config in the environment.

"Config" means everything that varies between **deploys** — your Ubuntu PC,
the studio PC, a CI runner — while the code stays identical: addresses, ports,
credentials, which backend to use. The rule is strict about one thing:
**config never lives in the code.** A quick test from the methodology: *could
you publish the code right now without leaking a credential?* This repository
is public, so the answer had to be yes from day one.

Environment variables are the recommended mechanism because every operating
system and every tool (shells, CI systems, Task Scheduler, containers) can set
them without touching the code or the repository.

**How this project adapts it:** pure environment variables are awkward for a
desktop app started by a logon task, and a token typed into a shell profile is
easy to leak. So values come from **three sources, in order of priority**:

1. **Environment variables** — highest priority, for overrides
   (`RMC_PORT=9000 uv run music-server`).
2. **A per-user config file**, `config.env` — the normal place for the token
   and machine settings.
3. **Defaults in this file** — so a fresh checkout runs with almost no setup.

This layering is common in real tools (Git, Docker, pip all combine defaults,
files and variables). The ordering is called **precedence**, and "most
specific / most temporary wins" is the usual rule.

---

## Block 1 — the module docstring

The docstring is effectively the user documentation for configuration: the
precedence order, where the file lives on each system, why it's outside the
repository, and the naming convention. Someone wondering "why is my setting
ignored?" should find the answer at the top of this file.

**The `RMC_` prefix:** environment variables are one global namespace shared by
every program. A variable called `PORT` or `TOKEN` could collide with another
tool's. A project prefix is the standard way to avoid that — a form of
**namespacing**.

**`%APPDATA%\\remote-music-control`** is written with double backslashes because
inside a normal Python string `\r` would be a carriage-return character. `\\`
means one literal backslash.

---

## Block 2 — imports

```python
import os
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
```

All standard library, on purpose: this file must never fail to import because
of a missing package, since it's what produces the helpful error messages.

**`Mapping`** is an abstract type meaning "anything you can read like a
dictionary". `os.environ` is one; so is a plain `dict`. Accepting `Mapping`
instead of `dict` is what lets tests pass a dict (Block 11).

---

## Block 3 — choices and defaults

```python
CONTROLLER_CHOICES = ("fake", "windows")
LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR")

DEFAULT_CONTROLLER = "fake"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SERVER_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
DEFAULT_PLAYER_APPS = ("chrome.exe", "firefox.exe")
DEFAULT_LOG_LEVEL = "INFO"

MIN_TOKEN_LENGTH = 32
```

**Every default is a named constant at the top**, so all of the app's
assumptions are visible in one screen, and tests and messages can refer to them
instead of repeating values.

**The defaults are chosen to be safe, not convenient:**

- `DEFAULT_CONTROLLER = "fake"` — a fresh checkout on any OS starts without
  Windows libraries.
- `DEFAULT_HOST = "127.0.0.1"` — a fresh server is reachable **only from the
  same PC**. Opening it to the network (`RMC_HOST=0.0.0.0`) is a deliberate
  act. This principle is called **secure by default**: the unconfigured state
  is the safe one, and exposure requires a decision.
- **No default token.** A default secret would be the same for every install,
  published in this public repository — so effectively no secret at all. (Many
  real-world breaches started with devices shipping a default password.)

**`DEFAULT_SERVER_URL` is built from the other two constants** with an
f-string, so changing the default port can't leave the client pointing at the
old one.

**`MIN_TOKEN_LENGTH = 32`**: the comment explains the number.
`secrets.token_urlsafe(32)` produces 43 characters, so real generated tokens
always pass. The limit exists to reject hand-typed tokens like `music123`,
which could be guessed.

---

## Block 4 — `ConfigError`

```python
class ConfigError(Exception):
    """A configuration problem the user must fix; shown as a one-line message."""
```

A custom exception type for one category of failure: *the user's settings are
wrong*. `server.py` and `cli.py` catch **exactly this type** and print its
message as one line, instead of a Python traceback:

```
music-server: configuration error: RMC_PORT='eighty' is not a number
```

A traceback is the right output for a **bug** (the developer needs every
detail). For a **user mistake** it's noise that hides the one useful sentence.
Having a dedicated exception type is how the program tells the two apart — the
same idea as `NoMediaSessionError` vs unexpected errors on page 03.

---

## Block 5 — the settings objects

```python
@dataclass(frozen=True)
class ServerSettings:
    controller: str
    host: str
    port: int
    player_apps: tuple[str, ...]
    token: str
    log_level: str
    log_file: Path | None

@dataclass(frozen=True)
class ClientSettings:
    server_url: str
    token: str | None
```

Raw configuration is a bag of strings: `"8000"`, `" Chrome.exe, msedge.exe "`,
`""`. These classes are the **output** after cleaning and checking: `port` is
already an `int` in range, `player_apps` is already a tuple of lowercase names,
`log_file` is a `Path` or `None`.

This is the pattern called **parse, don't validate** (from an essay by Alexis
King): instead of passing raw strings around and checking them wherever
they're used, convert them **once, at the boundary**, into types that can only
hold valid values. Code that receives a `ServerSettings` never has to wonder
whether `port` might be `"eighty"`.

**`frozen=True`** (page 01): settings are read once at startup and must not
change while the server runs. An accidental `settings.port = 0` somewhere would
raise immediately.

**Two classes, not one:** the server and the CLI need different things, and
the CLI must work on a machine where server-only settings (like a controller)
make no sense. `token` is required for the server but optional for the client
(`str | None`), because the CLI can still give a helpful message without one.

---

## Block 6 — where the config file lives

```python
def default_config_path(environ: Mapping[str, str] = os.environ) -> Path:
    if environ.get("RMC_CONFIG_FILE", "").strip():
        return Path(environ["RMC_CONFIG_FILE"].strip())
    if sys.platform == "win32":
        base = environ.get("APPDATA", "").strip() or Path.home() / "AppData" / "Roaming"
    else:
        base = environ.get("XDG_CONFIG_HOME", "").strip() or Path.home() / ".config"
    return Path(base) / "remote-music-control" / "config.env"
```

**The standard places for per-user settings:**

- **Linux:** the **XDG Base Directory Specification** (from freedesktop.org)
  says user configuration goes in `$XDG_CONFIG_HOME`, which defaults to
  `~/.config`. That's why you find `~/.config/Code`, `~/.config/git` and so on.
  Programs that dump dotfiles directly in your home folder are ignoring it.
- **Windows:** `%APPDATA%` (`C:\Users\<name>\AppData\Roaming`) is the per-user
  application data folder; "Roaming" means it can follow the user between PCs
  on a company network.

Following each platform's convention means the file is where an experienced
user of that system would look, and it's automatically **outside the
repository** — no `.gitignore` rule needed to keep the token out of Git.

**`RMC_CONFIG_FILE` overrides everything** — used by the tests (each test gets
its own temporary file) and handy for running two configurations side by side.

**`x or default`:** `or` returns its left side if that's truthy, otherwise its
right side. Combined with `.strip()`, an unset *or empty or blank* variable
falls back to the default. This matters: `Path("")` means "the current
folder", so an accidental `RMC_CONFIG_FILE=` would otherwise make the program
try to read a folder as a file. (That exact bug was found and fixed while
writing this page; the tests `test_empty_path_variables_count_as_unset` now
cover it.)

**`sys.platform == "win32"`** is `"win32"` on 64-bit Windows too — the name is
historical.

**`default_log_path`** (just below it) puts `server.log` in the same folder, so
everything the app writes for a user is in one place.

---

## Block 7 — reading the file

```python
def read_config_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"{path}, line {line_number}: expected KEY=VALUE, got {raw_line!r}")
        values[key.strip()] = value.strip()
    return values
```

**The format** is the common **dotenv** style — `KEY=VALUE` lines with `#`
comments — used by Docker Compose, many frameworks and the `python-dotenv`
package.

**Why write a parser instead of using `python-dotenv`:** the file holds a
handful of plain values. The whole parser is about 15 lines anyone can read;
the dependency would bring quoting rules, variable expansion (`${OTHER}`) and
multi-line values that this app doesn't need — and each extra feature is
something a user could trip over (a `$` in a token being expanded, for
instance). The project rule: *if the standard library is good enough, use it.*

Line by line:

- **Missing file → empty dict.** Not an error: the CLI can run on environment
  variables alone, and the server's own message ("no RMC_TOKEN configured. Run
  `music-server init`…") is more useful than "file not found".
- **`encoding="utf-8-sig"`** accepts an optional **BOM** (byte order mark), an
  invisible character that Windows PowerShell 5 and older Notepad put at the
  start of "UTF-8" files. With plain `"utf-8"` the first key would secretly be
  `"\ufeffRMC_TOKEN"`. This was a real bug in Phase 5: the server rejected its
  own config file after PowerShell had edited it.
- **`enumerate(..., start=1)`** yields `(number, line)` pairs counting from 1,
  like a text editor, so error messages point at the right line.
- **`line.partition("=")`** splits at the **first** `=` only and always returns
  three parts: `("RMC_TOKEN", "=", "abc=def")`. So values may contain `=` —
  base64-style tokens often do. If there's no `=`, the separator is `""`.
  (`split("=")` would break such values into pieces.)
- **`{raw_line!r}`** — the `!r` inserts the line's `repr()`, with quotes and
  visible escapes, so an invisible problem like a trailing tab shows up in the
  error message.
- **Keys and values are stripped**, so `RMC_PORT = 9000` works.

**What it deliberately doesn't do:** no quotes (`RMC_HOST="0.0.0.0"` would
keep the quotes in the value), no warnings about unknown keys. A typo like
`RMC_TOKNE=…` is silently ignored — though for the token, the server then
reports it's missing, which leads you to the typo. Warning about unknown
`RMC_` keys would be a reasonable improvement.

---

## Block 8 — merging the sources

```python
def load_values(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    set_in_environment = {key: value for key, value in environ.items() if value.strip()}
    return {**read_config_file(default_config_path(environ)), **set_in_environment}
```

This short function implements the precedence rule.

**`{**a, **b}`** builds a new dictionary from both; when a key appears in both,
**the later one wins**. With the file first and the environment second,
environment variables override the file — factor III's "environment first".

**The dictionary comprehension** `{k: v for k, v in ... if v.strip()}` keeps
only variables with a non-blank value. Why: a line like `export RMC_TOKEN=`
left in a shell profile would otherwise override the real token from the file
with an empty string, and the server would claim no token exists while the file
clearly has one. Treating empty as unset makes that mistake harmless. (Found in
Phase 5 when a test command set `RMC_SERVER_URL=` to "clear" it.)

**A detail:** the result contains *all* environment variables (`PATH`, `HOME`…),
not just `RMC_` ones. The loaders below only ever ask for `RMC_` keys, so the
extra entries are harmless, and filtering would add code for nothing.

**On Windows**, `os.environ` keys are case-insensitive (`rmc_port` and
`RMC_PORT` are the same variable). In the config file they're case-sensitive:
write them in capitals.

---

## Block 9 — creating the file safely

```python
def create_config_file(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
```

Used by `music-server init`. It could have been `path.write_text(...)`. The
lower-level `os.open` is there for two security properties:

**1. Never overwrite (`O_EXCL`).** The flags are combined with `|` (bitwise
OR):

- `O_WRONLY` — open for writing;
- `O_CREAT` — create the file if it doesn't exist;
- `O_EXCL` — with `O_CREAT`: **fail if it already exists**.

Running `init` twice therefore can't replace a working token with a new one,
which would silently disconnect every paired phone. `server.py` checks for the
file first to give a friendly message; `O_EXCL` guarantees it even if two
commands race.

The check and the creation happen as **one atomic operation** in the operating
system. Checking with `path.exists()` and then writing would leave a gap where
another process could create the file in between — a class of bug called
**TOCTOU** (*time of check to time of use*).

**2. Private from the first byte (`0o600`).** `0o600` is an **octal** number
encoding Unix permissions:

```
 6        0        0
 owner    group    others
 rw-      ---      ---
```

The permissions are set **as the file is created**. Writing first and then
calling `chmod` would leave a brief moment where another user on the machine
could open the fresh token file. (The process's `umask` can only remove
permissions, so the result is never *more* open than 600.)

On **Windows** this mode is ignored except for read-only; privacy comes from
the default permissions of `%APPDATA%`, which allow the user, administrators
and the SYSTEM account.

**`os.fdopen(fd, "w", encoding="utf-8")`** wraps the raw file descriptor
(an integer handle from the operating system) in a normal Python file object,
and **`with`** closes it even if writing fails — a **context manager**.

**`"\n".join(lines) + "\n"`** writes one line per item and ends with a newline,
as text files conventionally do.

---

## Block 10 — generating the token

```python
def generate_token() -> str:
    return secrets.token_urlsafe(32)
```

**`secrets` vs `random`:** Python's `random` module is a
**pseudo-random number generator** designed for simulations and games. It is
fast and repeatable — and, given enough outputs, **predictable**. `secrets`
uses the operating system's **cryptographically secure** random source
(`/dev/urandom` on Linux, `BCryptGenRandom` on Windows), designed so that
outputs can't be predicted. Anything used as a password, token or key must come
from `secrets`. Using `random` for tokens is a classic vulnerability.

**`token_urlsafe(32)`** takes **32 random bytes** — 256 bits of **entropy**
(unpredictability) — and encodes them in URL-safe base64 (letters, digits, `-`
and `_`), giving 43 characters. URL-safe matters because the token travels in a
URL fragment (`#token=…`) and a QR code.

**How strong is 256 bits?** A guesser trying a trillion tokens per second would
need far longer than the age of the universe to have a real chance. That's why
the server needs no rate limiting (ADR 0009): guessing is not a realistic
attack. Stealing is — which is what the file permissions, the header, the
no-store pairing page and the log hygiene are about.

---

## Block 11 — loading server settings

```python
def load_server_settings(environ: Mapping[str, str] = os.environ) -> ServerSettings:
    values = load_values(environ)
    config_path = default_config_path(environ)
    ...
```

### The testable default parameter

`environ` defaults to the real `os.environ`, so production code simply calls
`load_server_settings()`. Tests call `load_server_settings({"RMC_TOKEN": ...,
"RMC_CONFIG_FILE": ...})` with a plain dict. No test ever modifies the real
environment of the process, so tests can't affect each other or the developer's
shell. This is **dependency injection** once more, in its lightest form: a
default argument.

### Each setting: read, normalize, validate

**Controller:**

```python
    controller = values.get("RMC_CONTROLLER", DEFAULT_CONTROLLER).strip().lower()
    if controller not in CONTROLLER_CHOICES:
        raise ConfigError(f"RMC_CONTROLLER={controller!r} is not valid; choose one of: {', '.join(CONTROLLER_CHOICES)}")
```

`dict.get(key, default)` returns the default when the key is missing.
**Normalizing** (`strip`, `lower`) before checking means `Windows `, `WINDOWS`
and `windows` all work. The error message **lists the valid choices** — a good
error message tells you how to fix the problem, not only that one exists.

**Port:**

```python
    raw_port = values.get("RMC_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        raise ConfigError(f"RMC_PORT={raw_port!r} is not a number") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"RMC_PORT={port} is outside the valid range 1–65535")
```

Two separate checks with two separate messages: "not a number" and "out of
range" need different fixes. 65535 is the largest TCP port number (16 bits).

**`raise ... from None`** replaces Python's `ValueError` with our `ConfigError`
and **suppresses the chained traceback** ("During handling of the above
exception, another exception occurred…"). The low-level error adds nothing the
message doesn't already say. (Without `from None`, Python keeps the original
exception attached as context; with `from error`, it would mark it as the
explicit cause — the right choice when the original *is* useful, as in the
Windows adapter's `_send`.)

**Player apps:**

```python
    raw_apps = values.get("RMC_PLAYER_APPS", ",".join(DEFAULT_PLAYER_APPS))
    player_apps = tuple(name.strip().lower() for name in raw_apps.split(",") if name.strip())
    if not player_apps:
        raise ConfigError("RMC_PLAYER_APPS must name at least one application, e.g. chrome.exe")
```

Environment variables can only hold text, so lists are written comma-separated.
The **generator expression** inside `tuple(...)` splits, trims, lowercases and
**drops empty items** — so `" Chrome.exe, msedge.exe ,"` (spaces, a trailing
comma) becomes `("chrome.exe", "msedge.exe")`. Being forgiving about harmless
formatting while strict about meaning is sometimes called the **robustness
principle** (*be liberal in what you accept*) — applied here only to whitespace
and case, never to invalid values.

**Token:**

```python
    token = values.get("RMC_TOKEN", "").strip()
    if not token:
        raise ConfigError(f"no RMC_TOKEN configured. Run `music-server init` to create {config_path} with a new token.")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(...)
```

The missing-token message names **the exact file path** on this machine and
**the command** that fixes it. This is the error a new user is most likely to
hit first, so it gets the most helpful message. The server refuses to start
without a token at all — there is no "open" mode (ADR 0009).

**Log level and log file:**

```python
    log_level = values.get("RMC_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
    ...
    raw_log_file = values.get("RMC_LOG_FILE", "").strip()
```

Log levels are normalized to upper case, because that's how Python's `logging`
names them. The log file is optional: empty means "decide automatically"
(stderr, or `server.log` when there's no console — see page 06).

**`RMC_HOST` is not validated here.** An invalid address makes uvicorn fail at
startup with its own clear error, and duplicating network-address validation
would add code without adding clarity.

### Why validate everything at startup

All checks run before the server starts. A typo in the port is reported in the
first second, in one line — not an hour later as a mysterious failure. This is
**fail fast** (page 02) applied to configuration: a program with invalid
settings should refuse to run rather than run in a half-working state.

---

## Block 12 — loading client settings

```python
def load_client_settings(environ: Mapping[str, str] = os.environ) -> ClientSettings:
    values = load_values(environ)
    return ClientSettings(
        server_url=values.get("RMC_SERVER_URL", DEFAULT_SERVER_URL).strip(),
        token=values.get("RMC_TOKEN", "").strip() or None,
    )
```

Much simpler, on purpose: the client validates nothing up front. If the URL is
wrong, the HTTP library reports it; if the token is missing or wrong, the
server answers 401 and `cli.py` turns that into a message naming the config
file (page 05). The expression `"".strip() or None` converts "no token" into
`None`, matching the `str | None` type.

**The same file format and the same token name** on both machines: the server's
config file and the client's config file both say `RMC_TOKEN=…`, so copying the
token is copying one line.

---

## How the pieces are used

| Caller | Uses | For |
|---|---|---|
| `server.py` `main()` | `load_server_settings()`, `ConfigError` | Start with validated settings, or print one-line errors |
| `server.py` `init()` | `default_config_path`, `create_config_file`, `generate_token` | Create the first config file |
| `server.py` logging | `default_log_path` | Where to log without a console |
| `cli.py` | `load_client_settings`, `default_config_path`, `ConfigError` | Server URL, token, error messages naming the file |
| `install-autostart.ps1` | (reads `config.env` itself) | Warns if `RMC_CONTROLLER`/`RMC_HOST` aren't set; finds the port |
| Tests | every function, with dicts and temp files | Precedence, parsing, BOM, permissions, errors |

## Glossary

| Term | Meaning here |
|---|---|
| Twelve-factor app / factor III | Methodology for deployable services; config comes from the environment, never the code |
| Deploy | One running installation: Ubuntu PC, studio PC, CI runner |
| Precedence | Which source wins when several set the same value |
| Namespacing | A shared prefix (`RMC_`) to avoid name collisions |
| Secure by default | The unconfigured state is the safe one |
| Parse, don't validate | Convert raw input once into types that can only be valid |
| XDG Base Directory Specification | Linux standard for where per-user files go (`~/.config`) |
| `%APPDATA%` | Windows per-user application data folder |
| dotenv format | `KEY=VALUE` lines with `#` comments |
| BOM | Invisible byte order mark some Windows tools put at the start of UTF-8 files |
| `str.partition` | Split at the first separator into exactly three parts |
| Atomic operation / TOCTOU | One indivisible step / the bug when "check" and "use" are separate steps |
| `O_EXCL` | Create-only flag: fail if the file exists |
| Unix permissions / octal `0o600` | Owner read-write, nobody else |
| File descriptor | The operating system's integer handle for an open file |
| Context manager (`with`) | Guarantees cleanup, like closing a file |
| CSPRNG | Cryptographically secure random number generator (`secrets`) |
| Entropy | Unpredictability, measured in bits |
| Base64 / URL-safe | Encoding bytes as text; the URL-safe variant uses `-` and `_` |
| `raise ... from None` | Replace an exception without the chained traceback |
| Robustness principle | Accept harmless variation in input (spaces, case) |
| Fail fast | Refuse to start with invalid settings |

## Check your understanding

1. You run `RMC_PORT=9100 uv run music-server` and the config file says
   `RMC_PORT=9000`. Which port is used, and which line of code decides it?
2. Why is there no default token, when there are defaults for everything else?
3. What could go wrong if `create_config_file` used `path.exists()` followed by
   `path.write_text(...)` and then `os.chmod(path, 0o600)`? Name both problems.
4. A token generated with `random.choice` over letters and digits, 43
   characters long, passes `MIN_TOKEN_LENGTH`. Why is it still worse than
   `secrets.token_urlsafe(32)`?
5. Why does `read_config_file` use `partition("=")` and not `split("=")`? Give a
   value that would break with `split`.
6. Someone writes `RMC_HOST="0.0.0.0"` (with quotes) in `config.env`. What
   happens, and where would they see the error?
7. `load_server_settings` takes `environ` as a parameter. What would the tests
   have to do if it read `os.environ` directly, and what could go wrong?
8. Why do the server and the client have separate settings classes?
