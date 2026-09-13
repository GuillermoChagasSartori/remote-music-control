"""Server entry point: reads config, builds the controller, starts uvicorn.

This module is the *composition root* — the single place where concrete
classes are chosen and wired together. Every other module works with
abstractions; only here do we decide "use the fake" or "use Windows".
Run it with the `music-server` command.
"""

import sys

import uvicorn

from .api import create_app
from .config import ServerSettings, load_server_settings
from .media_controller import MediaController


def build_controller(settings: ServerSettings) -> MediaController:
    """Return the adapter selected by configuration (a simple *factory function*)."""
    # Adapters are imported inside their branch rather than at the top, so each
    # adapter's dependencies load only when that adapter is chosen. The Windows
    # adapter imports packages that don't exist on Linux.
    if settings.controller == "fake":
        from .adapters.fake import FakeMediaController

        return FakeMediaController()
    if settings.controller == "windows":
        from .adapters.windows import WindowsMediaController

        return WindowsMediaController(player_apps=settings.player_apps)
    raise ValueError(f"unknown controller {settings.controller!r}")


def main() -> None:
    try:
        settings = load_server_settings()
        controller = build_controller(settings)
    except (ValueError, ImportError) as error:
        # A config mistake gets a one-line message, not a Python traceback.
        sys.exit(f"music-server: configuration error: {error}")

    app = create_app(controller)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
