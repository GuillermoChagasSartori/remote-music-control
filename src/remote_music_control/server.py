"""Server entry point: reads config, builds the controller, starts uvicorn.

This module is the *composition root* — the single place where concrete
classes are chosen and wired together. Every other module works with
abstractions; only here do we decide "use the fake" or "use Windows".
Run it with the `music-server` command.
"""

import sys

import uvicorn

from .api import create_app
from .config import load_server_settings
from .media_controller import MediaController


def build_controller(name: str) -> MediaController:
    """Return the adapter selected by configuration (a simple *factory function*)."""
    if name == "fake":
        # Imported here rather than at the top so each adapter's dependencies
        # load only when that adapter is chosen. This matters in Phase 4: the
        # Windows adapter imports packages that don't exist on Linux.
        from .adapters.fake import FakeMediaController

        return FakeMediaController()
    raise ValueError(f"unknown controller {name!r}")


def main() -> None:
    try:
        settings = load_server_settings()
        controller = build_controller(settings.controller)
    except ValueError as error:
        # A config mistake gets a one-line message, not a Python traceback.
        sys.exit(f"music-server: configuration error: {error}")

    app = create_app(controller)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
