# 09 — `tests/`: the test suite and CI

**Files:** [`tests/`](../../tests) (171 tests in 9 files) ·
[`pyproject.toml`](../../pyproject.toml) (pytest and coverage settings) ·
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) (continuous integration)
**Depends on:** `pytest`, `pytest-cov` (development only), FastAPI's `TestClient`, and every module of the application
**Run with:** `uv run pytest`

## Where the tests sit

Earlier pages described what the code does. The tests are **executable
statements of what it must keep doing** — checked in seconds, on every change,
on two operating systems. They're also why most of the fixes found while writing
this walkthrough could be made without fear: each fix came with a test, and the
whole suite confirmed nothing else broke.

```
            ┌───────────────────────────────┐
            │ manual: docs/testing-on-      │  real Chrome, real speakers,
            │ windows.md (20 steps)         │  the studio PC
            ├───────────────────────────────┤
            │ integration: tests/integration│  real app over HTTP, real CLI,
            │ (52 tests)                    │  fake player, no network
            ├───────────────────────────────┤
            │ unit: tests/unit              │  one module at a time
            │ (116 tests)                   │
            └───────────────────────────────┘
               + tests/windows (3 smoke tests, Windows only)
```

### The technique: the test pyramid

The **test pyramid** (from Mike Cohn) is a guideline for the *mix* of tests:

- **Many unit tests** at the bottom: small, fast, precise — when one fails, it
  points at one function.
- **Fewer integration tests** in the middle: several parts working together
  (routing + authentication + the fake + error handlers). Slower, broader,
  catch problems in the connections between parts.
- **Few end-to-end or manual tests** at the top: the whole system for real.
  Slow, and when they fail they don't say *where*.

This project's shape follows it, with one twist imposed by the architecture:
the top layer can't be automated, because the real player needs a logged-in
Windows desktop with a browser. Everything below it runs against the **fake
adapter** (page 02) — which is only trustworthy because the fake is itself
tested against the port's contract.

---

## Block 1 — the layout

```
tests/
├── __init__.py
├── conftest.py              shared fixtures (pytest loads it automatically)
├── support.py               shared constants (the test token)
├── unit/
│   ├── test_fake_controller.py        23 tests
│   ├── test_media_controller.py       13
│   ├── test_config.py                 32
│   ├── test_cli_parsing_and_output.py 17
│   ├── test_server.py                 20
│   └── test_pairing.py                11
├── integration/
│   ├── test_api.py                    36
│   └── test_cli.py                    16
└── windows/
    └── test_windows_adapter.py         3
```

**Mirroring the code:** unit test files are named after the module they test,
so finding "the tests for `config.py`" needs no search.

**`__init__.py` in every folder** makes `tests` a Python *package*. That allows
relative imports between test files (`from ..support import TOKEN`) and avoids a
pytest pitfall: two test files with the same name in different folders would
otherwise collide.

**`support.py` vs `conftest.py`:** `conftest.py` is special — pytest finds and
loads it itself, and makes its fixtures available to every test below it. It
shouldn't be imported like a normal module (pytest's documentation advises
against it; it can end up loaded twice). Plain shared values therefore live in
`support.py`. The two test files that imported the token straight from
`conftest.py` were corrected while writing this page.

---

## Block 2 — pytest in one page

```python
def test_next_advances_and_wraps_to_the_first_track(player):
    titles = []
    for _ in range(len(TRACKS)):
        asyncio.run(player.next_track())
        titles.append(now_playing(player).title)
    assert titles == ["Second", "Third", "First"]
```

- **Discovery by name:** pytest collects files named `test_*.py` and functions
  named `test_*`. No registration.
- **Plain `assert`:** pytest rewrites assert statements when it loads test
  files, so a failure shows both values and how they differ:

  ```
  E   assert ['Second', 'First', 'Third'] == ['Second', 'Third', 'First']
  E     At index 1 diff: 'First' != 'Third'
  ```

  The alternative style, `unittest` (in the standard library), needs
  `self.assertEqual(a, b)` methods inside classes. pytest can run those too, but
  plain functions and `assert` are shorter and are today's common Python style.
