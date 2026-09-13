"""The library through the Chrome extension: a request/response bridge over one WebSocket.

The server can't reach into Chrome; the extension connects *to* the server and
keeps that connection open (ADR 0013). This module turns that connection into
ordinary async method calls: `await bridge.request("search", {...})` sends a
request message and waits for the matching reply. Matching replies to requests
by id over a message channel is often called *RPC over WebSocket*.

Messages are JSON objects:

  extension → server   {"type": "hello", "version": "1.0.0"}             first message
  server → extension   {"type": "request", "id": 7, "op": "search", "args": {"query": "..."}}
  extension → server   {"type": "response", "id": 7, "ok": true, "result": [...]}
                       {"type": "response", "id": 7, "ok": false,
                        "error": {"kind": "no_tab", "message": "..."}}
  extension → server   {"type": "keepalive"}                              every 20 s

Who may connect is decided in api.py before this code runs.
"""

import asyncio
import itertools
import logging
from typing import Any, Protocol

from .library import (
    InsertPosition,
    LibraryController,
    LibraryError,
    LibraryUnavailableError,
    Queue,
    QueueItem,
    QueueItemNotFoundError,
    Song,
)

logger = logging.getLogger(__name__)

# Long enough for "add to queue" (a request to YouTube Music's servers from the
# page, then a store update) on a slow moment; short enough that a stuck tab is
# reported instead of hanging the client.
REQUEST_TIMEOUT_SECONDS = 15.0
HELLO_TIMEOUT_SECONDS = 5.0

# Error kinds the extension may report, and the port's exception for each.
ERRORS_BY_KIND: dict[str, type[LibraryError]] = {
    "no_tab": LibraryUnavailableError,
    "not_found": QueueItemNotFoundError,
}


class JsonSocket(Protocol):
    """What the bridge needs from a WebSocket. Starlette's WebSocket has these
    methods; tests use a small in-memory stand-in. Receiving raises when the
    connection closes."""

    async def receive_json(self) -> Any: ...

    async def send_json(self, data: Any) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


class ExtensionProtocolError(Exception):
    """The other side didn't follow the protocol (e.g. no hello)."""


class ExtensionBridge:
    def __init__(self, request_timeout: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self._socket: JsonSocket | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._request_ids = itertools.count(1)
        self._request_timeout = request_timeout
        self.extension_version: str | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    async def serve(self, socket: JsonSocket) -> None:
        """Handle one extension connection until it closes.

        A new connection replaces an older one (the extension reconnected, e.g.
        after Chrome restarted its service worker).
        """
        try:
            hello = await asyncio.wait_for(socket.receive_json(), HELLO_TIMEOUT_SECONDS)
        except (TimeoutError, asyncio.TimeoutError):
            raise ExtensionProtocolError("no hello message within the time limit") from None
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            raise ExtensionProtocolError(f"expected a hello message, got {hello!r:.100}")

        previous = self._socket
        self._socket = socket
        self.extension_version = str(hello.get("version"))
        if previous is not None:
            self._fail_pending("the Chrome extension reconnected")
            try:
                await previous.close()
            except Exception:  # already closed — nothing to do
                pass
        logger.info("Chrome extension connected (version %s)", self.extension_version)

        try:
            while True:
                self._handle(await socket.receive_json())
        except Exception as error:
            logger.info("Chrome extension disconnected (%s)", type(error).__name__)
        finally:
            if self._socket is socket:
                self._socket = None
                self._fail_pending("the Chrome extension disconnected")

    def _handle(self, message: Any) -> None:
        if not isinstance(message, dict) or message.get("type") == "keepalive":
            return
        if message.get("type") == "response":
            future = self._pending.get(message.get("id"))
            if future is not None and not future.done():
                future.set_result(message)

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(LibraryUnavailableError(reason))
        self._pending.clear()

    async def request(self, op: str, args: dict[str, Any]) -> Any:
        """Send one request to the extension and return its result."""
        socket = self._socket
        if socket is None:
            raise LibraryUnavailableError(
                "the Chrome extension is not connected — is Chrome open on the studio PC with the extension enabled?"
            )
        request_id = next(self._request_ids)
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            try:
                await socket.send_json({"type": "request", "id": request_id, "op": op, "args": args})
            except Exception as error:
                raise LibraryUnavailableError("the Chrome extension connection was lost") from error
            try:
                reply = await asyncio.wait_for(future, self._request_timeout)
            except (TimeoutError, asyncio.TimeoutError):
                raise LibraryError(
                    f"the Chrome extension didn't answer '{op}' within {self._request_timeout:.0f} s"
                ) from None
        finally:
            self._pending.pop(request_id, None)

        if reply.get("ok"):
            return reply.get("result")
        error = reply.get("error") if isinstance(reply.get("error"), dict) else {}
        message = str(error.get("message") or f"'{op}' failed in the Chrome extension")
        raise ERRORS_BY_KIND.get(error.get("kind"), LibraryError)(message)


class ExtensionLibraryController(LibraryController):
    """The LibraryController port, implemented by asking the extension."""

    def __init__(self, bridge: ExtensionBridge) -> None:
        self._bridge = bridge

    async def is_available(self) -> bool:
        return self._bridge.connected

    async def search(self, query: str) -> list[Song]:
        result = await self._bridge.request("search", {"query": query})
        return [_song(item) for item in _list(result)]

    async def get_queue(self) -> Queue:
        result = await self._bridge.request("get_queue", {})
        if not isinstance(result, dict):
            raise LibraryError("unexpected queue reply from the Chrome extension")
        items = tuple(_queue_item(index, item) for index, item in enumerate(_list(result.get("items"))))
        current = next((item.index for item in items if item.is_current), None)
        return Queue(items=items, current_index=current)

    async def jump_to(self, index: int) -> None:
        await self._bridge.request("jump", {"index": index})

    async def play(self, video_id: str, position: InsertPosition) -> None:
        await self._bridge.request("play", {"video_id": video_id, "position": position.value})


# --- Checking what the extension sent -------------------------------------------------
#
# The extension reads YouTube Music's internals, which can change. Replies are
# checked here so a changed page produces a clear LibraryError (502), not a
# confusing crash deeper in the server.


def _list(value: Any) -> list:
    if not isinstance(value, list):
        raise LibraryError("unexpected reply from the Chrome extension (expected a list)")
    return value


def _text(item: dict, key: str, required: bool = False) -> str | None:
    value = item.get(key)
    if isinstance(value, str) and value:
        return value
    if required:
        raise LibraryError(f"unexpected reply from the Chrome extension (missing {key})")
    return None


def _song(item: Any) -> Song:
    if not isinstance(item, dict):
        raise LibraryError("unexpected song in the Chrome extension's reply")
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
