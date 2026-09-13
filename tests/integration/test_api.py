"""Integration tests: the real FastAPI app (routing, validation, authentication,
middleware, error handlers) running against the fake player.

"Integration" because many pieces are exercised together through HTTP, as a
client would use them — only the media player is replaced by the fake.
"""

import logging

import pytest

from remote_music_control.media_controller import MediaControllerError

from ..support import TOKEN


def state(client):
    response = client.get("/api/state")
    assert response.status_code == 200
    return response.json()


# --- Authentication ---------------------------------------------------------------


def api_routes(app):
    """Every (method, path) under /api, discovered from the app itself.

    Read from the app's OpenAPI schema — the public, machine-readable
    description behind the /docs page — rather than FastAPI's internal route
    objects, whose structure can change between versions.
    """
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api"):
            for method in operations:
                yield method.upper(), path


def test_every_api_route_requires_the_token(app, anonymous_client):
    # Discovering routes from the app (instead of listing them here) means a
    # route added later without protection makes this test fail.
    routes = list(api_routes(app))
    assert len(routes) == 16  # guards against the discovery silently finding nothing
    for method, path in routes:
        response = anonymous_client.request(method, path)
        assert response.status_code == 401, f"{method} {path} is not protected"
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_wrong_token_is_rejected(anonymous_client, fake):
    response = anonymous_client.post("/api/next", headers={"Authorization": "Bearer not-the-token"})
    assert response.status_code == 401
    assert anonymous_client.get("/api/state", headers={"Authorization": f"Bearer {TOKEN}"}).json()[
        "now_playing"
    ]["title"] == "Signal Path"  # the rejected "next" changed nothing


def test_token_must_use_the_bearer_scheme(anonymous_client):
    response = anonymous_client.get("/api/state", headers={"Authorization": f"Basic {TOKEN}"})
    assert response.status_code == 401


def test_health_and_web_page_are_public(anonymous_client):
    assert anonymous_client.get("/health").json() == {"status": "ok"}
    assert anonymous_client.get("/").status_code == 200
    assert anonymous_client.get("/static/app.js").status_code == 200


def test_rejected_requests_are_logged_without_the_token(anonymous_client, caplog):
    # `caplog` captures log records produced during the test.
    caplog.set_level(logging.INFO)
    anonymous_client.post("/api/next", headers={"Authorization": "Bearer guess-guess-guess"})
    assert "rejected POST /api/next" in caplog.text
    assert "guess-guess-guess" not in caplog.text
    assert TOKEN not in caplog.text


def test_cross_site_preflight_is_not_approved(anonymous_client):
    # A web page on another site asking the browser for permission to send a
    # request with an Authorization header. No CORS approval header comes
    # back, so the browser never sends the real request.
    response = anonymous_client.options(
        "/api/next",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert "access-control-allow-origin" not in response.headers


# --- Security headers -------------------------------------------------------------------


def test_web_page_has_security_and_cache_headers(anonymous_client):
    headers = anonymous_client.get("/").headers
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-cache"


def test_api_responses_do_not_get_web_page_headers(client):
    assert "Content-Security-Policy" not in client.get("/api/state").headers


# --- State and transport ------------------------------------------------------------------


def test_state_reports_track_volume_and_mute(client):
    assert state(client) == {
        "now_playing": {
            "title": "Signal Path",
            "artist": "The Test Patterns",
            "album": "Loopback",
            "status": "paused",
        },
        "volume": 50,
        "muted": False,
    }


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [("/api/play", "playing"), ("/api/pause", "paused"), ("/api/play-pause", "playing")],
)
def test_playback_commands(client, path, expected_status):
    response = client.post(path)
    assert response.status_code == 204
    assert response.content == b""
    assert state(client)["now_playing"]["status"] == expected_status


def test_next_and_previous(client):
    assert client.post("/api/next").status_code == 204
    assert state(client)["now_playing"]["title"] == "Low Latency"
    assert client.post("/api/previous").status_code == 204
    assert state(client)["now_playing"]["title"] == "Signal Path"


# --- Volume ----------------------------------------------------------------------------------


def test_set_volume_returns_the_new_volume(client):
    response = client.put("/api/volume", json={"level": 30})
    assert response.status_code == 200
    assert response.json() == {"volume": 30, "muted": False}
    assert client.get("/api/volume").json() == {"volume": 30, "muted": False}


def test_volume_up_and_down_use_a_default_step_of_5(client):
    assert client.post("/api/volume/up").json()["volume"] == 55
    assert client.post("/api/volume/down").json()["volume"] == 50


def test_volume_step_can_be_chosen_and_is_clamped(client):
    assert client.post("/api/volume/up", params={"step": 80}).json()["volume"] == 100
    assert client.post("/api/volume/down", params={"step": 100}).json()["volume"] == 0