- **Running part of the suite:**

  ```bash
  uv run pytest tests/unit/test_config.py                 # one file
  uv run pytest tests/unit/test_config.py::test_defaults_when_only_the_token_is_set
  uv run pytest -k volume                                 # names containing "volume"
  uv run pytest -x                                        # stop at the first failure
  ```

- **Async code in tests:** the port is async, but tests call it with
  `asyncio.run(...)`, which runs one coroutine to completion from normal code.
  No plugin (like `pytest-asyncio`) was needed.

### Test names as sentences

`test_locked_log_loses_no_lines_and_keeps_its_backups`,
`test_every_api_route_requires_the_token`,
`test_empty_environment_variable_does_not_hide_the_config_file`.

Each name states **one behaviour** as a sentence. When a test fails in CI, its
name alone says what broke — without opening the file. Long names are fine; they
are read far more often in failure reports than they are typed.

### Arrange, act, assert

Most tests follow three steps, often separated by blank lines:

```python
def test_player_failure_becomes_502_with_the_reason(client, fake, monkeypatch):
    async def refuse():                                          # arrange
        raise MediaControllerError("the player refused 'next'")
    monkeypatch.setattr(fake, "next_track", refuse)

    response = client.post("/api/next")                          # act

    assert response.status_code == 502                           # assert
    assert response.json() == {"detail": "the player refused 'next'"}
```

**Arrange–Act–Assert** (AAA) — prepare the situation, do the one thing being
tested, check the result. It keeps each test about a single action, so it's
clear what failed.

---

## Block 3 — fixtures (`conftest.py`)

```python
@pytest.fixture
def fake() -> FakeMediaController:
    return FakeMediaController()


@pytest.fixture
def app(fake):
    return create_app(fake, token=TOKEN)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}, raise_server_exceptions=False)
```

A **fixture** is a function that prepares something a test needs. A test asks
for it by **naming it as a parameter**: `def test_x(client, fake)`. pytest sees
the names, calls the fixtures, and passes the results in.

**Fixtures can use other fixtures:** `client` needs `app`, which needs `fake`.
In a test that asks for both `client` and `fake`, pytest creates **one** fake
and gives the same object to both — which is how a test can set
`fake.session_open = False` and then see the effect through `client`.

**A fresh set per test** (the default *function scope*): no test can leave the
fake half-muted for the next one. Tests are **independent** — they pass in any
order, alone or together. That property is what makes a failure mean something.

This is **dependency injection** one last time: tests *receive* their
collaborators, exactly like `create_app` receives its controller.

### The fixture that protects your real token

```python
@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("RMC_"):
            monkeypatch.delenv(name)
    config_file = tmp_path / "config.env"
    monkeypatch.setenv("RMC_CONFIG_FILE", str(config_file))
    return config_file
```

**`autouse=True`** applies it to **every test**, requested or not. The reason is
concrete: your Ubuntu PC has a **real config file with the real token** in
`~/.config/remote-music-control/`. Without this fixture, any test that loads
settings would read it — the suite would behave differently on your PC, on the
studio PC, and in CI, and a test failure message could even print your token.

Two built-in fixtures make it safe:

- **`tmp_path`** — a fresh, empty temporary folder for each test, removed later.
- **`monkeypatch`** — temporarily changes things (environment variables,
  attributes of modules and objects) and **undoes every change when the test
  ends**, pass or fail. Without it, a test that sets `RMC_TOKEN` would leak it
  into all following tests.

This practice is called **test isolation**, and the specific danger it avoids —
tests depending on the machine they run on — makes a suite **flaky** or,
worse, silently wrong.

### Fixtures with cleanup: `yield`

```python
@pytest.fixture
def installed_handlers(monkeypatch):
    handlers = []
    monkeypatch.setattr(server.logging, "basicConfig", lambda **options: handlers.extend(options["handlers"]))
    yield handlers
    for handler in handlers:
        handler.close()
```

Code before `yield` is setup; the yielded value goes to the test; code after
`yield` runs when the test finishes — **teardown**. Here it closes the log file
the handler opened, so no file stays locked (which would matter on Windows).

---

## Block 4 — unit tests, and the test doubles they use

Page 02 introduced test doubles. The unit tests use several kinds, created on the
spot with `monkeypatch`:

