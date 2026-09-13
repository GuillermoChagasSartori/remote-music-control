# 03 — `api.py`: the HTTP API

**File:** [`src/remote_music_control/api.py`](../../src/remote_music_control/api.py) · ~350 lines
**Depends on:** FastAPI (and Starlette, pydantic underneath), `media_controller.py` ([page 01](01-media-controller.md)), `pairing.py`
**Used by:** `server.py`, which builds the app and hands it to uvicorn; the tests, which call it in-process

This is the largest module so far and the one where most web concepts meet.
Take it in sittings: the first two sections give the map, then each block is
self-contained.

## Where this file sits

`api.py` is an **adapter too** — on the other side of the port. The Windows and
fake adapters connect the port to a *media player*; `api.py` connects it to the
*network*. In ports-and-adapters vocabulary those are called:

- **driven** (or *secondary*) adapters: the application calls them — the fake,
  the Windows adapter;
- **driving** (or *primary*) adapters: they call the application — this HTTP
  API, and in principle any other entry point.

```
  phone / browser / CLI
          │  HTTP
          ▼
  ┌──────────────── api.py (driving adapter) ────────────────┐
  │ HTTP ⇄ Python: parse, authenticate, validate, respond     │
  └───────────────────────────┬───────────────────────────────┘
                              │ awaits MediaController methods
                              ▼
                   media_controller.py (port)
                              ▲
                  fake.py / windows.py (driven adapters)
```

The rule from page 01 holds: `api.py` imports the **port**, never an adapter.
Which adapter it gets is decided in `server.py` ([page 06](06-server.md)).

## A request's journey

Before reading code, follow one request — `POST /api/next` from your phone —
through everything in this file. Every box is a block below.

```
uvicorn (receives bytes on port 8000, speaks ASGI to the app)
  │
  ▼
web_page_headers middleware ─────────────────────────┐ (runs first: defined last)
  │                                                   │
  ▼                                                   │
log_requests_and_unexpected_errors middleware ──────┐ │
  │                                                 │ │
  ▼                                                 │ │
router: which route matches "POST /api/next"?       │ │
  │                                                 │ │
  ▼                                                 │ │
dependency: require_token ── wrong? → 401 ───────┐  │ │
  │                                               │  │ │
  ▼                                               │  │ │
handler next_track() → await controller.next_track()  │ │
  │          │                                    │  │ │
  │          └─ raises NoMediaSessionError → 409 ─┤  │ │
  │          └─ raises MediaControllerError → 502 ┤  │ │
  │          └─ raises anything else ─────────────┼─→ 500 (caught by the log middleware)
  ▼                                               ▼  │ │
204 No Content ◀──────────────────────────────────┘  │ │
  │                                                   │ │
  └──── logged "POST /api/next -> 204 in 950 ms" ◀───┘ │
  └──── (web headers only for non-/api paths) ◀────────┘
```

---

## HTTP in five minutes

If HTTP is familiar, skip to Block 1.

An HTTP **request** is text with three parts:

```
PUT /api/volume HTTP/1.1                  ← method, path, version
Host: desktop-lvq43h5.local:8000          ← headers: name: value
Authorization: Bearer eyJ...
Content-Type: application/json

{"level": 40}                             ← body (optional)
```

The **response** has the same shape: a status line (`HTTP/1.1 200 OK`), headers,
and an optional body.

**Methods** used here: `GET` (read, no side effects), `POST` (do something),
`PUT` (replace a value; repeating it has the same effect — *idempotent*).

**Status codes** used here, and what each means in this app:

| Code | Name | Here |
|---|---|---|
| 200 | OK | Success with a body (state, volume) |
| 204 | No Content | Success, nothing to return (play, next…) |
| 401 | Unauthorized | Missing or wrong token — "who are you?" |
| 403 | Forbidden | Pairing page from another device — "I know the request, and no" |
| 409 | Conflict | The player is closed, so the command can't apply |
| 422 | Unprocessable Content | Bad input: volume 150, missing field |
| 500 | Internal Server Error | A bug or unexpected failure on our side |
| 502 | Bad Gateway | The player (behind us) refused or failed |