def test_mute_and_unmute(client):
    assert client.put("/api/mute", json={"muted": True}).json() == {"volume": 50, "muted": True}
    assert client.put("/api/mute", json={"muted": False}).json() == {"volume": 50, "muted": False}


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("PUT", "/api/volume", {"json": {"level": 150}}),
        ("PUT", "/api/volume", {"json": {"level": -1}}),
        ("PUT", "/api/volume", {"json": {"level": "loud"}}),
        ("PUT", "/api/volume", {"json": {}}),
        ("POST", "/api/volume/up", {"params": {"step": 0}}),
        ("PUT", "/api/mute", {"json": {"muted": "sometimes"}}),
    ],
)
def test_invalid_input_is_rejected_with_422(client, method, path, kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == 422
    assert client.get("/api/volume").json() == {"volume": 50, "muted": False}  # unchanged


# --- Errors ------------------------------------------------------------------------------------


def test_closed_player_gives_empty_state_and_409_for_commands(client, fake):
    fake.session_open = False

    assert state(client) == {"now_playing": None, "volume": None, "muted": None}
    response = client.post("/api/next")
    assert response.status_code == 409
    assert "no media session" in response.json()["detail"]


def test_player_failure_becomes_502_with_the_reason(client, fake, monkeypatch):
    async def refuse():
        raise MediaControllerError("the player refused 'next'")

    monkeypatch.setattr(fake, "next_track", refuse)

    response = client.post("/api/next")
    assert response.status_code == 502
    assert response.json() == {"detail": "the player refused 'next'"}


def test_unexpected_error_becomes_500_without_leaking_details(client, fake, monkeypatch, caplog):
    async def crash():
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(fake, "pause", crash)
    caplog.set_level(logging.INFO)

    response = client.post("/api/pause")

    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    # ...but the developer can still find out what happened:
    assert "secret internal detail" in caplog.text
    assert "Traceback" in caplog.text


# --- Logging -------------------------------------------------------------------------------------


def test_commands_are_logged_but_polling_is_not(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/api/state")
    client.post("/api/next")
    # Only our app's records: the test client logs its own requests too.
    app_log = "\n".join(r.getMessage() for r in caplog.records if r.name == "remote_music_control.api")
    assert "POST /api/next -> 204" in app_log
    assert "/api/state" not in app_log


# --- Pairing page ------------------------------------------------------------------------


@pytest.fixture
def pairing_network(monkeypatch):
    """Fixed network details, so the page doesn't depend on the test machine."""
    from remote_music_control import pairing

    details = pairing.NetworkDetails(hostname="studio-pc", ip_address="192.168.1.16", mac_address="AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(pairing, "current_network", lambda: details)
    return details


def browser(app, client_ip, url):
    """A client whose connection comes from `client_ip`, opening `url`."""
    from fastapi.testclient import TestClient

    return TestClient(app, base_url=url, client=(client_ip, 50000), raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("client_ip", "url"),
    # IPv6 ([::1]) is covered in test_same_pc_check_handles_ipv6: the test client can't parse IPv6 URLs.
    [("127.0.0.1", "http://127.0.0.1:8000"), ("127.0.0.1", "http://localhost:8000")],
)
def test_pairing_page_opens_on_the_server_pc(app, pairing_network, client_ip, url):
    response = browser(app, client_ip, url).get("/pair")
    assert response.status_code == 200
    assert "Pair a phone or computer" in response.text
    assert "AA:BB:CC:DD:EE:FF" in response.text
    assert response.text.count("<svg") == 2  # the two QR codes
    assert response.headers["Cache-Control"] == "no-store"  # never cached: it holds the token
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_pairing_page_is_refused_to_other_devices(app, pairing_network, caplog):
    caplog.set_level(logging.WARNING)
    response = browser(app, "192.168.1.12", "http://192.168.1.16:8000").get("/pair")
    assert response.status_code == 403
    assert "<svg" not in response.text
    assert TOKEN not in response.text
    assert "refused the pairing page to 192.168.1.12" in caplog.text
    assert "http://127.0.0.1:8000/pair" in response.text  # tells the user where it does open


def test_pairing_page_is_refused_to_dns_rebinding(app, pairing_network):
    # Connection from this PC, but the browser was on the attacker's domain,
    # which had been made to resolve to 127.0.0.1.
    response = browser(app, "127.0.0.1", "http://evil.example:8000").get("/pair")
    assert response.status_code == 403


def test_pairing_qr_code_contains_the_token_and_the_port_in_use(app, pairing_network, monkeypatch):
    from remote_music_control import pairing

    encoded = []
    monkeypatch.setattr(pairing, "qr_code_svg", lambda text: encoded.append(text) or "<svg></svg>")
    browser(app, "127.0.0.1", "http://127.0.0.1:9000").get("/pair")
    assert encoded[0] == f"http://192.168.1.16:9000/#token={TOKEN}"


@pytest.mark.parametrize(
    ("client_ip", "host_header", "expected"),
    [
        ("::1", "[::1]:8000", True),
        ("::1", "localhost:8000", True),
        ("::1", "evil.example:8000", False),
        ("192.168.1.12", "[::1]:8000", False),
    ],
)
def test_same_pc_check_handles_ipv6(client_ip, host_header, expected):
    from types import SimpleNamespace

    from remote_music_control.api import is_same_pc_request

    request = SimpleNamespace(client=SimpleNamespace(host=client_ip), headers={"host": host_header})
    assert is_same_pc_request(request) is expected
