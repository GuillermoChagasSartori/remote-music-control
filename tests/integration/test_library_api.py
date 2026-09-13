"""Integration tests: the library routes (search and the queue), with the fake library."""

import pytest

from remote_music_control.library import LibraryError


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
        assert "not ready" in response.json()["detail"]


def test_library_failure_answers_502(client, library, monkeypatch):
    async def broken(query):
        raise LibraryError("YouTube Music's page changed")

    monkeypatch.setattr(library, "search", broken)
    response = client.get("/api/library/search", params={"q": "x"})
    assert response.status_code == 502
    assert response.json() == {"detail": "YouTube Music's page changed"}