| Double | Example in the tests | Replaces |
|---|---|---|
| **Fake** | `FakeMediaController` everywhere | The real player |
| **Stub** | `monkeypatch.setattr(pairing, "current_network", lambda: details)` | Reading the real network |
| **Spy / recorder** | `uvicorn.run` replaced by a function that stores its arguments | Starting a real server |
| **Fault injection** | `os.replace` replaced by one that raises `PermissionError` | A locked file on Windows |
| **Fake object** | `SimpleNamespace(client=..., headers=...)` as a request | A full HTTP request |

### 4a. Testing the contract (`test_fake_controller.py`)

```python
@pytest.mark.parametrize(
    "call",
    [lambda p: p.play(), lambda p: p.pause(), ..., lambda p: p.set_muted(True)],
    ids=["play", "pause", ..., "set_muted"],
)
def test_closed_player_rejects_every_command(player, call):
    player.session_open = False
    with pytest.raises(NoMediaSessionError):
        asyncio.run(call(player))
```

**`@pytest.mark.parametrize`** runs one test function once per value — here nine
times, reported as nine separate results (`test_closed_player_rejects_every_command[pause]`).
`ids` gives each case a readable name. It turns a table of cases into tests
without copy-pasting.

**`pytest.raises(X)`** as a `with` block passes only if the code inside raises
`X` — the standard way to test that errors happen.

This test encodes the **port's contract** (page 01, 7d) method by method. If the
fake ever stopped obeying it, every API test built on the fake would be testing
against the wrong behaviour.

### 4b. Tables of cases (`test_media_controller.py`, `test_config.py`)

```python
@pytest.mark.parametrize(
    ("start", "delta", "expected"),
    [(50, +10, 60), (50, -10, 40), (95, +10, 100), (5, -10, 0), (100, +5, 100), (0, -5, 0)],
)
def test_change_volume_moves_and_clamps(start, delta, expected):
```

Reading the table *is* reading the specification: normal moves, clamping at
both ends, staying at the edge. Choosing inputs at and around limits is called
**boundary value testing** — bugs cluster at edges (`<` vs `<=`, 100 vs 101).

`test_config.py` uses the same idea for invalid settings: a controller named
`vlc`, a port of `eighty`, `70000`, `0`, a log level of `LOUD`, a player list
of only commas.

### 4c. Passing inputs in instead of patching globals

```python
def test_environment_variables_override_the_config_file(tmp_path):
    write_config(tmp_path, f"RMC_TOKEN={GOOD_TOKEN}\nRMC_PORT=9000\n")
    settings = load_server_settings(environment(tmp_path, RMC_PORT="9100"))
    assert settings.port == 9100
```

Because `load_server_settings` takes `environ` as a parameter (page 04), this
test passes a plain dictionary. No real environment is touched. **Code designed
to receive its inputs is easier to test** than code that reaches for globals —
and the tests are the first place that design pays off.

The same file shows **platform-specific tests**:

```python
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_create_config_file_is_readable_only_by_the_owner(tmp_path):
```

`skipif` skips a test where it can't be meaningful, and reports it as skipped
(not silently absent), with the reason.

### 4d. Recording instead of running (`test_server.py`)

```python
def test_run_wires_settings_into_the_app_and_uvicorn(monkeypatch):
    calls = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **options: calls.update(app=app, **options))

    server.run(settings("fake"))

    assert calls["host"] == "127.0.0.1"
    assert calls["access_log"] is False
```

`uvicorn.run` would start a real server and never return. Replaced by a
**recorder**, the test checks the composition root wired the right values —
without a port, a process or a network.

The logging setup is tested the same way (added while writing this page):
`logging.basicConfig` is replaced by a recorder, and the test inspects which
handler *would* have been installed — so the real, process-wide logging of the
test run is never changed.

### 4e. Simulating Windows on Linux (`test_server.py`)

```python
def test_locked_log_loses_no_lines_and_keeps_its_backups(tmp_path, monkeypatch):
    for number in (1, 2, 3):
        (tmp_path / f"server.log.{number}").write_text(f"backup {number}\n")

    real_replace = os.replace
    def locked_replace(source, destination):
        if str(source).endswith("server.log"):
            raise PermissionError("The file is being used by another process")
        return real_replace(source, destination)
    monkeypatch.setattr(server.os, "replace", locked_replace)

    write_log_lines(tmp_path / "server.log", 400)

    assert sum(line.startswith("line ") for line in all_lines(tmp_path)) == 400
    for number in (1, 2, 3):
        assert (tmp_path / f"server.log.{number}").read_text() == f"backup {number}\n"
```

