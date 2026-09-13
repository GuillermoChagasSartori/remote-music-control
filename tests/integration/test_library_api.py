"""Integration tests: the library routes and the extension's WebSocket endpoint."""

import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from remote_music_control.adapters.fake import FakeMediaController
from remote_music_control.api import create_app
from remote_music_control.extension_bridge import ExtensionBridge, ExtensionLibraryController
from remote_music_control.library import LibraryError

from ..support import TOKEN

EXTENSION_ID = "hgchacmedljophnblmbdmogbkafcmdol"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"


# --- Routes, with the fake library -------------------------------------------------------


def test_status_reports_availability(client, library):
    assert client.get("/api/library/status").json() == {"available": True}
    library.available = False
    assert client.get("/api/library/status").json() == {"available": False}


def test_search_returns_songs(client):
    response = client.get("/api/library/search", params={"q": "test patterns"})
    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {"video_id": "fake0000001", "title": "Signal Path", "artist": "The Test Patterns", "duration": "3:12"},
            {"video_id": "fake0000002", "title": "Low Latency", "artist": "The Test Patterns", "duration": "2:48"},
        ]
    }


@pytest.mark.parametrize("params", [{}, {"q": ""}, {"q": "x" * 201}])
def test_search_query_is_validated(client, params):
    assert client.get("/api/library/search", params=params).status_code == 422


def test_queue_and_jump(client):
    queue = client.get("/api/library/queue").json()
    assert queue["current_index"] == 0
    assert queue["items"][1] == {
        "index": 1, "video_id": "fake0000002", "title": "Low Latency",
        "artist": "The Test Patterns", "duration": "2:48", "is_current": False, "is_autoplay": False,
    }

    assert client.post("/api/library/queue/2/play").status_code == 204
    assert client.get("/api/library/queue").json()["current_index"] == 2


def test_jump_to_missing_item_is_404(client):
    response = client.post("/api/library/queue/99/play")
    assert response.status_code == 404
    assert "no queue item 99" in response.json()["detail"]


def test_negative_queue_index_is_rejected(client):
    assert client.post("/api/library/queue/-1/play").status_code == 422


@pytest.mark.parametrize(("position", "expected_index"), [("next", 1), ("end", 4)])
def test_play_next_and_at_end(client, position, expected_index):
    response = client.post("/api/library/play", json={"video_id": "fake0000007", "position": position})
    assert response.status_code == 204
    items = client.get("/api/library/queue").json()["items"]
    assert items[expected_index]["title"] == "Read Your Writes"


def test_play_defaults_to_now(client):
    assert client.post("/api/library/play", json={"video_id": "fake0000008"}).status_code == 204
    queue = client.get("/api/library/queue").json()
    assert (queue["current_index"], queue["items"][0]["title"]) == (0, "Cross-Site Hijack")


@pytest.mark.parametrize(
    "body",
    [{}, {"video_id": ""}, {"video_id": "has spaces"}, {"video_id": "<script>"}, {"video_id": "abc", "position": "later"}],
)
def test_play_request_is_validated(client, body):
    assert client.post("/api/library/play", json=body).status_code == 422


def test_unavailable_library_answers_503(client, library):
    library.available = False
    for response in (
        client.get("/api/library/search", params={"q": "x"}),
        client.get("/api/library/queue"),
        client.post("/api/library/queue/0/play"),
        client.post("/api/library/play", json={"video_id": "abc"}),
    ):
        assert response.status_code == 503
        assert "not connected" in response.json()["detail"]


def test_library_failure_answers_502(client, library, monkeypatch):
    async def broken(query):
        raise LibraryError("YouTube Music's page changed")

    monkeypatch.setattr(library, "search", broken)
    response = client.get("/api/library/search", params={"q": "x"})
    assert response.status_code == 502
    assert response.json() == {"detail": "YouTube Music's page changed"}


# --- The extension's WebSocket endpoint -----------------------------------------------------


@pytest.fixture
def bridge():
    return ExtensionBridge(request_timeout=5)


@pytest.fixture
def studio_app(bridge):
    return create_app(
        FakeMediaController(),
        token=TOKEN,
        library=ExtensionLibraryController(bridge),
        extension_bridge=bridge,
        extension_id=EXTENSION_ID,
    )


def socket_url(url):
    """Full ws:// URL for the extension endpoint.

    Starlette's TestClient ignores base_url for WebSockets and sends
    "Host: testserver" unless given a full URL — which would make every
    connection fail the Host check, including the legitimate one.
    """
    return url.replace("http://", "ws://") + "/extension/ws"