The first digit is the family: **2xx** success, **4xx** the client's problem,
**5xx** the server's problem. That split is why a closed browser is 409 (the
request doesn't fit the current state) but a player that rejects a valid
command is 502 (something behind the server failed).

---

## Block 1 — the module docstring

It states three things a reader needs before the code: the dependency rule
(port only, **dependency injection**), the endpoint shape (ADR 0006), and the
security model (token on `/api`, public static files, `/pair` only on the
server PC). Each points to its ADR, so the *why* lives in one place.

**Dependency injection** here means: `create_app()` *receives* the controller
instead of creating it. Tests pass a fake; `server.py` passes whichever adapter
the configuration selects. The API never decides.

---

## Block 2 — imports: three libraries, one stack

```python
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import pairing
from .media_controller import (...)
```

Three layers that are easy to confuse:

| Library | Role |
|---|---|
| **Starlette** | The web toolkit: requests, responses, routing, middleware, static files. `Request`, `FileResponse`, `StaticFiles` are really Starlette classes that FastAPI re-exports. |
| **pydantic** | Data validation from type hints: turns JSON into checked Python objects and back. |
| **FastAPI** | Glue on top: reads your function signatures and type hints, wires Starlette and pydantic together, and generates the API description (OpenAPI) behind `/docs`. |

**ASGI** is the contract between uvicorn (the server that owns the network
socket) and the app. It's the async successor to WSGI, which Flask and Django
traditionally use.

**`from . import pairing`** imports the *module*, and the code later calls
`pairing.current_network()`. The alternative, `from .pairing import
current_network`, would copy the function into this module's namespace; tests
that replace `pairing.current_network` with a fake version would then not
affect `api.py`. Importing the module keeps the lookup live, which is what lets
the pairing tests control the network details.

---

## Block 3 — constants: the web folder and the security policy

```python
WEB_DIR = Path(__file__).parent / "web"
```

`__file__` is this module's path on disk; `.parent` is its folder; `/ "web"`
joins paths (`pathlib` overloads `/`). The web files are part of the Python
package, so wherever the package is installed — Ubuntu, the studio PC, a CI
runner — they're found next to this file without configuration.

```python
CONTENT_SECURITY_POLICY = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
```

A **Content-Security-Policy (CSP)** is a response header that tells the
browser what the page is *allowed* to do. Directive by directive:

| Directive | Meaning | What it stops |
|---|---|---|
| `default-src 'self'` | Scripts, styles, images, connections only from this same server | A script injected into the page can't load code from, or send the token to, another site; inline `<script>` blocks don't run |
| `frame-ancestors 'none'` | No other site may show this page in a frame | **Clickjacking**: an evil page overlays our page invisibly and tricks you into clicking "next" or entering the token |
| `base-uri 'none'` | The page can't change its base URL | An injected `<base>` tag redirecting relative links |
| `form-action 'self'` | Forms can only submit to this server | An injected form sending the token elsewhere |

This is **defence in depth**: the page already never inserts untrusted text as
HTML (page 08), so injection shouldn't be possible — the CSP limits the damage
if that first defence ever fails.

---

## Block 4 — DTOs: pydantic models for the JSON

```python
class StateResponse(BaseModel):
    now_playing: NowPlaying | None
    volume: int | None
    muted: bool | None

class VolumeResponse(BaseModel):
    volume: int
    muted: bool

class SetVolumeRequest(BaseModel):
    level: int = Field(ge=MIN_VOLUME, le=MAX_VOLUME)

class SetMutedRequest(BaseModel):
    muted: bool
```

A **DTO (data transfer object)** describes exactly what crosses the network —
nothing about behaviour. Subclassing pydantic's `BaseModel` gives each one:

- **parsing and validation** of incoming JSON: `{"level": "40"}` becomes the
  integer 40; `{"level": "loud"}` or a missing field is rejected;
