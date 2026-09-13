"""WebViewPage: the YouTubeMusicPage interface, implemented with a pywebview window.

The server's event loop and the window live on different threads: pywebview
runs the window on the program's main thread (Windows requires it), uvicorn
runs the server on a background thread. This class is the bridge between them.
"""

import asyncio
import threading
from typing import Any, Protocol

from ..library import LibraryError, LibraryUnavailableError

YOUTUBE_MUSIC_HOST = "music.youtube.com"

# Answer "is the page ready?" quickly: the web page asks it on every refresh.
READY_CHECK_TIMEOUT_SECONDS = 3.0

READY_CHECK_SCRIPT = f"location.hostname === {YOUTUBE_MUSIC_HOST!r} && typeof ytcfg !== 'undefined'"


class ScriptWindow(Protocol):
    """The part of pywebview's Window this class uses (tests pass a stand-in)."""

    def evaluate_js(self, script: str, callback: Any = None) -> Any: ...


class WebViewPage:
    def __init__(self, window: ScriptWindow) -> None:
        self._window = window
        # Set by the window's "loaded" event, cleared when it navigates away.
        # Before the first load pywebview's evaluate_js would wait for the
        # page instead of answering, so nothing is sent until then.
        self._loaded = threading.Event()

    def on_loaded(self, *_: Any) -> None:
        self._loaded.set()

    def on_before_load(self, *_: Any) -> None:
        self._loaded.clear()

    async def is_ready(self) -> bool:
        try:
            return await asyncio.wait_for(self.evaluate(READY_CHECK_SCRIPT), READY_CHECK_TIMEOUT_SECONDS) is True
        except (LibraryError, TimeoutError, asyncio.TimeoutError):
            return False

    async def evaluate(self, script: str) -> Any:
        """Evaluate `script` in the page and wait for its value (see YouTubeMusicPage).

        pywebview hands the value of a Promise to a callback, on one of its own
        threads, while a plain value is returned directly and the callback is
        never called — and never unregistered, which would leak one entry per
        call. So the script is always wrapped in `Promise.resolve(...)`, and the
        callback moves the value onto the server's event loop with
        `call_soon_threadsafe`, the one asyncio method meant to be called from
        another thread.
        """
        if not self._loaded.is_set():
            raise LibraryUnavailableError("the YouTube Music window hasn't loaded yet")

        loop = asyncio.get_running_loop()
        answer: asyncio.Future = loop.create_future()

        def deliver(value: Any) -> None:
            loop.call_soon_threadsafe(_resolve, answer, value)

        try:
            # evaluate_js blocks until the window has *started* the script, so it
            # runs in a worker thread to keep the event loop free meanwhile.
            await asyncio.to_thread(self._window.evaluate_js, f"Promise.resolve({script})", deliver)
        except Exception as error:  # the window closed, or the script didn't parse
            raise LibraryError(f"couldn't run code in the YouTube Music window: {error}") from error
        return await answer


def _resolve(future: asyncio.Future, value: Any) -> None:
    # The caller may have stopped waiting (a timeout) before the value arrived.
    if not future.done():
        future.set_result(value)
