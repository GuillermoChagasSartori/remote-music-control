"""PageLibraryController: search and the queue, by running code inside the YouTube Music page.

The app shows YouTube Music in its own window (ADR 0014), so the server can
ask that window to evaluate JavaScript in the page directly. The functions that
know YouTube Music's internals are in youtube-music.js, next to this file; this
adapter turns a port call such as `search("nujabes")` into a script that calls
one of them, and checks what comes back.

The window itself is behind a small interface, `YouTubeMusicPage`, so this
module doesn't depend on the window library (pywebview): the app hands in the
real page, tests hand in a stand-in. That is the same *dependency injection* as
in api.py, one level further down.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol

from ..library import (
    InsertPosition,
    LibraryController,
    LibraryError,
    Queue,
    QueueItem,
    QueueItemNotFoundError,
    Song,
)

PAGE_FUNCTIONS_FILE = Path(__file__).parent / "youtube-music.js"

# Long enough for "add to queue" (a request to YouTube Music's servers from the
# page, then a store update) on a slow moment; short enough that a stuck page
# is reported instead of hanging the client.
CALL_TIMEOUT_SECONDS = 15.0

# Error kinds the page functions may report, and the port's exception for each.
# Any other kind ("page_changed") becomes a plain LibraryError.
ERRORS_BY_KIND: dict[str, type[LibraryError]] = {
    "not_found": QueueItemNotFoundError,
}


class YouTubeMusicPage(Protocol):
    """What the adapter needs from the window showing YouTube Music.

    A *Protocol* describes the methods an object must have without requiring
    it to inherit from anything (*structural typing*, "duck typing" that type
    checkers can verify).
    """

    async def is_ready(self) -> bool:
        """True when the window is open and showing YouTube Music."""

    async def evaluate(self, script: str) -> Any:
        """Evaluate a script in the page and return its result, decoded from JSON.

        If the script's value is a Promise, the page waits for it. Raises
        LibraryUnavailableError when there is no page to run it in.
        """


def page_function_script(source: str, function: str, args: list[Any]) -> str:
    """The script that defines the page functions and calls one of them.

    The arguments are written into the script as JSON, which is also valid
    JavaScript — so a search for `"); alert("hi` stays a harmless string
    instead of becoming code (the same idea as parameterized SQL queries,
    preventing *code injection*).

    Everything runs inside an arrow function called at once (an *IIFE*,
    immediately invoked function expression), so nothing leaks into the
    page's global variables.
    """
    return (
        "(() => {\n"
        f"{source}\n"
        f"return PAGE_FUNCTIONS[{json.dumps(function)}](...{json.dumps(args)});\n"
        "})()"
    )


class PageLibraryController(LibraryController):
    def __init__(
        self,
        page: YouTubeMusicPage,
        source: str | None = None,
        call_timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> None:
        self._page = page
        # Read once: the file is part of the installed package and never changes while running.
        self._source = source if source is not None else PAGE_FUNCTIONS_FILE.read_text(encoding="utf-8")
        self._call_timeout = call_timeout

    async def _call(self, function: str, *args: Any) -> Any:
        """Run one page function and return its value, or raise the matching port error."""
        script = page_function_script(self._source, function, list(args))
        try:
            outcome = await asyncio.wait_for(self._page.evaluate(script), self._call_timeout)
        except (TimeoutError, asyncio.TimeoutError):
            raise LibraryError(
                f"YouTube Music didn't answer '{function}' within {self._call_timeout:.0f} s"
            ) from None
        if not isinstance(outcome, dict):
            raise LibraryError(f"no result from YouTube Music for '{function}'")
        if outcome.get("ok") is True:
            return outcome.get("value")
        message = str(outcome.get("message") or f"'{function}' failed in YouTube Music")
        raise ERRORS_BY_KIND.get(outcome.get("kind"), LibraryError)(message)

    async def is_available(self) -> bool:
        return await self._page.is_ready()

    async def search(self, query: str) -> list[Song]:
        return [_song(item) for item in _list(await self._call("search", query))]

    async def get_queue(self) -> Queue:
        value = await self._call("getQueue")
        if not isinstance(value, dict):
            raise LibraryError("unexpected queue from YouTube Music")
        items = tuple(_queue_item(index, item) for index, item in enumerate(_list(value.get("items"))))
        current = next((item.index for item in items if item.is_current), None)
        return Queue(items=items, current_index=current)

    async def jump_to(self, index: int) -> None:
        await self._call("jumpTo", index)

    async def play(self, video_id: str, position: InsertPosition) -> None:
        if position is InsertPosition.NOW:
            await self._call("playNow", video_id)
        else:
            await self._call("addToQueue", video_id, position.value)


# --- Checking what the page sent ----------------------------------------------------------
#
# The page functions read YouTube Music's internals, which can change. Their
# values are checked here so a changed page produces a clear LibraryError
# (HTTP 502), not a confusing crash deeper in the server.


def _list(value: Any) -> list:
    if not isinstance(value, list):
        raise LibraryError("unexpected reply from YouTube Music (expected a list)")
    return value


def _text(item: dict, key: str, required: bool = False) -> str | None:
    value = item.get(key)
    if isinstance(value, str) and value:
        return value
    if required:
        raise LibraryError(f"unexpected reply from YouTube Music (missing {key})")
    return None


def _song(item: Any) -> Song:
    if not isinstance(item, dict):
        raise LibraryError("unexpected song in YouTube Music's reply")
    return Song(
        video_id=_text(item, "video_id", required=True),
        title=_text(item, "title", required=True),
        artist=_text(item, "artist"),
        duration=_text(item, "duration"),
    )


def _queue_item(index: int, item: Any) -> QueueItem:
    song = _song(item)
    return QueueItem(
        index=index,
        video_id=song.video_id,
        title=song.title,
        artist=song.artist,
        duration=song.duration,
        is_current=item.get("is_current") is True,
        is_autoplay=item.get("is_autoplay") is True,
    )
