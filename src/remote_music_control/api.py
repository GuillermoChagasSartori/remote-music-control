"""HTTP API: translates HTTP requests into MediaController calls.

This layer depends only on the MediaController *port*, never on a specific
adapter. The controller is handed in from outside (see server.py) — that is
*dependency injection*: a component receives the objects it needs instead of
creating them itself, so a test can pass in a fake and the production server
can pass in the real thing.
"""

from fastapi import FastAPI

from .media_controller import MediaController


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

    @app.get("/health")
    async def health() -> dict[str, str]:
        # A *liveness check*: answers "is the server process up and serving?"
        # It deliberately doesn't touch the media player, so a closed browser
        # doesn't make the server look dead.
        return {"status": "ok", "controller": type(controller).__name__}

    return app
