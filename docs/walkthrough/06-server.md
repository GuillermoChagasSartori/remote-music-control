# 06 — `server.py`: the composition root

**File:** [`src/remote_music_control/server.py`](../../src/remote_music_control/server.py) · ~260 lines
**Depends on:** uvicorn, and almost every module of the project: `config`, `api`, `pairing`, the port, and (lazily) the adapters
**Used by:** the `music-server` command, and the logon task (`pythonw.exe -m remote_music_control.server`)

## Where this file sits

Every page so far described a piece that **doesn't know** about the others:
the port knows no adapter, the API knows no adapter, the adapters know no HTTP,
configuration knows nothing about any of them. Somewhere, though, the program
has to become concrete — *read these settings, build that adapter, give it to
this API, start listening on that port.* This file is that place.

```
                        server.py
          ┌─────────────────┼──────────────────┬──────────────┐
          ▼                 ▼                  ▼              ▼
   config.py         adapters/fake.py     api.py         uvicorn
 (load settings)   or adapters/windows.py  (create_app)   (serve it)
                   (build_controller)
```

It also owns everything about **running as a process**: where logs go, what
happens at startup when something's wrong, which exit code the process ends
with, and the `init` setup command.

### The technique: composition root

A **composition root** (term from Mark Seemann's work on dependency injection)
is the single place in an application where the object graph is assembled:
concrete classes are chosen and connected, as close as possible to the
program's entry point. Everywhere else, code receives its collaborators
instead of creating them.

The payoff is the one promised on page 01. Switching from the fake to the real
player is **one `if` in this file** — the API, CLI, web page and tests don't
change. And because assembly happens only here, the rest of the code can be
built from pieces that are each testable alone.

**The alternative** is to let modules create what they need
(`api.py` doing `controller = WindowsMediaController()` at import time). That's
called the **Service Locator** or simply hard-coded dependencies, and it's
exactly what would have made the API impossible to run on Linux.

---

## Block 1 — imports and the named logger

```python
import argparse
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from .api import create_app
from .config import (...)
from .media_controller import MediaController
from .pairing import lan_ip_address

logger = logging.getLogger("remote_music_control.server")
```

**Import order** follows the common convention (enforced by tools like
`isort`): standard library, blank line, third-party, blank line, the project's
own modules — each group alphabetical.

**What's *not* imported at the top:** the adapters. See Block 2.

**`logging.getLogger(name)`** returns the logger with that name, creating it
the first time. Loggers form a hierarchy by dotted names:
`remote_music_control.server` and `remote_music_control.api` are both children
of `remote_music_control`, and all messages flow up to the **root logger**,
where the handler configured in Block 4 writes them out. Each line in the log
shows which module wrote it.

**Why a fixed name instead of the usual `logging.getLogger(__name__)`:** the
logon task starts the server with `python -m remote_music_control.server`, and
a module run with `-m` gets `__name__ == "__main__"`. Log lines would then say
`__main__: starting with ...`, which tells a reader nothing. (This was visible
in the server log in Phase 5.)

---

## Block 2 — `build_controller`: choosing the adapter

```python
def build_controller(settings: ServerSettings) -> MediaController:
    if settings.controller == "fake":
        from .adapters.fake import FakeMediaController

        return FakeMediaController()
    if settings.controller == "windows":
        try:
            from .adapters.windows import WindowsMediaController
        except ImportError as error:
            raise ConfigError(f"RMC_CONTROLLER=windows can't be used here: {error}") from error

        return WindowsMediaController(player_apps=settings.player_apps)
    raise ConfigError(f"unknown controller {settings.controller!r}")
```

**A factory function:** code that decides which concrete class to create and
returns it as the abstract type (`-> MediaController`). Callers get "a media
controller" and never learn which one.

### Lazy imports

Imports normally sit at the top of a file. Here each adapter is imported
**inside its branch** — a **lazy** (or deferred) import. The reason is the
two-machine constraint from the plan: `adapters/windows.py` imports `winrt` and
`pycaw`, which **don't exist on Linux**. A top-level import would crash the
server on Ubuntu before it ever read `RMC_CONTROLLER=fake`. Importing only the
chosen adapter means each machine only needs the packages for the adapter it
actually uses.

It also documents a dependency direction: **this is the only file in the
package that imports an adapter.**

### Turning an import failure into a configuration error

If you set `RMC_CONTROLLER=windows` on Linux, the adapter module refuses to
load (its first lines raise `ImportError("the Windows media adapter can only be
used on Windows")`). That isn't a bug in the program — it's a setting that
doesn't fit this machine — so it's re-raised as `ConfigError`, which `main()`
reports as one clear line:

```
configuration error: RMC_CONTROLLER=windows can't be used here: the Windows media adapter can only be used on Windows
```

**`from error`** keeps the original `ImportError` attached as the **cause**
(visible if someone debugs it), unlike `from None` on page 04, which hides it.
Here the original message is useful, so it's also included in the text.

**Why the `try` wraps only the import line:** an earlier version caught
`ImportError` around the entire server run, uvicorn included. Any import
problem deep inside a library would then have been reported as a
"configuration error", sending you to check your settings for a problem that
wasn't there. Catching an exception **as close as possible to where it can
legitimately happen** keeps the diagnosis accurate. This was corrected while
writing this page.

**The final `raise`** can't be reached through normal use — `config.py`
already rejects unknown controller names — but it keeps the function correct
even if called with hand-made settings, as the tests do.

---

## Block 3 — the rotating log file

```python
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
LOG_FILE_MAX_BYTES = 1_000_000
LOG_FILE_BACKUPS = 3
```

**The format** produces lines like:

```
2026-09-13 11:03:55,862 INFO    remote_music_control.api: POST /api/pause -> 204 in 115 ms (from 192.168.1.20)
```

`%(name)s` placeholders are filled by `logging` for each record. `-7s` pads
the level to 7 characters, so messages line up whether the level is `INFO` or
`WARNING`. `1_000_000` — underscores in number literals are just for
readability.

### Why rotate at all

A **log rotation** policy stops a log from growing forever: when `server.log`
reaches 1 MB, it becomes `server.log.1` (the previous `.1` becomes `.2`, and so
on), and a fresh `server.log` starts. With 3 backups, the log never uses more
than about 4 MB. A server that runs for months at logon, unattended, must not
be able to fill the disk.

### `LockTolerantRotatingFileHandler`

```python
class LockTolerantRotatingFileHandler(RotatingFileHandler):
    def __init__(self, filename: Path, max_bytes: int, backup_count: int) -> None:
        if backup_count < 1:
            raise ValueError("backup_count must be at least 1")
        super().__init__(filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        self._next_attempt_size = 0

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if not super().shouldRollover(record):
            return False
        return self.stream.tell() >= self._next_attempt_size

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None

        in_progress = self.baseFilename + ".rotating"
        try:
            os.replace(self.baseFilename, in_progress)
        except OSError:
            self.stream = self._open()
            self._next_attempt_size = self.stream.tell() + self.maxBytes
            return

        for number in range(self.backupCount - 1, 0, -1):
            older = f"{self.baseFilename}.{number}"
            if os.path.exists(older):
                os.replace(older, f"{self.baseFilename}.{number + 1}")
        os.replace(in_progress, f"{self.baseFilename}.1")

        self._next_attempt_size = 0
        self.stream = self._open()
```

This class exists because of a bug found **while writing this page**, and the
story is a good lesson in why you test the things your documentation
recommends.

**The problem.** The README suggests following the log live on Windows with
`Get-Content ... -Wait`. On Windows, a file that another program has open
**can't be renamed**. So when the log reached its size limit, rotation failed.
Python's standard `RotatingFileHandler` handles that badly:

1. It first shifts the backups (`.2` → `.3`, deleting the old `.3`; `.1` →
   `.2`), and only *then* tries to rename `server.log` — which fails.
2. The failure is caught by `logging`, and **the record being written is
   dropped**.
3. The file is still over the limit, so the *next* record tries again: another
   backup destroyed, another record dropped.

Measured on the studio PC with a small size limit: **286 of 400 lines lost, and
two of the three backups deleted**, while `Get-Content -Wait` was running.
Antivirus scanners briefly locking the file could cause the same thing.

**The fix changes the order of operations:**

1. **Move the current log aside first** (`server.log` → `server.log.rotating`).
   This is the step that fails when the file is locked — and it fails *before
   anything has been changed*.
2. **If it fails:** reopen the same file and keep writing. No record is lost,
   no backup touched. Remember to try again only after the file has grown by
   another `maxBytes` (`_next_attempt_size`), instead of retrying — and failing
   — on every single line.
3. **If it succeeds:** shift the backups, then file the moved log as `.1`, and
   start a fresh `server.log`.

After the fix, the same test on Windows: **400 of 400 lines kept, 0 errors, all
backups intact.** Unit tests simulate the lock on Linux by replacing
`os.replace` with a version that raises `PermissionError`.

**Techniques and terms in this class:**

- **Subclassing to change behaviour:** it inherits everything from
  `RotatingFileHandler` and **overrides** only two methods. `super()` calls the
  parent's version where the original behaviour is still wanted.
- **Ordering operations so failure leaves a consistent state** — do the step
  most likely to fail before any irreversible step. The same idea underlies
  database transactions and "write to a temporary file, then rename".
- **`os.replace`** renames and overwrites the destination if it exists, and
  behaves the same on Windows and Linux (plain `os.rename` refuses to overwrite
  on Windows).
- **Backoff:** after a failure, wait before retrying (here measured in bytes
  written rather than seconds).
- **Guard in `__init__`:** the class only makes sense with at least one backup,
  so it refuses to be built otherwise — fail fast (page 02).
- **`range(self.backupCount - 1, 0, -1)`** counts *down* (2, 1), so `.2` moves
  to `.3` before `.1` moves to `.2` and nothing is overwritten too early.

**Method names like `shouldRollover` and `doRollover`** are in camelCase
because they override the standard library's names; Python's `logging` module
predates PEP 8's naming style.

---

## Block 4 — deciding where logs go

```python
def log_destination(configured_file: Path | None, stderr) -> Path | None:
    if configured_file is not None:
        return configured_file
    if stderr is None:
        return default_log_path()
    return None


def configure_logging(level: str, log_file: Path | None) -> None:
    destination = log_destination(log_file, sys.stderr)
    if destination is None:
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handler = LockTolerantRotatingFileHandler(
            destination, max_bytes=LOG_FILE_MAX_BYTES, backup_count=LOG_FILE_BACKUPS
        )
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=[handler])
```

### Three situations, one decision

| How the server runs | `sys.stderr` | Logs go to |
|---|---|---|
| `uv run music-server` in a terminal | the terminal | stderr (the terminal) |
| Logon task, `pythonw.exe` (no console) | **`None`** | `server.log` next to the config file |
| Either, with `RMC_LOG_FILE` set | — | that file |

**`pythonw.exe`** is the Windows Python that runs without opening a console
window (Phase 7: otherwise a black window would sit on the studio desktop).
Without a console there's nowhere for output to go, so Python sets
`sys.stdout` and `sys.stderr` to `None`. Anything that writes to them —
a `print`, a `StreamHandler` — would crash. Hence the automatic file.

**Why the decision is a separate function:** `log_destination` is pure (page
05): it takes the stderr object as a *parameter* instead of reading `sys.stderr`
itself. Tests pass `None` to simulate `pythonw` on Linux, without actually
changing the process's stderr. `configure_logging` then does the side effects.

**Twelve-factor, factor XI ("Logs")** says an app should write logs to its
output stream and let the environment route them. That's the terminal case.
When there *is* no output stream, writing a rotated file is the practical
substitute — the same compromise many Windows services make.

### Details

- **`sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")`** —
  when the terminal output is redirected on Windows, Python would use `cp1252`
  and crash on a track title like "花の専門店" (a real Phase 4 crash; the CLI's
  version of the same fix is on page 05). `backslashreplace` turns anything
  still unencodable into `花`-style escapes rather than failing.
- **`mkdir(parents=True, exist_ok=True)`** creates the folder and any missing
  parent folders, and does nothing if it already exists.
- **`handler: logging.Handler = ...`** — a type annotation on a variable, so
  the two branches (a stream handler, a file handler) are understood as the
  same kind of thing.
- **`logging.basicConfig(..., handlers=[handler])`** attaches the handler and
  format to the root logger, which receives messages from every module's
  logger. It's called once, at startup. (It does nothing if the root logger
  already has handlers — one reason the tests replace this function rather than
  call it.)

