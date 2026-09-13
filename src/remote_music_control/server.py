"""Server entry point: `music-server` runs the server, `music-server init` sets it up.

This module is the *composition root* — the single place where concrete
classes are chosen and wired together. Every other module works with
abstractions; only here do we decide "use the fake" or "use Windows".
"""

import argparse
import logging
import socket
import sys

import uvicorn

from .api import create_app
from .config import (
    DEFAULT_PORT,
    ConfigError,
    ServerSettings,
    create_config_file,
    default_config_path,
    generate_token,
    load_server_settings,
)
from .media_controller import MediaController

# A fixed name rather than __name__: run with `python -m`, __name__ would be
# "__main__", which says nothing in the log.
logger = logging.getLogger("remote_music_control.server")


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
    raise ConfigError(f"unknown controller {settings.controller!r}")


def configure_logging(level: str) -> None:
    # When stderr is redirected to a file on Windows, Python defaults to the
    # legacy cp1252 encoding and crashes on track titles like "花の専門店".
    # Forcing UTF-8 makes logging safe wherever the output goes.
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def run(settings: ServerSettings) -> None:
    configure_logging(settings.log_level)
    controller = build_controller(settings)
    app = create_app(controller, token=settings.token)
    logger.info(
        "starting with %s on %s:%d", type(controller).__name__, settings.host, settings.port
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        # log_config=None: don't let uvicorn install its own log handlers, so
        # its messages go through the format configured above.
        log_config=None,
        # Access logs off: the web page polls every second, which would write
        # ~86,000 lines a day. api.py logs the requests that change something.
        access_log=False,
    )


def init() -> int:
    """Create the config file with a fresh token (never overwrites an existing one)."""
    path = default_config_path()
    if path.exists():
        print(f"music-server: {path} already exists; leaving it unchanged.", file=sys.stderr)
        return 1
    token = generate_token()
    create_config_file(
        path,
        [
            "# Remote Music Control configuration. Keep this file private.",
            "# Real environment variables with the same names take precedence.",
            f"RMC_TOKEN={token}",
            "",
            "# On the Windows PC, uncomment these to control the browser from the LAN:",
            "# RMC_CONTROLLER=windows",
            "# RMC_HOST=0.0.0.0",
            "",
            "# RMC_PORT=8000",
            "# RMC_PLAYER_APPS=chrome.exe,firefox.exe",
            "# RMC_LOG_LEVEL=INFO",
        ],
    )
    # mDNS name: most home networks resolve "<computer name>.local" to this PC.
    host = f"{socket.gethostname().lower()}.local"
    print(f"Created {path}")
    print()
    print("Token for clients (put it in their config file as RMC_TOKEN):")
    print(f"  {token}")
    print()
    print("Pairing link for a browser or phone (opens the page and saves the token):")
    print(f"  http://{host}:{DEFAULT_PORT}/#token={token}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="music-server", description="Remote Music Control server.")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser("init", help="create the config file with a new token")
    args = parser.parse_args(argv)

    if args.command == "init":
        return init()

    try:
        settings = load_server_settings()
        run(settings)
    except (ConfigError, ImportError) as error:
        # A config mistake gets a one-line message, not a Python traceback.
        print(f"music-server: configuration error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
