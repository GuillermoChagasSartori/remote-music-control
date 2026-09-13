"""The Windows app: YouTube Music in a window, with the server inside (ADR 0014).

This module is the app's *composition root*: it picks the real adapters and
wires the window, the server and the tray icon together. The pieces themselves
live in the other modules of this package.

Threads, since several things must run at once:

- **main thread:** the window (pywebview requires it);
- **http-server:** uvicorn with the API, the web page and the adapters;
- **tray icon:** pystray's loop;
- **show-requests:** waits for another copy of the app asking to show the window.
"""

import argparse
import ctypes
import logging
import os
import sys
import webbrowser

from ..api import create_app
from ..config import (
    APP_DEFAULT_HOST,
    ConfigError,
    default_browser_profile_path,
    default_config_path,
    default_log_path,
    ensure_config_file,
    load_server_settings,
)
from ..server import configure_logging, report_startup_error
from .background_server import BackgroundServer, ServerStartError
from .page import YOUTUBE_MUSIC_HOST, WebViewPage
from .texts import Texts, system_texts
from .window_actions import WindowActions

logger = logging.getLogger("remote_music_control.app")

YOUTUBE_MUSIC_URL = f"https://{YOUTUBE_MUSIC_HOST}/"
# The WebView2 process that plays the audio and publishes the media session.
PLAYER_PROCESS_NAME = "msedgewebview2.exe"

MESSAGE_BOX_ERROR_ICON = 0x10


def show_error(texts: Texts, error: object) -> None:
    """A Windows message box: the app has no console, so errors must be shown."""
    message = texts.start_failed.format(error=error, log=default_log_path())
    ctypes.windll.user32.MessageBoxW(None, message, texts.start_failed_title, MESSAGE_BOX_ERROR_ICON)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="remote-music-control", description="Remote Music Control app.")
    parser.add_argument(
        "--minimized", action="store_true", help="start in the tray, without showing the window (used at logon)"
    )
    args = parser.parse_args(argv)
    texts = system_texts()

    # Imported here, not at the top, so the rest of the package (and its
    # tests) can be imported on Linux, where these Windows-only modules fail.
    import webview

    from .single_instance import SingleInstance
    from .tray import Tray

    instance = SingleInstance()
    if not instance.is_first:
        instance.ask_first_instance_to_show()
        return 0

    first_run = ensure_config_file(default_config_path())
    try:
        settings = load_server_settings(default_host=APP_DEFAULT_HOST)
    except ConfigError as error:
        report_startup_error(f"configuration error: {error}")
        show_error(texts, error)
        return 1
    # Always a file: the app has no console to read, and depending on how it was
    # launched Python may still have an invisible stderr that would swallow the log.
    configure_logging(settings.log_level, settings.log_file or default_log_path())
    logger.info("starting the app (first run: %s)", first_run)

    window = webview.create_window(
        texts.window_title,
        YOUTUBE_MUSIC_URL,
        width=1200,
        height=820,
        min_size=(720, 540),
        hidden=args.minimized,
    )
    page = WebViewPage(window)
    window.events.before_load += page.on_before_load
    window.events.loaded += page.on_loaded

    def build_app():
        # Runs on the server's thread (see BackgroundServer). The Windows
        # adapter is imported here for the same reason.
        from ..adapters.page_library import PageLibraryController
        from ..adapters.windows import WindowsMediaController

        controller = WindowsMediaController(player_apps=(PLAYER_PROCESS_NAME,), owner_pid=os.getpid())
        return create_app(controller, token=settings.token, library=PageLibraryController(page))

    server = BackgroundServer(build_app, settings.host, settings.port)
    try:
        server.start()
    except ServerStartError as error:
        logger.error("%s", error)
        show_error(texts, error)
        return 1

    pairing_url = f"http://127.0.0.1:{settings.port}/pair"
    tray = Tray(
        texts,
        on_show=lambda: actions.show(),
        on_pair=lambda: webbrowser.open(pairing_url),
        on_quit=lambda: actions.quit(),
    )
    actions = WindowActions(window, tray.notify, texts)
    window.events.closing += actions.on_closing
    instance.call_when_asked_to_show(actions.show)
    tray.start()
    if first_run:
        # The first time, show how to connect a phone; later it's in the tray menu.
        webbrowser.open(pairing_url)

    try:
        # Blocks until the window is destroyed (Quit in the tray menu).
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(default_browser_profile_path()))
    finally:
        logger.info("quitting")
        tray.stop()
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