---

## Block 5 — errors before logging exists

```python
def report_startup_error(message: str) -> None:
    line = f"music-server: {message}"
    if sys.stderr is not None:
        print(line, file=sys.stderr)
        return
    path = default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(line + "\n")
```

A **bootstrapping problem**: logging is configured from the settings (level,
log file). If *loading the settings* fails — a typo in `config.env` — there's no
logging yet to report it with.

On a console, print. Under `pythonw`, append the message to the default log
file (`"a"` = append mode, never overwrite). Without this, a broken config file
would make the server at logon **fail silently**: no window, no log line,
nothing for you to find. This situation — a background process that dies
without a trace — is one of the most frustrating to debug, so it's worth these
few lines. A test simulates it by setting `sys.stderr` to `None`.

---

## Block 6 — `run`: wiring and starting

```python
def run(settings: ServerSettings) -> None:
    controller = build_controller(settings)
    app = create_app(controller, token=settings.token)
    logger.info("starting with %s on %s:%d", type(controller).__name__, settings.host, settings.port)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )
```

These first two lines **are** the composition: settings → adapter → app.

**`uvicorn.run(app, ...)`** starts the **ASGI server** (page 03): it opens the
socket, runs the event loop, and hands each HTTP request to the FastAPI app. It
**blocks** — it returns only when the server stops (Ctrl+C, or the process is
ended).

