"""Unit tests for the app's platform-independent parts: texts, window actions, background server."""

import socket

import httpx2
import pytest
from fastapi import FastAPI

from remote_music_control.app import texts
from remote_music_control.app.background_server import BackgroundServer, ServerStartError
from remote_music_control.app.window_actions import WindowActions
from remote_music_control.config import default_browser_profile_path

# --- Texts ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language_id", "expected"),
    [
        (0x0416, texts.PORTUGUESE),  # pt-BR
        (0x0816, texts.PORTUGUESE),  # pt-PT
        (0x0409, texts.ENGLISH),  # en-US
        (0x0C0A, texts.ENGLISH),  # es-ES: anything else falls back to English
    ],
)
def test_language_follows_the_windows_display_language(language_id, expected):
    assert texts.texts_for_language_id(language_id) is expected


def test_both_languages_fill_in_the_error_message():
    for language in (texts.ENGLISH, texts.PORTUGUESE):
        message = language.start_failed.format(error="port in use", log="C:\\log.txt")
        assert "port in use" in message and "C:\\log.txt" in message


def test_texts_outside_windows_are_english(monkeypatch):
    monkeypatch.setattr(texts.sys, "platform", "linux")
    assert texts.system_texts() is texts.ENGLISH


# --- Window actions --------------------------------------------------------------------------


class FakeWindow:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):  # records hide(), show(), restore(), destroy()
        return lambda: self.calls.append(name)


@pytest.fixture
def window_and_notices():
    window, notices = FakeWindow(), []
    actions = WindowActions(window, lambda title, message: notices.append(title), texts.ENGLISH)
    return actions, window, notices


def test_closing_the_window_hides_it_and_explains_once(window_and_notices):
    actions, window, notices = window_and_notices
    assert actions.on_closing() is False  # closing cancelled
    assert actions.on_closing() is False
    assert window.calls == ["hide", "hide"]
    assert notices == ["Still playing"]  # only the first time


def test_show_brings_back_a_hidden_or_minimized_window(window_and_notices):
    actions, window, _ = window_and_notices
    actions.show()
    assert window.calls == ["show", "restore"]


def test_quit_really_closes(window_and_notices):
    actions, window, _ = window_and_notices
    actions.quit()
    assert window.calls == ["destroy"]
    assert actions.on_closing() is True  # pywebview asks while destroying: allowed now


# --- Browser profile location ------------------------------------------------------------------


def test_browser_profile_is_under_local_app_data(tmp_path):
    assert default_browser_profile_path({"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "remote-music-control" / "webview"


# --- Background server ---------------------------------------------------------------------------


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def small_app():
    app = FastAPI()
    app.get("/health")(lambda: {"status": "ok"})
    return app


def test_background_server_answers_while_the_caller_keeps_its_thread():
    port = free_port()
    server = BackgroundServer(small_app, "127.0.0.1", port)
    server.start()
    try:
        assert httpx2.get(f"http://127.0.0.1:{port}/health").json() == {"status": "ok"}
    finally:
        server.stop()
    with pytest.raises(httpx2.ConnectError):
        httpx2.get(f"http://127.0.0.1:{port}/health")


def test_port_in_use_is_a_start_error():
    with socket.socket() as occupant:
        occupant.bind(("127.0.0.1", 0))
        occupant.listen()
        port = occupant.getsockname()[1]
        with pytest.raises(ServerStartError, match=f"port {port}"):
            BackgroundServer(small_app, "127.0.0.1", port).start()


def test_an_app_that_fails_to_build_is_a_start_error():
    def broken():
        raise RuntimeError("no media controls here")

    with pytest.raises(ServerStartError, match="no media controls here"):
        BackgroundServer(broken, "127.0.0.1", free_port()).start()