- **constraints** via `Field(ge=..., le=...)` (*greater or equal*, *less or
  equal*): `{"level": 150}` never reaches our code;
- **serialization** of outgoing objects to JSON;
- a **JSON Schema**, which FastAPI puts in the OpenAPI document shown at `/docs`.

A rejected request gets **422** with a precise, machine-readable explanation,
generated automatically:

```json
{"detail": [{"type": "less_than_equal", "loc": ["body", "level"],
             "msg": "Input should be less than or equal to 100", "input": 150}]}
```

This is **declarative validation**: you *declare* the rules as types and
constraints, and the framework enforces them, instead of writing
`if not 0 <= level <= 100: return error` in every handler.

**Why separate DTOs instead of returning `NowPlaying` directly?** The port's
types describe the *domain*; DTOs describe the *wire format*. They often look
alike, but they change for different reasons — the API might add a field for
the web page without touching the port. `StateResponse` combines three port
calls into one JSON object; nothing in the port has that shape. It does reuse
`NowPlaying` as a field: pydantic can serialize standard dataclasses, so there
was no need to duplicate those four fields.

**Why `None` everywhere in `StateResponse`:** when the player is closed, the
page shows "nothing playing" instead of a number. `None` becomes JSON `null`.

---

## Block 5 — `Annotated` and where parameters come from

```python
VolumeStep = Annotated[int, Query(ge=1, le=MAX_VOLUME)]
```

`Annotated[type, metadata]` (from `typing`) attaches extra information to a
type without changing it: to Python this is just `int`; to FastAPI it says
"read it from the **query string** and require 1–100". Giving it a name makes a
reusable **type alias** for the two volume-step endpoints.

FastAPI decides where each handler parameter comes from by looking at it:

| Parameter looks like | FastAPI reads it from | Example here |
|---|---|---|
| A pydantic model | The JSON **body** | `body: SetVolumeRequest` |
| A simple type (`int`, `str`) | The **query string** (`?step=10`) | `step: VolumeStep = 5` |
| A name in the path (`/items/{id}`) | The **path** | (not used) |
| `Request` | The raw request object | `request: Request` |
| `Annotated[..., Depends(f)]` | The return value of `f` | the token credentials |

Nothing is registered by hand. This **convention over configuration** — the
signature *is* the specification — is FastAPI's central idea.

---

## Block 6 — `HTTPBearer`: reading the token header

```python
bearer_scheme = HTTPBearer(auto_error=False)
```

A **bearer token** is a secret that grants access to whoever holds ("bears")
it, sent as `Authorization: Bearer <token>`. `HTTPBearer` is FastAPI's helper
that reads and splits that header. Verified behaviour:

| Header sent | `HTTPBearer` returns |
|---|---|
| `Bearer abc` or `bearer abc` | credentials with `.credentials == "abc"` |
| `Basic abc` (another scheme) | `None` |
| `Bearer` (no value) | `None` |
| no header | `None` |

`auto_error=False` means "return `None` instead of rejecting the request
yourself". Our own check (Block 10) then produces a single response for every
failure. Registering it through FastAPI also makes `/docs` show an
**Authorize** button, so you can try the API in the browser with the token.

---

## Block 7 — "is this the server PC?"

```python
LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}
LOOPBACK_HOST_NAMES = {"127.0.0.1", "localhost", "::1"}

def is_same_pc_request(request: Request) -> bool:
    connection_is_local = request.client is not None and request.client.host in LOOPBACK_ADDRESSES
    host_name = urlsplit("//" + request.headers.get("host", "")).hostname
    return connection_is_local and host_name in LOOPBACK_HOST_NAMES
```

**Loopback** is the network interface a computer uses to talk to itself:
`127.0.0.1` in IPv4, `::1` in IPv6, usually named `localhost`. Traffic to it
never leaves the machine. Sets (`{...}`) are used because checking membership
(`in`) in a set is fast and reads naturally.