The real bug (page 06) needed Windows and a second program holding the file.
The test reproduces **only the essential condition** — "renaming `server.log`
fails" — by replacing `os.replace` with a version that raises for that one file
and behaves normally otherwise. This is **fault injection**: deliberately
causing the failure a test needs, instead of waiting for it to happen.

**A test that measured the wrong thing:** the companion test
(`...resumes_once_the_lock_is_released`) first asserted all 400 lines survived.
It failed — correctly: with three 2 KB backups only ~127 lines fit, and old lines
*should* age out. The test was fixed to check what should really happen
(rotation resumes, the newest line is present, never more than three backups).
A failing test is a question — "is the code wrong, or the expectation?" — and
here it was the expectation.

### 4f. Capturing what code prints

```python
def test_init_creates_a_config_file_with_a_token(isolated_environment, capsys):
    assert server.main(["init"]) == 0
    printed = capsys.readouterr().out
    assert f"#token={token}" in printed
```

**`capsys`** captures everything written to stdout and stderr during the test;
`readouterr()` returns it as `.out` and `.err`. Command-line behaviour — messages,
warnings — becomes assertable.

---

## Block 5 — integration tests: the real app, in memory

### 5a. `TestClient`

```python
def test_closed_player_gives_empty_state_and_409_for_commands(client, fake):
    fake.session_open = False

    assert state(client) == {"now_playing": None, "volume": None, "muted": None}
    response = client.post("/api/next")
    assert response.status_code == 409
```

FastAPI's **`TestClient`** is an `httpx2.Client` that, instead of opening a
network connection, calls the ASGI app **directly in the same process**. Every
request goes through the real middleware, routing, token dependency, validation
and exception handlers (page 03). Only the player is fake. No port is opened, so
tests can run in parallel and never conflict with a running server.

**`raise_server_exceptions=False`** matters for error tests: by default,
TestClient re-raises exceptions from the app inside the test, which would skip
the app's own 500 handling. With `False`, the test sees what a real client would
see.

### 5b. A test that covers routes that don't exist yet

```python
def api_routes(app):
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api"):
            for method in operations:
                yield method.upper(), path


def test_every_api_route_requires_the_token(app, anonymous_client):
    routes = list(api_routes(app))
    assert len(routes) == 11
    for method, path in routes:
        response = anonymous_client.request(method, path)
        assert response.status_code == 401, f"{method} {path} is not protected"
```

Instead of listing routes by hand, the test **discovers them** from the app's
OpenAPI description (page 03). A new `/api` endpoint added later without the
token check fails this test automatically. Testing a rule over *all* instances
rather than a few examples is sometimes called a **property check** or
**invariant test**.

**`assert len(routes) == 11` guards the guard.** The first version discovered
routes through FastAPI's internal route objects — which a FastAPI update had
restructured, so discovery found **zero** routes and the loop checked nothing. An
"every route is protected" test that passes because there are no routes is worse
than no test. The count assertion made that visible, and discovery was moved to
the public OpenAPI description.

**`yield` in a normal function** makes it a **generator**: it produces values one
at a time as the loop asks for them.

### 5c. Security tests

- **No token, wrong token, wrong scheme** → 401, and a rejected `next` doesn't
  change the track.
- **Tokens never logged:** `caplog` captures log records; the test asserts both
  the guessed token and the real one are **absent** from the log text. Testing
  that something *doesn't* happen is as important as testing that it does.
- **No CORS approval** for a preflight from `https://evil.example`.
- **Security headers** on the page, and not on JSON responses.
- **Pairing page:** served for `127.0.0.1` and `localhost`; **403** for another
  device's address; **403 for DNS rebinding** — a client connecting from
  `127.0.0.1` but with `Host: evil.example`. `TestClient` accepts a `client=`
  address, so both conditions can be simulated precisely.

**A limitation found and worked around:** TestClient can't parse IPv6 URLs such
as `http://[::1]:8000`. The IPv6 case is tested on `is_same_pc_request` directly,
with a minimal stand-in request (`SimpleNamespace(client=..., headers=...)`).
When a tool can't express a case, test the function underneath rather than skip
the case.

