"""HTTP API: translates HTTP requests into MediaController calls.

This layer depends only on the MediaController *port*, never on a specific
adapter. The controller is handed in from outside (see server.py) — that is
*dependency injection*: a component receives the objects it needs instead of
creating them itself, so a test can pass in a fake and the production server
can pass in the real thing.

Endpoint shape (see docs/decisions/0006):
- Actions are POST to a verb-like path (`POST /api/next`) — RPC-style.
- State you can overwrite is PUT with the new value (`PUT /api/volume`) — REST-style.
- `GET /api/state` returns everything a client displays, in one request.

Security (see docs/decisions/0009): every /api route requires the shared bearer
token. `/health` and the web page's static files are public — they contain no
secrets and do nothing. `/pair` shows the token, so it is served only to the
server PC itself (see docs/decisions/0012).

The web page (HTML, CSS, JS in the `web/` folder) is served by this same app,
so there is nothing to install on the client: open the server's address in a
browser. See docs/decisions/0007.
"""

import logging
import secrets
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import pairing
from .media_controller import (
    MAX_VOLUME,
    MIN_VOLUME,
    MediaController,
    MediaControllerError,
    NoMediaSessionError,
    NowPlaying,
    change_volume,
)

logger = logging.getLogger(__name__)

DEFAULT_VOLUME_STEP = 5

# The web files ship inside the Python package, next to this module, so they
# are installed wherever the package is — no separate path to configure.
WEB_DIR = Path(__file__).parent / "web"

# Content-Security-Policy for the web page: the browser may only load scripts,
# styles and data from this same server, and no other site may embed the page
# in a frame (which blocks *clickjacking*). A second line of defence behind
# app.js never inserting untrusted text as HTML.
CONTENT_SECURITY_POLICY = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


# --- Request and response bodies ---
#
# These pydantic models are *DTOs* (data transfer objects): they describe the
# exact JSON shape that crosses the network. FastAPI uses them to validate
# incoming JSON (a level of 150 is rejected with HTTP 422 before our code runs)
# and to generate the schema shown on the /docs page.


class StateResponse(BaseModel):
    # All three are None when there is no media session (e.g. browser closed).
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


# Reused by the volume up/down endpoints: an optional ?step=N query parameter.
VolumeStep = Annotated[int, Query(ge=1, le=MAX_VOLUME)]

# Reads an `Authorization: Bearer <token>` header. auto_error=False lets our own
# check produce the error, so missing and wrong tokens get the same response.
bearer_scheme = HTTPBearer(auto_error=False)


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# Loopback: the addresses and names a computer uses to talk to itself.
LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}
LOOPBACK_HOST_NAMES = {"127.0.0.1", "localhost", "::1"}


def is_same_pc_request(request: Request) -> bool:
    """True only for a browser on the server PC that opened a loopback address.

    Two checks, because each one alone can be fooled:

    1. The connection comes from a loopback address, so it didn't come over
       the network from another device.
    2. The Host header (the address typed in the browser) is a loopback name.
       This blocks *DNS rebinding*: a malicious web page opened on this PC
       makes its own domain name resolve to 127.0.0.1, so the browser treats
       the page and our server as the same site and lets the page read the
       response. The request then still carries the attacker's domain in the
       Host header, which fails this check.
    """
    connection_is_local = request.client is not None and request.client.host in LOOPBACK_ADDRESSES
    # urlsplit understands "localhost:8000" and "[::1]:8000" alike.
    host_name = urlsplit("//" + request.headers.get("host", "")).hostname
    return connection_is_local and host_name in LOOPBACK_HOST_NAMES


