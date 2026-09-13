"""The icon in the Windows notification area ("system tray") and its menu.

pystray draws the icon and menu with the Windows API. Its loop runs on its own
thread; the menu callbacks run there too, so they only ask the window to do
things (pywebview's window methods may be called from any thread).
"""

from collections.abc import Callable
from pathlib import Path

import pystray
from PIL import Image

from .texts import Texts

ICON_FILE = Path(__file__).parent / "icon.ico"


class Tray:
    def __init__(
        self,
        texts: Texts,
        on_show: Callable[[], None],
        on_pair: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        menu = pystray.Menu(
            # default=True: also runs when the icon itself is clicked.
            pystray.MenuItem(texts.tray_show, lambda: on_show(), default=True),
            pystray.MenuItem(texts.tray_pair, lambda: on_pair()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(texts.tray_quit, lambda: on_quit()),
        )
        self._icon = pystray.Icon("remote-music-control", Image.open(ICON_FILE), texts.window_title, menu)

    def start(self) -> None:
        # run_detached() starts the icon without taking over this thread.
        self._icon.run_detached()

    def notify(self, title: str, message: str) -> None:
        self._icon.notify(message, title)

    def stop(self) -> None:
        self._icon.stop()
