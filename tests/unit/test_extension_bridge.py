"""Unit tests for the extension bridge, with an in-memory stand-in for the WebSocket.

Each test runs one asyncio "scenario": the bridge serves the fake socket in a
background task, while the test plays the extension's part by reading the
requests the bridge sends and writing replies.
"""

import asyncio

import pytest

from remote_music_control import extension_bridge
from remote_music_control.extension_bridge import (
    ExtensionBridge,
    ExtensionLibraryController,
    ExtensionProtocolError,
)
from remote_music_control.library import (
    InsertPosition,
    LibraryError,
    LibraryUnavailableError,
    QueueItemNotFoundError,
)

CLOSED = object()


class MemorySocket:
    """Just enough of a WebSocket: messages in, messages out, close."""

    def __init__(self):
        self.incoming: asyncio.Queue = asyncio.Queue()  # extension -> server
        self.sent: asyncio.Queue = asyncio.Queue()  # server -> extension
        self.closed = False

    async def receive_json(self):
        message = await self.incoming.get()
        if message is CLOSED:
            raise ConnectionError("socket closed")
        return message

    async def send_json(self, data):
        if self.closed:
            raise ConnectionError("socket closed")
        self.sent.put_nowait(data)

    async def close(self, code=1000):
        self.closed = True
        self.incoming.put_nowait(CLOSED)


async def connect(bridge, socket=None):
    """Start serving a socket that has said hello; return it and its task."""
    socket = socket or MemorySocket()
    socket.incoming.put_nowait({"type": "hello", "version": "1.0.0"})
    task = asyncio.create_task(bridge.serve(socket))
    for _ in range(100):  # wait until the bridge has taken the connection
        if bridge.connected:
            break
        await asyncio.sleep(0)
    return socket, task


async def reply_to_next_request(socket, **reply):
    request = await socket.sent.get()
    socket.incoming.put_nowait({"type": "response", "id": request["id"], **reply})
    return request


def test_request_without_a_connection_is_unavailable():
    async def scenario():
        with pytest.raises(LibraryUnavailableError, match="not connected"):
            await ExtensionBridge().request("search", {"query": "x"})

    asyncio.run(scenario())


def test_search_round_trip_parses_songs():
    async def scenario():
        bridge = ExtensionBridge()
        socket, task = await connect(bridge)
        library = ExtensionLibraryController(bridge)

        search = asyncio.create_task(library.search("nujabes"))
        request = await reply_to_next_request(
            socket,
            ok=True,
            result=[
                {"video_id": "abc", "title": "Aruarian Dance", "artist": "Nujabes", "duration": "4:05"},
                {"video_id": "def", "title": "Luv(sic)", "artist": None, "duration": ""},
            ],
        )
        songs = await search

        assert request["op"] == "search" and request["args"] == {"query": "nujabes"}
        assert [song.title for song in songs] == ["Aruarian Dance", "Luv(sic)"]
        assert songs[1].artist is None and songs[1].duration is None
        assert bridge.extension_version == "1.0.0"
        await socket.close()
        await task

    asyncio.run(scenario())


def test_queue_reply_gives_indexes_and_the_current_item():
    async def scenario():
        bridge = ExtensionBridge()
        socket, task = await connect(bridge)
        queue_request = asyncio.create_task(ExtensionLibraryController(bridge).get_queue())
        await reply_to_next_request(
            socket,
            ok=True,
            result={"items": [
                {"video_id": "a", "title": "One", "is_current": False},
                {"video_id": "b", "title": "Two", "is_current": True},
                {"video_id": "c", "title": "Three", "is_current": False, "is_autoplay": True},
            ]},
        )
        queue = await queue_request
        assert [item.index for item in queue.items] == [0, 1, 2]
        assert queue.current_index == 1
        assert [item.is_autoplay for item in queue.items] == [False, False, True]
        await socket.close()
        await task

    asyncio.run(scenario())