### 5d. Errors that must not leak

```python
def test_unexpected_error_becomes_500_without_leaking_details(client, fake, monkeypatch, caplog):
    async def crash():
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(fake, "pause", crash)
    caplog.set_level(logging.INFO)

    response = client.post("/api/pause")

    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert "secret internal detail" in caplog.text
    assert "Traceback" in caplog.text
```

One test, both sides of the design: the client learns nothing internal; the
developer still gets the full traceback in the log.

### 5e. The CLI against the real API (`test_cli.py`)

```python
@pytest.fixture
def run(app, monkeypatch, capsys):
    def fake_make_client(url, token):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return TestClient(app, headers=headers)
    monkeypatch.setattr(cli, "make_client", fake_make_client)

    def run_cli(*args):
        exit_code = cli.main(list(args))
        captured = capsys.readouterr()
        return exit_code, captured.out, captured.err
    return run_cli
```

The fixture returns a **function** — a *factory fixture* — so each test can run
several commands: `run("vol", "30")`, then `run("up")`. It replaces
`cli.make_client`, the **test seam** from page 05, with the in-process client.
A test like `run("next")` exercises argument parsing → HTTP → authentication →
the fake → formatting → exit code, in milliseconds.

**Network failures** use `httpx2.MockTransport`: a transport that hands each
request to a function instead of the network. The function raises
`ConnectTimeout` or `ReadTimeout`, so "PC switched off" and "server too slow" are
tested without either happening. The **UTF-8 test** swaps `sys.stdout` for a
`cp1252` text stream — imitating Windows output redirection — and checks the
bytes decode as UTF-8 with "⏸" intact.

---

## Block 6 — Windows smoke tests

```python
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only adapter")

def test_adapter_imports_and_implements_the_port():
    from remote_music_control.adapters.windows import WindowsMediaController
    controller = WindowsMediaController(player_apps=("chrome.exe",))
    assert isinstance(controller, MediaController)
```

**`pytestmark`** at module level applies a marker to every test in the file.
On Linux all three are skipped; in the Windows CI job they run.

A **smoke test** checks that something basically works — "does it start
without smoke coming out?". These can't test playback (no desktop session in
CI), but they catch what CI *can* see: the Windows-only packages failing to
install or import, or the adapter no longer satisfying the port.

The import happens **inside** each test, not at the top of the file — otherwise
merely collecting the file on Linux would crash.

---

## Block 7 — configuration: coverage and warnings

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=remote_music_control --cov-report=term-missing"
filterwarnings = [
    "error",
    "ignore:The anyio.abc.BlockingPortal alias is deprecated:DeprecationWarning",
]

[tool.coverage.run]
omit = ["*/adapters/windows.py"]