def local_client(app, client_ip="127.0.0.1", url="http://127.0.0.1:8000"):
    return TestClient(
        app,
        base_url=url,
        client=(client_ip, 50000),
        headers={"Authorization": f"Bearer {TOKEN}"},
        raise_server_exceptions=False,
    )


@pytest.mark.parametrize(
    ("client_ip", "url", "origin"),
    [
        ("127.0.0.1", "http://127.0.0.1:8000", "https://evil.example"),  # a web page on this PC
        ("127.0.0.1", "http://127.0.0.1:8000", "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),  # another extension
        ("127.0.0.1", "http://127.0.0.1:8000", None),  # no Origin at all (not a browser)
        ("192.168.1.12", "http://192.168.1.16:8000", EXTENSION_ORIGIN),  # another device forging the origin
        ("127.0.0.1", "http://evil.example:8000", EXTENSION_ORIGIN),  # DNS rebinding host
    ],
)
def test_extension_endpoint_refuses_everyone_else(studio_app, bridge, client_ip, url, origin):
    headers = {"origin": origin} if origin else {}
    with pytest.raises(WebSocketDisconnect) as refused:
        with local_client(studio_app, client_ip, url).websocket_connect(socket_url(url), headers=headers):
            pass
    assert refused.value.code == 1008
    assert bridge.connected is False


def test_the_legitimate_extension_is_accepted(studio_app, bridge):
    # Control case for the refusals above: without it, a check that refused
    # everything (as a Host-header mix-up once did) would look like success.
    with local_client(studio_app).websocket_connect(socket_url("http://127.0.0.1:8000"), headers={"origin": EXTENSION_ORIGIN}) as extension:
        extension.send_json({"type": "hello", "version": "1.0.0"})
        extension.send_json({"type": "keepalive"})
        for _ in range(50):
            if bridge.connected:
                break
            threading.Event().wait(0.02)
        assert bridge.connected


def test_extension_endpoint_does_not_exist_without_a_bridge(app):
    with pytest.raises(WebSocketDisconnect):
        with local_client(app).websocket_connect(socket_url("http://127.0.0.1:8000"), headers={"origin": EXTENSION_ORIGIN}):
            pass


def test_extension_connects_and_answers_a_search_end_to_end(studio_app, bridge):
    # `with` keeps ONE event loop for every request and the WebSocket, like
    # uvicorn in production. Without it, TestClient gives each request its own
    # loop, and the bridge's reply Future would belong to a loop that never
    # resolves it — the test would hang.
    with local_client(studio_app) as client:
        run_end_to_end_search(client, bridge)


def run_end_to_end_search(client, bridge):
    assert client.get("/api/library/status").json() == {"available": False}

    with client.websocket_connect(socket_url("http://127.0.0.1:8000"), headers={"origin": EXTENSION_ORIGIN}) as extension:
        extension.send_json({"type": "hello", "version": "1.0.0"})
        extension.send_json({"type": "keepalive"})  # the bridge ignores it; also lets it settle

        # The HTTP request waits for the extension's answer, so it runs in a
        # thread while this test plays the extension.
        responses = []
        phone = threading.Thread(
            target=lambda: responses.append(client.get("/api/library/search", params={"q": "yussef"}))
        )
        phone.start()
        request = extension.receive_json()
        extension.send_json({
            "type": "response",
            "id": request["id"],
            "ok": True,
            "result": [{"video_id": "XIQ6q5bocHw", "title": "Turquoise Galaxy", "artist": "Yussef Dayes", "duration": "9:12"}],
        })
        phone.join(timeout=5)

        assert (request["type"], request["op"], request["args"]) == ("request", "search", {"query": "yussef"})
        assert responses[0].status_code == 200
        assert responses[0].json()["results"][0]["title"] == "Turquoise Galaxy"
        assert client.get("/api/library/status").json() == {"available": True}


def test_extension_that_skips_hello_is_disconnected(studio_app, bridge):
    with pytest.raises(WebSocketDisconnect) as closed:
        with local_client(studio_app).websocket_connect(socket_url("http://127.0.0.1:8000"), headers={"origin": EXTENSION_ORIGIN}) as extension:
            extension.send_json({"type": "response", "id": 1, "ok": True})
            extension.receive_json()
    assert closed.value.code == 1008
