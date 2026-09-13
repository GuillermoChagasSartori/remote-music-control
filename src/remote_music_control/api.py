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

The web page (HTML, CSS, JS in the `web/` folder) is served by this same app,
so there is nothing to install on the client: open the server's address in a
browser. See docs/decisions/0007.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .media_controller import (
    MAX_VOLUME,
    MIN_VOLUME,
    MediaController,
    MediaControllerError,
    NoMediaSessionError,
    NowPlaying,
    change_volume,
)

DEFAULT_VOLUME_STEP = 5

# The web files ship inside the Python package, next to this module, so they
# are installed wherever the package is — no separate path to configure.
WEB_DIR = Path(__file__).parent / "web"


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


def create_app(controller: MediaController) -> FastAPI:
    """Build the FastAPI application around a given controller.

    This is the *application factory* pattern: a function that returns a fresh
    app, instead of one global `app` object created at import time. Each call
    gets its own controller, which keeps tests independent of each other.

    Routes are defined inside this function so they can use `controller`
    directly from the enclosing scope (a *closure*). It is the plainest way to
    give handlers the injected object; FastAPI's `Depends` mechanism would do
    the same with more machinery than this small API needs.
    """
    app = FastAPI(title="Remote Music Control")

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
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(error)})

    @app.get("/health")
    async def health() -> dict[str, str]:
        # A *liveness check*: answers "is the server process up and serving?"
        # It deliberately doesn't touch the media player, so a closed browser
        # doesn't make the server look dead.
        return {"status": "ok", "controller": type(controller).__name__}

    # An APIRouter groups routes under a shared prefix. Keeping the API under
    # /api leaves "/" free for the web page in Phase 3.
    api = APIRouter(prefix="/api")

    async def read_volume() -> VolumeResponse:
        return VolumeResponse(volume=await controller.get_volume(), muted=await controller.is_muted())

    # --- State ---

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

    # --- Transport actions: no response body, just 204 No Content ---
    #
    # They don't return the new state because on the real player the change
    # takes effect asynchronously; clients read it from GET /api/state.

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

    # --- Volume: every endpoint answers with the resulting volume ---

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

    # --- Web page ---

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    # Everything else in web/ (CSS, JS) is served under /static/<filename>.
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.middleware("http")
    async def revalidate_web_files(request: Request, call_next):
        # *Middleware* wraps every request: code here runs before and after the
        # route handler. "no-cache" doesn't disable caching — it tells the
        # browser to check with the server before reusing a stored copy. The
        # server answers "304 Not Modified" (no body) if nothing changed, so it
        # costs almost nothing, and an updated app.js is never served stale.
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    return app
