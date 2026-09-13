"""What the window does when it is closed, shown again, or the app quits."""

from collections.abc import Callable
from typing import Any

from .texts import Texts


class WindowActions:
    """The window's behaviour: hide instead of close, show on request, quit from the tray."""

    def __init__(self, window: Any, tray_notify: Callable[[str, str], None], texts: Texts) -> None:
        """`window`: a pywebview Window. `tray_notify(title, message)` shows a tray notice."""
        self._window = window
        self._tray_notify = tray_notify
        self._texts = texts
        self._quitting = False
        self._told_about_tray = False

    def on_closing(self) -> bool:
        """pywebview calls this when the window's X is clicked; False cancels closing."""
        if self._quitting:
            return True
        self._window.hide()
        if not self._told_about_tray:
            # Once per run: otherwise the music playing on with no window in
            # sight looks like a bug.
            self._told_about_tray = True
            self._tray_notify(self._texts.still_running_title, self._texts.still_running)
        return False

    def show(self) -> None:
        self._window.show()
        self._window.restore()  # un-minimize, if it was minimized

    def quit(self) -> None:
        self._quitting = True
        self._window.destroy()