**`host`** is the address to listen on: `127.0.0.1` means only this PC can
connect; `0.0.0.0` means every network interface, i.e. the LAN (with the
firewall rule and token as protection — ADR 0009).

**`log_config=None`** stops uvicorn from installing its own logging setup,
which would bypass ours. Its messages then flow to the root logger and appear
in the same file, in the same format, with the name `uvicorn.error` (a
historical name — it carries uvicorn's general messages, not only errors).

**`access_log=False`** disables uvicorn's one-line-per-request log. The web
page polls every second, which would mean about 86,000 lines a day; `api.py`
logs only the requests that change something (page 03, Block 12).

**The startup log line** records which adapter and address were chosen — the
first thing to check when "it doesn't work".

**If the port is taken** (e.g. starting `music-server` by hand while the logon
task's server is running), uvicorn logs the reason — verified on the studio PC:

```
ERROR   uvicorn.error: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000): ...
```

and ends the process with exit code 3 via `SystemExit`. `SystemExit` is not an
`Exception` subclass, so `main()`'s safety net (Block 8) lets it through
untouched — uvicorn has already logged a clearer message than we could.

---

## Block 7 — `init`: first-time setup

```python
def init() -> int:
    path = default_config_path()
    if path.exists():
        print(f"music-server: {path} already exists; leaving it unchanged.", file=sys.stderr)
        return 1
    token = generate_token()
    create_config_file(path, [
        "# Remote Music Control configuration. Keep this file private.",
        ...
        f"RMC_TOKEN={token}",
        ...
        "# RMC_CONTROLLER=windows",
        "# RMC_HOST=0.0.0.0",
        ...
    ])
    print(f"Created {path}")
    ...
```

**A self-documenting config file:** besides the token, `init` writes every
other setting **commented out**, with its default and a short explanation.
Opening the file shows what can be configured, without looking up the README.
Uncommenting two lines turns it into the studio PC's configuration.

**Never overwrites:** it checks first to print a friendly message; underneath,
`create_config_file` uses `O_EXCL`, so even a race can't replace an existing
token (page 04, Block 9). Replacing the token would silently disconnect every
paired phone.

**What it prints:** the token, and two pairing links:

- by name (`<computer>.local`) — survives IP changes, but Android browsers
  can't resolve it (found with your phone in Phase 5);
- by IP — works everywhere, but breaks if the router assigns a new address.

…and a pointer to `http://127.0.0.1:8000/pair` for QR codes later. The links
use `DEFAULT_PORT`, since at this moment no port has been configured yet.

This is the one moment the token is shown on a screen by design — at setup,
on the server PC, to its owner.

---

## Block 8 — `main`: startup sequence and exit codes

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="music-server", description="Remote Music Control server.")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser("init", help="create the config file with a new token")
    args = parser.parse_args(argv)

    if args.command == "init":
        return init()

    try:
        settings = load_server_settings()
    except ConfigError as error:
        report_startup_error(f"configuration error: {error}")
        return 1

    configure_logging(settings.log_level, settings.log_file)
    try:
        run(settings)
    except ConfigError as error:
        logger.error("configuration error: %s", error)
        return 1
    except Exception:
        logger.exception("server stopped because of an unexpected error")
        return 1
    return 0
```

### The startup sequence

The order is deliberate — each step makes the next one's errors reportable:

1. **Parse arguments.** Subparsers here are *optional* (no `required=True`):
   plain `music-server` runs the server; `music-server init` sets up. With one
   subcommand, a simple `if` is clearer than a dispatch table (compare page 05,
   where twelve commands earned one).
2. **Load settings.** Can fail with `ConfigError` → reported *without* logging
   (Block 5), since logging depends on the settings.
3. **Configure logging.** From now on, everything goes to the right place.
4. **Build and run.** `ConfigError` (e.g. the Windows adapter on Linux) is
   logged as one line; anything else is logged with its traceback.

### Exit codes

| Outcome | Exit code | Who decides |
|---|---|---|
| Stopped normally (Ctrl+C) | 0 | `return 0` |
| Configuration error | 1 | `return 1` |
| Unexpected error | 1 | `return 1` |
| Port already in use | 3 | uvicorn, via `SystemExit` |
| `init` when the file exists | 1 | `init()` |

A process ends with an exit code so whoever started it — a shell, a script, a
service manager — can tell success from failure. **Non-zero means "didn't do
its job."**

**What the exit code does *not* do here** — and the comment in the code says
so: it doesn't make Task Scheduler restart the server. Phase 7 tested that
directly: Task Scheduler's "restart on failure" only reacts to a task that
fails to *launch*. The server is restarted by the **watchdog trigger** (every
minute, ADR 0011), whatever the exit code. An older comment here claimed the
opposite and was corrected while writing this page — a reminder that comments
must be updated when the facts they state are disproven.

### The safety net

`except Exception` catches anything unforeseen while the server runs, so the
crash lands in the log **with its full traceback** (`logger.exception`),
instead of vanishing — under `pythonw` there's no console where Python's
default traceback would appear. `KeyboardInterrupt` and `SystemExit` aren't
`Exception` subclasses, so Ctrl+C and uvicorn's own exits pass through.

**Settings are loaded inside `main()`, not at import time.** Importing
`remote_music_control.server` (as the tests do) has no side effects: nothing
reads files, nothing listens on a port, until `main()` runs.

---

## How the process starts, end to end

```
Windows logon
  └─ Task Scheduler: "Remote Music Control" (logon trigger, or watchdog every minute)
       └─ .venv\Scripts\pythonw.exe -m remote_music_control.server
            └─ server.main()
                 ├─ load_server_settings()        ← %APPDATA%\remote-music-control\config.env
                 ├─ configure_logging()           ← no console → server.log (rotating)
                 └─ run()
                      ├─ build_controller()       ← RMC_CONTROLLER=windows → WindowsMediaController
                      ├─ create_app()             ← FastAPI app with the token
                      └─ uvicorn.run()            ← listens on 0.0.0.0:8000 until the process ends
```

(The `.venv` `pythonw.exe` is a small launcher that starts the real interpreter
as a child process — which is why two `pythonw.exe` processes appear in Task
Manager.)

## How it's tested

| Test | Checks |
|---|---|
| `test_build_controller_returns_the_fake`, `..._windows_adapter_elsewhere_is_a_configuration_error`, `test_unknown_controller_is_a_configuration_error` | Adapter selection and its errors |
| `test_run_wires_settings_into_the_app_and_uvicorn` | `uvicorn.run` replaced by a recorder: correct host, port, `log_config=None`, `access_log=False` |
| `test_main_starts_the_server_when_configured`, `test_server_without_a_token_exits_with_a_one_line_message` | Startup sequence and exit codes |
| `test_unexpected_crash_exits_with_failure...` | Safety net logs the error and returns 1 |
| `test_logs_go_to_...` (3 tests) | `log_destination` for console, configured file, no console |
| `test_startup_error_without_a_console_is_written_to_the_log_file` | Block 5 with `sys.stderr = None` |
| `test_log_rotates_into_numbered_backups`, `test_locked_log_loses_no_lines_and_keeps_its_backups`, `test_rotation_resumes_once_the_lock_is_released` | The lock-tolerant handler, with locking simulated |
| `test_init_...` (2 tests) | Config file created with a token and links; never replaced |

Not unit-tested: `configure_logging` itself (it changes process-wide logging
state) — checked instead by running the real server on both machines.

## Glossary

| Term | Meaning here |
|---|---|
| Composition root | The single place where concrete classes are chosen and connected |
| Service locator / hard-coded dependencies | The alternative: code fetching or creating its own dependencies |
| Factory function | Code that decides which concrete class to create |
| Lazy (deferred) import | Importing inside a function, only when needed |
| Exception cause (`raise ... from error`) | Keeping the original exception attached to a new one |
| Logger hierarchy / root logger | Dotted logger names; messages flow up to the root's handlers |
| Log rotation | Replacing a full log with a fresh one, keeping a few old ones |
| Overriding / `super()` | Replacing a parent class's method / calling the parent's version |
| Consistent state on failure | Ordering steps so a failure leaves nothing half-done |
| Backoff | Waiting before retrying something that failed |
| `pythonw.exe` | Windows Python without a console; `sys.stdout`/`sys.stderr` are `None` |
| Twelve-factor factor XI | Logs as an output stream routed by the environment |
| Bootstrapping problem | Needing a facility (logging) to report failures in setting it up |
| ASGI server / uvicorn | The process that owns the socket and runs the app |
| Blocking call | A call that doesn't return until its work ends |
| Exit code | 0 success, non-zero failure, read by whatever started the process |
| Self-documenting config | A generated config file that lists every option, commented |

## Check your understanding

1. Suppose `from .adapters.windows import WindowsMediaController` were moved to
   the top of `server.py`. What would happen on Ubuntu, and when?
2. Why is the logger named `"remote_music_control.server"` rather than
   `__name__`? What would the log show otherwise?
3. The server is started by the logon task and `config.env` has a typo. Walk
   through `main()`: where does the error message end up, and why can't it use
   the normal logging setup?
4. In `LockTolerantRotatingFileHandler.doRollover`, why must the rename of
   `server.log` happen *before* the backups are shifted? What did the standard
   handler lose when it did it the other way round?
5. Why does the handler wait until the file has grown by another `maxBytes`
   before retrying, instead of retrying on the next line?
6. `uvicorn` exits with code 3 when the port is taken. Why doesn't `main()`'s
   `except Exception` catch that?
7. Does exiting with code 1 cause the logon task to restart the server? What
   does, and how was that established?
8. Why does `run()` pass `log_config=None` and `access_log=False` to uvicorn?