# {port} is filled in with str.format(); the HTML itself contains no other braces.
PAIRING_REFUSED_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Not available</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body class="document"><main class="pairing">
<h1>Only available on the server PC</h1>
<p>The pairing page contains the access token, so it opens only on the PC that
runs the server, at <code>http://127.0.0.1:{port}/pair</code>.</p>
</main></body></html>"""


def create_app(controller: MediaController, token: str) -> FastAPI:
    """Build the FastAPI application around a given controller and token.

    This is the *application factory* pattern: a function that returns a fresh
    app, instead of one global `app` object created at import time. Each call
    gets its own controller, which keeps tests independent of each other.

    Routes are defined inside this function so they can use `controller` and
    `token` directly from the enclosing scope (a *closure*). It is the plainest
    way to give handlers the injected objects.
    """
    app = FastAPI(title="Remote Music Control")
    expected_token = token.encode()

    # --- Authentication ---

    async def require_token(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    ) -> None:
        """A FastAPI *dependency*: runs before every /api route and can reject the request.

        compare_digest takes the same time however many leading characters
        match. A plain `==` stops at the first difference, so an attacker
        timing many requests could learn the token one character at a time
        (a *timing attack*).
        """
        if credentials is not None and secrets.compare_digest(
            credentials.credentials.encode(), expected_token
        ):
            return
        reason = "missing token" if credentials is None else "wrong token"
        logger.warning("rejected %s %s from %s: %s", request.method, request.url.path, client_address(request), reason)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid token",
            # Tells clients which authentication scheme the server expects.
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Error handling ---

    @app.exception_handler(NoMediaSessionError)
    async def no_media_session(request: Request, error: NoMediaSessionError) -> JSONResponse:
        # 409 Conflict: the request itself is fine, but the current state of
        # the player (nothing open) doesn't allow it. One handler here means no
        # endpoint needs its own try/except for this case.
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(error)})

    @app.exception_handler(MediaControllerError)
    async def media_controller_failed(request: Request, error: MediaControllerError) -> JSONResponse:
        # Any other adapter failure (e.g. the player refused a command).
        # 502 Bad Gateway: we are a gateway to the player, and the player failed.
        # FastAPI picks the most specific handler, so NoMediaSessionError still
        # gets the 409 above.
        logger.warning("%s %s failed: %s", request.method, request.url.path, error)
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(error)})

    # --- Middleware ---
    #
    # *Middleware* wraps every request: code here runs before and after the
    # route handler. Each function below does one job.

    @app.middleware("http")
    async def log_requests_and_unexpected_errors(request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # A bug or an unforeseen failure (e.g. a Windows API error nobody
            # anticipated). The full traceback goes to the server log; the
            # client gets a generic message that reveals nothing internal.
            logger.exception("unhandled error in %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "internal server error (see the server log)"},
            )
        # Log requests that change something. GETs are skipped: the web page
        # polls /api/state every second and would flood the log.
        if request.method != "GET" and request.url.path.startswith("/api"):
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s -> %d in %.0f ms (from %s)",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                client_address(request),
            )
        return response

    @app.middleware("http")
    async def web_page_headers(request: Request, call_next):
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            # "no-cache" doesn't disable caching — it tells the browser to
            # check with the server before reusing a stored copy ("304 Not
            # Modified" if unchanged), so an updated app.js is never stale.
            response.headers.setdefault("Cache-Control", "no-cache")
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            # Don't let the browser guess a file's type from its contents.
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    # --- Public routes ---

    @app.get("/health")
    async def health() -> dict[str, str]:
        # A *liveness check*: answers "is the server process up and serving?"
        # It deliberately doesn't touch the media player, so a closed browser
        # doesn't make the server look dead. Public, so it needs no token.
        return {"status": "ok"}

    # --- API routes: all require the token ---

    # An APIRouter groups routes under a shared prefix. `dependencies` applies
    # require_token to every route in the group, so none can be forgotten.
    api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    async def read_volume() -> VolumeResponse:
        return VolumeResponse(volume=await controller.get_volume(), muted=await controller.is_muted())

    @api.get("/state")
    async def get_state() -> StateResponse:
        now = await controller.now_playing()
        if now is None:
            return StateResponse(now_playing=None, volume=None, muted=None)
        # If the session disappears between these calls, the 409 handler
        # answers instead — rare, and the client simply polls again.
        return StateResponse(
            now_playing=now,
            volume=await controller.get_volume(),
            muted=await controller.is_muted(),
        )

    # Transport actions: no response body, just 204 No Content.

    @api.post("/play", status_code=status.HTTP_204_NO_CONTENT)
    async def play() -> None:
        await controller.play()

    @api.post("/pause", status_code=status.HTTP_204_NO_CONTENT)
    async def pause() -> None:
        await controller.pause()

    @api.post("/play-pause", status_code=status.HTTP_204_NO_CONTENT)
    async def toggle_play_pause() -> None:
        await controller.toggle_play_pause()

    @api.post("/next", status_code=status.HTTP_204_NO_CONTENT)
    async def next_track() -> None:
        await controller.next_track()

    @api.post("/previous", status_code=status.HTTP_204_NO_CONTENT)
    async def previous_track() -> None:
        await controller.previous_track()

    # Volume: every endpoint answers with the resulting volume.

    @api.get("/volume")
    async def get_volume() -> VolumeResponse:
        return await read_volume()

    @api.put("/volume")
    async def set_volume(body: SetVolumeRequest) -> VolumeResponse:
        await controller.set_volume(body.level)
        return await read_volume()

    @api.post("/volume/up")
    async def volume_up(step: VolumeStep = DEFAULT_VOLUME_STEP) -> VolumeResponse:
        await change_volume(controller, +step)
        return await read_volume()

    @api.post("/volume/down")
    async def volume_down(step: VolumeStep = DEFAULT_VOLUME_STEP) -> VolumeResponse:
        await change_volume(controller, -step)
        return await read_volume()

    @api.put("/mute")
    async def set_muted(body: SetMutedRequest) -> VolumeResponse:
        await controller.set_muted(body.muted)
        return await read_volume()

    app.include_router(api)

    # --- Web page (public: static files, no secrets) ---

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    # --- Pairing page (server PC only: it contains the token) ---

    @app.get("/pair", include_in_schema=False)
    async def pairing_page(request: Request) -> HTMLResponse:
        port = request.url.port or 80  # the port the browser used, i.e. the one we listen on
        if not is_same_pc_request(request):
            logger.warning("refused the pairing page to %s: only served to the server PC", client_address(request))
            return HTMLResponse(PAIRING_REFUSED_PAGE.format(port=port), status_code=status.HTTP_403_FORBIDDEN)
        page = pairing.render_pairing_page(token=token, port=port, network=pairing.current_network())
        # no-store: a page containing the token must not be kept in the browser cache.
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    # Everything else in web/ (CSS, JS) is served under /static/<filename>.
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    return app