Only the pairing page uses this, and it needs **both** checks:

**1. The connection comes from loopback.** `request.client.host` is the
address the connection actually came from, as seen by the operating system. A
phone on the Wi-Fi shows up as `192.168.1.12`, so it fails.

**2. The `Host` header names loopback.** This one defends against **DNS
rebinding**, an attack worth understanding step by step:

1. You open `http://evil.example` in a browser **on the studio PC**.
2. Its DNS record first points to the attacker's server, which sends a page
   with a script.
3. The attacker then changes the DNS record so `evil.example` resolves to
   `127.0.0.1`, with a very short cache time.
4. The script requests `http://evil.example:8000/pair`. The browser looks up
   the name again, gets `127.0.0.1`, and connects to **our** server.
5. To the browser, the page and the response share the same origin
   (`evil.example:8000`), so it lets the script read the response — including
   the token.

Check 1 passes (the connection really is local). But the request still says
`Host: evil.example:8000`, because that's what the browser thinks it's talking
to, so check 2 refuses it. This is called **Host header validation**.

**`urlsplit("//" + host).hostname`** is a small trick: `urlsplit` parses URLs,
and prefixing `//` makes it treat the header as a network location. It then
handles `localhost:8000`, `127.0.0.1:8000` and the IPv6 form `[::1]:8000`
correctly (brackets removed, port dropped). Splitting on `:` by hand would
break on IPv6, which is full of colons.

---

## Block 8 — the refusal page

```python
PAIRING_REFUSED_PAGE = """<!doctype html>
...runs the server, at <code>http://127.0.0.1:{port}/pair</code>.</p>
</main></body></html>"""
```

A **triple-quoted string** spans several lines. `{port}` is a placeholder
filled with `str.format(port=...)`. Escaping isn't needed because the only
value inserted is an integer the server itself computed. (If a braces
character ever appeared in this HTML, `format` would misread it — hence the
comment in the code.)

---

## Block 9 — `create_app`: the application factory

```python
def create_app(controller: MediaController, token: str) -> FastAPI:
    app = FastAPI(title="Remote Music Control")
    expected_token = token.encode()
    ...
    return app
```

**Application factory:** a function that builds and returns a new app, instead
of a module-level `app = FastAPI()` created on import. Each test calls
`create_app(fake, token)` with a fresh fake, so no state leaks between tests,
and the production server calls it once with the real adapter.