def test_jump_and_play_send_the_right_requests():
    async def scenario():
        bridge = ExtensionBridge()
        socket, task = await connect(bridge)
        library = ExtensionLibraryController(bridge)

        jump = asyncio.create_task(library.jump_to(3))
        jump_request = await reply_to_next_request(socket, ok=True, result=None)
        await jump
        play = asyncio.create_task(library.play("xyz", InsertPosition.NEXT))
        play_request = await reply_to_next_request(socket, ok=True, result=None)
        await play

        assert (jump_request["op"], jump_request["args"]) == ("jump", {"index": 3})
        assert (play_request["op"], play_request["args"]) == ("play", {"video_id": "xyz", "position": "next"})
        await socket.close()
        await task

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("kind", "exception"),
    [("no_tab", LibraryUnavailableError), ("not_found", QueueItemNotFoundError), ("page_changed", LibraryError)],
)
def test_error_kinds_become_port_exceptions(kind, exception):
    async def scenario():
        bridge = ExtensionBridge()
        socket, task = await connect(bridge)
        request = asyncio.create_task(bridge.request("jump", {"index": 9}))
        await reply_to_next_request(socket, ok=False, error={"kind": kind, "message": "explained"})
        with pytest.raises(exception, match="explained"):
            await request
        await socket.close()
        await task

    asyncio.run(scenario())


def test_malformed_reply_is_a_library_error():
    async def scenario():
        bridge = ExtensionBridge()
        socket, task = await connect(bridge)
        search = asyncio.create_task(ExtensionLibraryController(bridge).search("x"))
        await reply_to_next_request(socket, ok=True, result=[{"title": "no video id"}])
        with pytest.raises(LibraryError, match="missing video_id"):
            await search
        await socket.close()
        await task

    asyncio.run(scenario())


def test_no_answer_times_out():
    async def scenario():
        bridge = ExtensionBridge(request_timeout=0.05)
        socket, task = await connect(bridge)
        with pytest.raises(LibraryError, match="didn't answer"):
            await bridge.request("search", {"query": "x"})
        await socket.close()
        await task

    asyncio.run(scenario())


def test_disconnect_fails_waiting_requests_and_marks_unavailable():
    async def scenario():
        bridge = ExtensionBridge()
        socket, task = await connect(bridge)
        request = asyncio.create_task(bridge.request("search", {"query": "x"}))
        await socket.sent.get()
        await socket.close()
        await task
        with pytest.raises(LibraryUnavailableError, match="disconnected"):
            await request
        assert bridge.connected is False

    asyncio.run(scenario())


def test_keepalives_are_ignored():
    async def scenario():
        bridge = ExtensionBridge()
        socket, task = await connect(bridge)
        socket.incoming.put_nowait({"type": "keepalive"})
        request = asyncio.create_task(bridge.request("get_queue", {}))
        await reply_to_next_request(socket, ok=True, result={"items": []})
        assert await request == {"items": []}
        await socket.close()
        await task

    asyncio.run(scenario())


def test_a_new_connection_replaces_the_old_one():
    async def scenario():
        bridge = ExtensionBridge()
        old_socket, old_task = await connect(bridge)
        pending = asyncio.create_task(bridge.request("search", {"query": "x"}))
        await old_socket.sent.get()

        new_socket = MemorySocket()
        new_socket.incoming.put_nowait({"type": "hello", "version": "1.0.1"})
        new_task = asyncio.create_task(bridge.serve(new_socket))
        await old_task  # the old connection was closed by the bridge

        assert old_socket.closed
        with pytest.raises(LibraryUnavailableError, match="reconnected"):
            await pending
        assert bridge.connected and bridge.extension_version == "1.0.1"
        await new_socket.close()
        await new_task

    asyncio.run(scenario())


def test_first_message_must_be_hello():
    async def scenario():
        socket = MemorySocket()
        socket.incoming.put_nowait({"type": "response", "id": 1})
        with pytest.raises(ExtensionProtocolError, match="hello"):
            await ExtensionBridge().serve(socket)

    asyncio.run(scenario())


def test_silent_connection_is_dropped(monkeypatch):
    monkeypatch.setattr(extension_bridge, "HELLO_TIMEOUT_SECONDS", 0.05)

    async def scenario():
        with pytest.raises(ExtensionProtocolError, match="no hello"):
            await ExtensionBridge().serve(MemorySocket())

    asyncio.run(scenario())
