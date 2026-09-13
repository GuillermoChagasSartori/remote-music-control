"""Server entry point: `music-server` runs the server, `music-server init` sets it up.

This module is the *composition root* — the single place where concrete
classes are chosen and wired together. Every other module works with
abstractions; only here do we decide "use the fake" or "use Windows".
"""

import argparse
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from .adapters.fake_library import FakeLibraryController
from .api import create_app
from .config import (
    DEFAULT_PORT,
    ConfigError,
    ServerSettings,
    create_config_file,
    default_config_path,
    default_log_path,
    generate_token,
    load_server_settings,
)
from .extension_bridge import ExtensionBridge, ExtensionLibraryController
from .library import LibraryController
from .media_controller import MediaController
from .pairing import lan_ip_address

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
        try:
            from .adapters.windows import WindowsMediaController
        except ImportError as error:
            # On Linux the adapter refuses to import (and its packages aren't
            # installed): that's a settings problem, so report it as one.
            raise ConfigError(f"RMC_CONTROLLER=windows can't be used here: {error}") from error

        return WindowsMediaController(player_apps=settings.player_apps)
    raise ConfigError(f"unknown controller {settings.controller!r}")


def build_library(settings: ServerSettings) -> tuple[LibraryController, ExtensionBridge | None]:
    """Search and the queue: through the Chrome extension on the studio PC, a fake elsewhere.

    Tied to the media controller choice: the extension only makes sense where
    the real browser is (ADR 0013). Returns the bridge too, so the API can
    offer the extension its WebSocket endpoint.
    """
    if settings.controller == "windows":
        bridge = ExtensionBridge()
        return ExtensionLibraryController(bridge), bridge
    return FakeLibraryController(), None


LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
# A rotating log starts a new file when it reaches this size and keeps this
# many old ones (server.log.1 … .3), so it can never fill the disk.
LOG_FILE_MAX_BYTES = 1_000_000
LOG_FILE_BACKUPS = 3


class LockTolerantRotatingFileHandler(RotatingFileHandler):
    """A rotating log file that never loses records when the file is locked.

    Rotating means renaming server.log to server.log.1 (and .1 to .2, and so
    on) and starting a fresh server.log. On Windows a file can't be renamed
    while another program has it open — for example `Get-Content -Wait`
    following the log live, or an antivirus scan. The standard
    RotatingFileHandler then fails on every record: it drops the record, and
    because it shifts the backups *before* discovering the rename fails, each
    attempt also deletes the oldest backup. (Measured on the studio PC: 286 of
    400 lines lost, and two of three backups gone.)

    This version renames the current log first. If that fails, nothing has been
    touched yet: it keeps writing to the same file and tries again once the
    file has grown by another `maxBytes`. Only after the rename succeeds are the
    backups shifted.
    """

    def __init__(self, filename: Path, max_bytes: int, backup_count: int) -> None:
        if backup_count < 1:
            raise ValueError("backup_count must be at least 1")
        super().__init__(filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        # File size at which to try rotating again after a failed attempt.
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
            # Step 1: move the current log aside. This is the step that fails
            # while another program holds the file open.
            os.replace(self.baseFilename, in_progress)
        except OSError:
            self.stream = self._open()  # carry on in the same file
            self._next_attempt_size = self.stream.tell() + self.maxBytes
            return

        # Step 2: shift the backups (.2 -> .3, .1 -> .2); the oldest is overwritten.
        for number in range(self.backupCount - 1, 0, -1):
            older = f"{self.baseFilename}.{number}"
            if os.path.exists(older):
                os.replace(older, f"{self.baseFilename}.{number + 1}")
        os.replace(in_progress, f"{self.baseFilename}.1")

        self._next_attempt_size = 0
        self.stream = self._open()


def log_destination(configured_file: Path | None, stderr) -> Path | None:
    """Decide where logs go: a file path, or None for stderr.

    Started at logon, the server runs under pythonw.exe — the Windows Python
    that opens no console window — and there `sys.stderr` is None. Logging (or
    printing) to it would crash, so without an explicit RMC_LOG_FILE the log
    then goes to the default file next to the config file.
    """
    if configured_file is not None:
        return configured_file
    if stderr is None:
        return default_log_path()
    return None


def configure_logging(level: str, log_file: Path | None) -> None:
    destination = log_destination(log_file, sys.stderr)
    if destination is None:
        # When stderr is redirected to a file on Windows, Python defaults to the
        # legacy cp1252 encoding and crashes on track titles like "花の専門店".
        # Forcing UTF-8 makes logging safe wherever the output goes.
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handler = LockTolerantRotatingFileHandler(
            destination, max_bytes=LOG_FILE_MAX_BYTES, backup_count=LOG_FILE_BACKUPS
        )
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=[handler])


def report_startup_error(message: str) -> None:
    """Show an error that happens before logging is set up.

    On a console it is printed. Under pythonw there is nowhere to print, so it
    is appended to the default log file — otherwise a broken config file would
    make the server at logon fail with no trace at all.
    """
    line = f"music-server: {message}"
    if sys.stderr is not None:
        print(line, file=sys.stderr)
        return
    path = default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(line + "\n")


def run(settings: ServerSettings) -> None:
    controller = build_controller(settings)
    library, extension_bridge = build_library(settings)
    app = create_app(
        controller,
        token=settings.token,
        library=library,
        extension_bridge=extension_bridge,
        extension_id=settings.extension_id,
    )
    logger.info(
        "starting with %s on %s:%d", type(controller).__name__, settings.host, settings.port
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        # log_config=None: don't let uvicorn install its own log handlers, so
        # its messages go through the handler configured above.
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
            "# Log file; default is the console, or server.log next to this file when there is none:",
            "# RMC_LOG_FILE=C:\\path\\to\\server.log",
        ],
    )
    print(f"Created {path}")
    print()
    print("Token for clients (put it in their config file as RMC_TOKEN):")
    print(f"  {token}")
    print()
    print("Pairing links for a browser or phone (open one: it shows the player and saves the token).")
    # Two forms, because neither works everywhere: the mDNS name survives the
    # PC getting a new IP but Android browsers can't resolve ".local" names;
    # the IP works on every device but changes unless reserved in the router.
    print(f"  by name (desktops, iPhone): http://{socket.gethostname().lower()}.local:{DEFAULT_PORT}/#token={token}")
    ip_address = lan_ip_address()
    if ip_address:
        print(f"  by IP (Android, anything):  http://{ip_address}:{DEFAULT_PORT}/#token={token}")
    print()
    print(f"Later, while the server runs, open http://127.0.0.1:{DEFAULT_PORT}/pair on this PC")
    print("to show these links as QR codes.")
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
    except ConfigError as error:
        # A config mistake gets a one-line message, not a Python traceback.
        report_startup_error(f"configuration error: {error}")
        return 1

    configure_logging(settings.log_level, settings.log_file)
    try:
        run(settings)
    except ConfigError as error:
        logger.error("configuration error: %s", error)
        return 1
    except Exception:
        # Anything unforeseen: record it with its traceback, and exit with a
        # failure code, as a program should when it didn't do its job. (The
        # logon task restarts the server within a minute either way: its
        # watchdog trigger doesn't depend on the exit code, see ADR 0011.)
        logger.exception("server stopped because of an unexpected error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