**Closures:** every handler below is defined *inside* `create_app`, so it can
use `controller` and `token` directly — Python keeps variables from the
enclosing function alive for inner functions that reference them. That's the
plainest way to give handlers the injected objects. (FastAPI's alternative is
`Depends()` for everything, or `app.state`; both add indirection this small API
doesn't need.)

**`token.encode()`** turns the text into bytes once. `secrets.compare_digest`
compares bytes safely for any characters; comparing `str` objects it only
accepts ASCII.

---

## Block 10 — `require_token`: authentication as a dependency

```python
    async def require_token(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    ) -> None:
        if credentials is not None and secrets.compare_digest(
            credentials.credentials.encode(), expected_token
        ):
            return
        reason = "no Bearer token" if credentials is None else "wrong token"
        logger.warning("rejected %s %s from %s: %s", request.method, request.url.path, client_address(request), reason)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

### FastAPI dependencies

A **dependency** is a function FastAPI runs *before* a handler. Its parameters
are resolved the same way as a handler's (Block 5) — here `credentials` is
itself the result of another dependency, `bearer_scheme`. If a dependency
raises `HTTPException`, the handler never runs.

"Dependency injection" now has two related meanings in this file: Block 1's
(the controller passed into `create_app`) and FastAPI's (functions whose
results are passed into handlers). Both mean *the code receives what it needs
instead of fetching it*.

### Constant-time comparison

`a == b` on strings stops at the **first different character**. Comparing a
guess starting with the right first character takes a tiny bit longer than one
starting wrong. With enough requests and careful timing, an attacker can learn
the token one character at a time — a **timing attack** (a kind of
**side-channel attack**: learning a secret from *how* a system behaves rather
than what it says). `secrets.compare_digest` always examines the whole value,
so its duration reveals nothing.

Realistically, a home Wi-Fi is too noisy to measure those nanoseconds — but the
correct function costs nothing, and using `==` for secrets is a classic finding
in security reviews.

### One response for every failure

Missing token, wrong token, wrong scheme: all get the **same** status and
message. Telling an attacker *which* one failed would only help them. The
**log** records the distinction (without the token itself) for you.

**401 vs 403:** 401 *Unauthorized* really means "not authenticated — tell me
who you are"; it must include a `WWW-Authenticate` header naming the expected
scheme. 403 *Forbidden* means "I know who you are (or it doesn't matter), and
the answer is no" — which is why the pairing page from a phone is 403: no token
would change that.

**Lazy log formatting:** `logger.warning("rejected %s %s", a, b)` passes values
separately instead of using an f-string. The logging module only builds the
final text if the message will actually be written, and log tools can group
messages by their fixed template. It's the standard style for `logging`.

---

## Block 11 — exception handlers: errors become status codes

```python
    @app.exception_handler(NoMediaSessionError)
    async def no_media_session(request, error) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(MediaControllerError)
    async def media_controller_failed(request, error) -> JSONResponse:
        logger.warning(...)
        return JSONResponse(status_code=502, content={"detail": str(error)})
```

An **exception handler** turns an exception raised anywhere during a request
into a response. Handlers stay simple — `await controller.next_track()` — and
never need `try/except` for these cases. This is **centralized error
handling**: the mapping from errors to HTTP lives in one place.

Remember the hierarchy from page 01: `NoMediaSessionError` *is a*
`MediaControllerError`. When one is raised, Starlette walks the exception's
class hierarchy from most specific to least and uses the first handler it
finds — so a closed browser gets 409, never 502. The order in which the
handlers are written doesn't matter.

`str(error)` is the message the adapter wrote (`"no media session from
chrome.exe, firefox.exe — is the player open?"`). These messages are written
for users, so sending them is fine. Unexpected exceptions are different — see
the next block.

**`{"detail": ...}`** matches FastAPI's own error format (401 and 422 use it
too), so clients read every error the same way; the CLI's
`server_error_message()` and the page's `api()` both rely on it.

---

## Block 12 — middleware

```python
    @app.middleware("http")
    async def log_requests_and_unexpected_errors(request: Request, call_next):
        ...
        response = await call_next(request)
        ...
        return response
```

**Middleware** wraps the whole request: code before `await call_next(request)`
runs on the way in, code after it runs on the way out. `call_next` runs
everything inside — other middleware, routing, dependencies, the handler —
and returns the response. It's the **decorator pattern** (or *chain of
responsibility*) applied to HTTP: layers that each add one behaviour around a
core.

**Order — verified, and easy to get wrong:** the middleware defined **last**
becomes the **outermost** layer. So `web_page_headers` (defined second) runs
first on the way in and last on the way out, around
`log_requests_and_unexpected_errors`.

### 12a. Logging and the safety net

```python
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error in %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={"detail": "internal server error (see the server log)"})
        if request.method != "GET" and request.url.path.startswith("/api"):
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info("%s %s -> %d in %.0f ms (from %s)", ...)
        return response
```

**`time.perf_counter()`** is a high-resolution clock meant for measuring
durations; unlike `time.time()`, it can't jump when the system clock is
adjusted.

**The `except Exception` safety net:** 401, 409, 422 and 502 are handled
*inside* by FastAPI and the exception handlers, so they arrive here as normal
responses (and get logged). Only truly unexpected errors reach this `except`:
a bug, or a Windows API failure nobody anticipated. For those:

- **`logger.exception`** logs at ERROR level *and* includes the full
  traceback — the developer's view;
- the client gets a generic message — revealing exception text or stack traces
  to clients is **information disclosure**, since internals help attackers.