[tool.coverage.report]
exclude_also = ['if __name__ == "__main__":']
```

### Coverage

**Code coverage** measures which lines ran during the tests.
`term-missing` prints the line numbers that never ran:

```
src/remote_music_control/server.py     126      1    99%   54
TOTAL                                  607      3    99%
```

**What it's good for:** finding code no test exercises. While writing this
page, the report showed `configure_logging` and two error paths untested; tests
were added and coverage rose from 98% to 99%.

**What it can't tell you:** whether the tests *check* anything. A test that
calls every function and asserts nothing reaches 100%. Coverage shows where
tests are missing, never that existing ones are good. That's what Block 8 is
about.

**`omit` the Windows adapter:** it can't run on Linux, so including it would
lower the number without any action being possible. It's excluded honestly,
with a comment pointing to the manual checklist — not hidden.

### Warnings as errors

`"error"` turns **every warning into a test failure**. Deprecation warnings are
how libraries announce "this will break in a future version"; printed and
ignored, they pile up until an upgrade breaks everything at once. Failing makes
each one handled when it appears.

It paid off immediately: the first run failed on a deprecated `anyio` name used
**inside Starlette**, not in this project. That single warning is ignored **by
its exact message**, with a comment saying why and when to remove it, so any
other warning still fails. Ignoring all deprecation warnings would have thrown
away the benefit.

---

## Block 8 — do the tests catch real bugs? Mutation checks

A suite can pass and still check nothing important. The direct way to find out
is to **break the code on purpose** and see whether a test fails. Done once in
Phase 6, by hand:

| Deliberate bug | Result |
|---|---|
| Remove the token dependency from the API router | **6 tests failed**, including the route-discovery test |
| Return the traceback to the client in 500 responses | **1 test failed** (`..._without_leaking_details`) |
| Compare tokens with `==` instead of `compare_digest` | **No test failed** — behaviour is identical; timing isn't measurable in a unit test (a documented limit) |

After each change, `git checkout` restored the file.

This is **mutation testing**: introduce small changes (*mutants*) and check
that tests *kill* them. Tools such as `mutmut` or `cosmic-ray` automate it over
thousands of mutants. Doing even three by hand answers the most important
question — would the security tests notice if security were removed?

---

## Block 9 — what the tests found, and what found problems in the tests

Tests earn their keep by failing. A record from this project:

**Application bugs found while writing tests and these pages**, each fixed
together with a test that fails without the fix:

- Empty path variables crashing config loading (page 04).
- CLI timeouts too short for the real player; UTF-8 output crashing on Windows;
  a switched-off PC reported as "too slow" (page 05).
- Log rotation losing data while the log was being watched; an overly broad
  "configuration error" (page 06).
- A malformed pairing link stopping the page script (page 08 — checked in
  headless Chrome, since the page has no JavaScript tests).

**Mistakes in the tests themselves** — equally worth recording:

- Route discovery relying on a private FastAPI structure (fixed: public OpenAPI).
- A logging assertion too broad: it matched the *test client's* own log lines
  (fixed: filter records by logger name).
- A miscounted number of routes (12 instead of 11).
- A rotation test expecting old lines to survive (fixed: rotation *should*
  delete them).

The pattern: **when a test fails, first decide whether the code or the test is
wrong.** Both happen.

---

## Block 10 — continuous integration (`.github/workflows/ci.yml`)

```yaml
on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    name: Tests (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0
        with:
          version: "0.12.13"
          enable-cache: true
      - run: uv sync --locked
      - run: uv run pytest
```

**Continuous integration (CI)** runs the test suite automatically on a clean
machine for every change pushed. It answers "does this work somewhere other than
my PC?" — no leftover files, no personal config, no forgotten installation step.

**GitHub Actions vocabulary:** a **workflow** (this file) contains **jobs**; each
job runs on a fresh virtual machine called a **runner**; a job is a list of
**steps**; `uses:` runs a published **action**, `run:` runs a shell command.

Line by line:

- **`on: push, pull_request`** — every push to any branch, and every pull request.
- **`permissions: contents: read`** — the workflow's automatic GitHub token can
  only read the repository. **Least privilege**: if a step were compromised, it
  couldn't push code or change settings.
- **`matrix: os: [ubuntu-latest, windows-latest]`** — the same job twice, once per
  operating system. Linux runs everything against the fake; Windows additionally
  proves the Windows-only packages install and the smoke tests pass.
- **`fail-fast: false`** — by default, one failing job cancels the others. Here
  both always finish, so a Windows-only failure doesn't hide the Linux result.
- **Pinning `setup-uv` to a commit hash** — a version *tag* like `v10.1.0` is a
  movable label; if an attacker gained control of that repository, they could
  point the tag at malicious code, and every workflow using it would run it. A
  full commit hash can't be moved. The version stays in the comment for humans.
  This guards against a **supply-chain attack** (compromising software through
  one of its dependencies). `actions/checkout` is published by GitHub itself and
  kept on its major tag.
- **`version: "0.12.13"`** — uv itself is pinned, so CI doesn't change behaviour
  the day uv releases a new version.
- **`enable-cache: true`** — downloaded packages are cached between runs.
- **`uv sync --locked`** — installs exactly what `uv.lock` specifies, and **fails
  if the lockfile doesn't match `pyproject.toml`**. That catches committing a new
  dependency without its lockfile — which would otherwise work on your PC and
  install something different everywhere else.
- **`uv run pytest`** — the same command you run locally. CI doing exactly what a
  developer does keeps "passes locally, fails in CI" rare and explainable.

**The first CI runs failed before any test ran** — the workflow referenced
`astral-sh/setup-uv@v10`, a tag that doesn't exist (the project stopped
publishing short major tags). The fix became the commit-hash pin above. Checking
the actual CI result — rather than assuming green — is part of the job.

**The badge** at the top of the README shows the latest result publicly, for
anyone looking at the repository.

---

## What isn't tested automatically, and why

| Not automated | Why | Covered instead by |
|---|---|---|
| The Windows adapter's behaviour | Needs a desktop session and a browser playing | `docs/testing-on-windows.md` (20 steps, dated results) |
| `app.js` | Needs Node.js and a JS test runner (ADR 0007 avoids that toolchain) | Headless Chrome checks; the API it calls is fully tested |
| The logon task and installer | Needs Windows Task Scheduler and a real logon | Manual steps 14–15; tested live in Phase 7 |
| Timing of token comparison | Not measurable reliably in a unit test | Code review; `compare_digest` is the standard function |
| Real network conditions | CI and TestClient don't use the LAN | Measurements on the studio PC (latency, timeouts) |

Knowing — and writing down — what the automated suite *doesn't* cover is part of
a trustworthy test strategy. "All tests pass" means exactly what the tests check,
nothing more.

## Glossary

| Term | Meaning here |
|---|---|
| Test pyramid | Many unit tests, fewer integration tests, few end-to-end/manual |
| Unit / integration / end-to-end test | One module / several parts together / the whole real system |
| Test discovery | pytest finding `test_*` files and functions by name |
| Assertion rewriting | pytest showing both values when an `assert` fails |
| Arrange–Act–Assert | Prepare, do one thing, check |
| Fixture / fixture scope | Setup a test receives by parameter name / how long one instance lives |
| `conftest.py` | File pytest loads automatically for shared fixtures |
| `autouse` fixture | Applied to every test without being requested |
| Test isolation / flaky test | Tests independent of each other and the machine / tests that pass or fail unpredictably |
| `monkeypatch` / `tmp_path` / `capsys` / `caplog` | Temporary changes undone after the test / fresh temp folder / captured output / captured logs |
| Teardown (`yield` fixture) | Cleanup code after the test |
| Parametrize | One test function run once per case |
| Boundary value testing | Choosing inputs at and around limits |
| Stub / spy / recorder | Double returning fixed answers / double recording calls |
| Fault injection | Deliberately causing a failure to test how it's handled |
| `TestClient` | Calls the ASGI app in-process, with no network |
| Property / invariant test | Checking a rule over all instances (every route) |
| Factory fixture | A fixture that returns a function tests call repeatedly |
| `MockTransport` | HTTP transport that hands requests to a function instead of the network |
| Smoke test | Checks that something basically starts or loads |
| Code coverage | Which lines ran during tests; not whether they were checked |
| Mutation testing | Breaking code on purpose to see whether tests notice |
| Continuous integration | Automatic test runs on a clean machine for every change |
| Workflow / job / runner / step / action | GitHub Actions building blocks |
| Build matrix / `fail-fast` | Same job on several configurations / whether one failure cancels the rest |
| Least privilege | Granting only the permissions needed |
| Supply-chain attack / pinning by commit | Compromise through a dependency / referencing an unmovable version |
| Lockfile check (`--locked`) | Failing when dependencies and lockfile disagree |

## Check your understanding

1. Why is `isolated_environment` marked `autouse=True`? What could happen on your
   Ubuntu PC without it?
2. A test asks for both `client` and `fake`. Are they connected? Which fixture
   declarations make that true?
3. `test_every_api_route_requires_the_token` asserts `len(routes) == 11`. What
   real failure did that line reveal, and why is a passing security test that
   checks nothing dangerous?
4. The rotation bug needed Windows and a second program. How does
   `test_locked_log_loses_no_lines_and_keeps_its_backups` reproduce it on Linux?
   What's that technique called?
5. The suite has 99% coverage. Name something important it doesn't prove.
6. Which deliberate bug did *no* test catch in the mutation check, and why is that
   acceptable?
7. Why does CI pin `setup-uv` to a commit hash but `actions/checkout` to `v7`?
8. `uv sync --locked` fails in CI but `uv sync` works on your PC. What did you
   probably forget to commit?
9. The Windows smoke tests import the adapter *inside* each test function. What
   would happen on the Linux CI runner if the import were at the top of the file?
10. When `test_rotation_resumes_once_the_lock_is_released` first failed, was the
    code wrong or the test? How do you decide in general?