Catching `Exception` (not `BaseException`) deliberately lets `KeyboardInterrupt`
and `SystemExit` through, so Ctrl+C still stops the server.

**Why skip GETs:** the web page polls `/api/state` every second — about 86,000
lines a day of noise. POST and PUT change something, so those are worth
recording, with duration and client address.

### 12b. Headers for the web page

```python
    @app.middleware("http")
    async def web_page_headers(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers.setdefault("Cache-Control", "no-cache")
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response
```

Only non-API responses (the page, CSS, JS, `/pair`) get these; JSON responses
don't need a CSP.

- **`Cache-Control: no-cache`** — despite the name, the browser *does* cache,
  but must ask the server before reusing its copy. If the file is unchanged,
  the server answers `304 Not Modified` with no body; if you updated `app.js`,
  the browser gets the new one. Without it, a phone could keep running old
  JavaScript for days.
- **`Cache-Control: no-store`** (set by `/pair`) is stricter: never save the
  response at all — right for a page containing the token.
- **`X-Content-Type-Options: nosniff`** stops the browser from guessing a file's
  type from its content, a guess attackers can abuse to make a text file run
  as a script.

**`setdefault`** sets the header only if the response doesn't already have
one. That's what lets `/pair` choose `no-store` without this middleware
overwriting it with `no-cache`.

**A note on the style:** `@app.middleware("http")` creates Starlette's
`BaseHTTPMiddleware`, the simplest form. For very high traffic, "pure ASGI"
middleware is faster and avoids some edge cases with streaming responses;
neither matters for one household's music remote, and the plain form is far
easier to read.

---

## Block 13 — `/health`: a liveness check

```python
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}
```

**`@app.get("/health")`** is a decorator that *registers* the function for
`GET /health`. The return annotation tells FastAPI the response shape.

A **liveness check** answers only "is the process up and serving HTTP?". It
deliberately doesn't touch the player: a closed browser is normal, and should
not make the server look dead. The related **readiness check** ("can it do its
job right now?") would consult the player. The installer uses `/health` to
confirm the server started, and `music health` uses it before testing the
token.

It's public, and it returns nothing beyond `ok`. An earlier version included
the adapter's class name; that was removed in Phase 5 because an
unauthenticated endpoint shouldn't describe the internals.

---

## Block 14 — the API router

```python
    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
    ...
    app.include_router(api)
```

An **APIRouter** groups routes. Two settings apply to every route in it:

- `prefix="/api"` — `@api.get("/state")` becomes `GET /api/state`;
- `dependencies=[Depends(require_token)]` — every route runs the token check.

That second line is the security design in one statement: authentication is
applied to the *group*, so a new endpoint added later **can't forget** it. The
test `test_every_api_route_requires_the_token` backs this up by discovering all
`/api` routes from the OpenAPI document and requesting each without a token.

The routes are defined first, then `include_router` attaches the group to the
app.

---

## Block 15 — reading state

```python
    async def read_volume() -> VolumeResponse:
        return VolumeResponse(volume=await controller.get_volume(), muted=await controller.is_muted())

    @api.get("/state")
    async def get_state() -> StateResponse:
        now = await controller.now_playing()
        if now is None:
            return StateResponse(now_playing=None, volume=None, muted=None)
        return StateResponse(now_playing=now, volume=await controller.get_volume(), muted=await controller.is_muted())
```

**`read_volume`** is a local helper (not a route — no decorator) used by five
endpoints, so "what a volume response contains" is written once.

**`get_state`** is the endpoint the web page polls: one request returns
everything it displays (ADR 0006). If the player is closed, it returns a normal
200 with `null`s instead of an error, following the port's contract.

**The race in the comment:** between `now_playing()` and `get_volume()` there
are `await`s. If the browser closes in that instant, `get_volume()` raises
`NoMediaSessionError` and the client gets a 409 for that one poll. The page
polls again a second later. Handling it perfectly would add code for a
situation that corrects itself — a conscious trade-off, documented where
someone would wonder about it.

---

## Block 16 — transport endpoints

```python
    @api.post("/play", status_code=status.HTTP_204_NO_CONTENT)
    async def play() -> None:
        await controller.play()
    ...
```

Five nearly identical endpoints, one per port method. Each is a **thin
handler**: translate HTTP into one port call, nothing more. All the logic lives
in the adapters (and the waiting-until-visible behaviour in the Windows
adapter, ADR 0008), so these never need to change.

**Why POST to a verb (`/api/next`)** instead of a REST resource: "next track"
is an action, not a thing you can read or replace. This mix of **RPC-style**
actions and **REST-style** state is deliberate (ADR 0006).

**Why 204 and no body:** the command either worked (204) or raised (409/502).
Returning the new state could mislead: on the real player the change becomes
visible slightly later, so clients read state with `GET /api/state`.

**`status.HTTP_204_NO_CONTENT`** is just the number 204 with a readable name —
the magic-number idea from page 01 applied to HTTP.

---

## Block 17 — volume endpoints

```python
    @api.put("/volume")
    async def set_volume(body: SetVolumeRequest) -> VolumeResponse:
        await controller.set_volume(body.level)
        return await read_volume()

    @api.post("/volume/up")
    async def volume_up(step: VolumeStep = DEFAULT_VOLUME_STEP) -> VolumeResponse:
        await change_volume(controller, +step)
        return await read_volume()
    ...
    @api.put("/mute")
    async def set_muted(body: SetMutedRequest) -> VolumeResponse:
        await controller.set_muted(body.muted)
        return await read_volume()
```

**PUT with a body** for absolute values — "the volume *is* 40" — which is
idempotent: sending it twice leaves 40. **POST with a query parameter** for
relative changes — "volume *up* by 5" — which is not: twice means +10.

**Why volume endpoints return the resulting volume** (unlike transport):
volume changes take effect immediately, and clients need the *final* value —
`up` by 80 from 50 clamps to 100, and only the server knows that. The CLI
prints it; the page moves its slider to it.

`+step` and `-step` are just the number and its negative; `change_volume`
(page 01, Block 8) adds and clamps.

---

## Block 18 — the web page and static files

```python
    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")
    ...
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
```

**`FileResponse`** sends a file from disk with the right `Content-Type`, plus
`ETag` and `Last-Modified` headers that make the `304 Not Modified`
revalidation from Block 12b work.

**`include_in_schema=False`** keeps the page out of the OpenAPI document — it's
not part of the API.

**`app.mount`** attaches a whole sub-application at a path prefix: every
request under `/static/` is served from the `web/` folder
(`/static/app.js` → `web/app.js`). `StaticFiles` refuses paths that try to
escape the folder, like `/static/../config.py` — a **path traversal** attack.

**Nothing here requires the token**, on purpose: the HTML, CSS and JavaScript
contain no secrets. The page must load *before* it has a token, so it can ask
for one.

---

## Block 19 — the pairing page route

```python
    @app.get("/pair", include_in_schema=False)
    async def pairing_page(request: Request) -> HTMLResponse:
        port = request.url.port or 80
        if not is_same_pc_request(request):
            logger.warning("refused the pairing page to %s: only served to the server PC", client_address(request))
            return HTMLResponse(PAIRING_REFUSED_PAGE.format(port=port), status_code=status.HTTP_403_FORBIDDEN)
        page = pairing.render_pairing_page(token=token, port=port, network=pairing.current_network())
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})
```

- **`request.url.port or 80`**: the port in the address the browser used — the
  one the server listens on — so QR codes and messages are right even with
  `RMC_PORT=9000`. HTTP URLs without a port mean 80, and `port` is then `None`,
  hence `or 80`.
- **Refusal first**, logged with the client address, before any token-bearing
  content is built. This ordering is a **guard clause** again (page 02).
- **`no-store`** so the token isn't written to the browser's disk cache.
- The HTML itself comes from `pairing.py` (its own page later); this route only
  decides *whether* to show it.

---

## The whole API at a glance

| Route | Auth | Success | Errors |
|---|---|---|---|
| `GET /health` | public | 200 `{"status": "ok"}` | — |
| `GET /api/state` | token | 200 state | 401 |
| `POST /api/play`, `/pause`, `/play-pause`, `/next`, `/previous` | token | 204 | 401, 409, 502, 500 |
| `GET /api/volume` | token | 200 volume | 401, 409 |
| `PUT /api/volume` | token | 200 volume | 401, 409, 422 |
| `POST /api/volume/up`, `/down` | token | 200 volume | 401, 409, 422 |
| `PUT /api/mute` | token | 200 volume | 401, 409, 422 |
| `GET /` and `/static/*` | public | the web page | 404 |
| `GET /pair` | server PC only | pairing page | 403 |
| `GET /docs`, `/openapi.json` | public | FastAPI's API explorer | — |

## Glossary

| Term | Meaning here |
|---|---|
| Driving / driven adapter | Calls the application (this API) / is called by it (fake, Windows) |
| ASGI | The async interface between a server (uvicorn) and an app (FastAPI) |
| Starlette / pydantic / FastAPI | Web toolkit / data validation / glue that reads type hints |
| DTO | A class describing the exact data crossing the network |
| Declarative validation | Rules declared as types and constraints, enforced by the framework |
| OpenAPI | A standard machine-readable description of an HTTP API; powers `/docs` |
| Convention over configuration | Behaviour inferred from how code is written, not registered by hand |
| Bearer token | A secret that grants access to whoever presents it |
| Content-Security-Policy | Header restricting what a page may load and do |
| Clickjacking | Tricking clicks through an invisible framed page |
| Defence in depth | Several independent protections, so one failure isn't fatal |
| Loopback | The interface a computer uses to talk to itself (`127.0.0.1`, `::1`) |
| DNS rebinding | Pointing an attacker's domain at a local address to read local pages |
| Host header validation | Rejecting requests whose `Host` isn't an expected name |
| Application factory | A function that builds a fresh app |
| Closure | An inner function using variables from its enclosing function |
| FastAPI dependency | A function run before a handler, whose result is injected |
| Timing / side-channel attack | Learning a secret from how long operations take |
| 401 vs 403 | Not authenticated vs not allowed |
| Centralized error handling | Exceptions mapped to responses in one place |
| Middleware | Layers wrapping every request and response |
| Information disclosure | Leaking internal details (tracebacks) to clients |
| Liveness vs readiness check | "Process is up" vs "able to do its job" |
| APIRouter | A group of routes sharing a prefix and dependencies |
| Thin handler | A route that only translates HTTP to one application call |
| Idempotent | Repeating the request has the same effect as doing it once |
| `no-cache` vs `no-store` | Revalidate before reuse vs never save |
| Path traversal | Using `../` to reach files outside a served folder |

## Check your understanding

1. A new endpoint `POST /api/shuffle` is added to the `api` router. Does it
   require the token? What if it were added with `@app.post` instead — which
   test would catch the mistake?
2. Why is a closed browser 409 but a player refusing "next" 502? Why isn't
   either one 500?
3. The pairing page checks the connection address *and* the `Host` header.
   Describe an attack that only the first check would miss.
4. `web_page_headers` uses `setdefault`. What would change for `/pair` if it
   used `response.headers["Cache-Control"] = "no-cache"`?
5. The logging middleware skips GET requests. Which useful information does
   that lose, and why is it still the right choice here?
6. Why does `PUT /api/volume` take a JSON body, while `POST /api/volume/up`
   takes a query parameter?
7. Swap the order in which the two middleware functions are defined. For a
   request to `/api/next` that crashes with a bug, does the response change?
   (Hint: which layer creates the 500, and which one adds headers?)
8. What would an attacker learn if `require_token` returned "missing token"
   for no header and "wrong token" for a bad one in the response body?
