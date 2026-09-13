"""Unit tests for the server entry point: adapter selection, `init`, startup errors."""

import socket
import sys
from pathlib import Path

import pytest

from remote_music_control import server
from remote_music_control.adapters.fake import FakeMediaController
from remote_music_control.config import ServerSettings, read_config_file


def settings(controller: str) -> ServerSettings:
    return ServerSettings(
        controller=controller,
        host="127.0.0.1",
        port=8000,
        player_apps=("chrome.exe",),
        token="t" * 40,
        log_level="INFO",
        log_file=None,
    )


def test_build_controller_returns_the_fake():
    assert isinstance(server.build_controller(settings("fake")), FakeMediaController)


@pytest.mark.skipif(sys.platform == "win32", reason="checks the behaviour on non-Windows systems")
def test_windows_adapter_refuses_to_load_elsewhere():
    with pytest.raises(ImportError, match="only be used on Windows"):
        server.build_controller(settings("windows"))


def test_init_creates_a_config_file_with_a_token(isolated_environment, capsys):
    # `isolated_environment` (conftest.py) points RMC_CONFIG_FILE at a temp file.
    # `capsys` captures what the code prints.
    assert server.main(["init"]) == 0

    token = read_config_file(isolated_environment)["RMC_TOKEN"]
    printed = capsys.readouterr().out
    assert len(token) >= 32
    assert f"#token={token}" in printed


def test_init_never_replaces_an_existing_config_file(isolated_environment, capsys):
    isolated_environment.write_text("RMC_TOKEN=keep-me\n")

    assert server.main(["init"]) == 1

    assert isolated_environment.read_text() == "RMC_TOKEN=keep-me\n"
    assert "already exists" in capsys.readouterr().err


def test_server_without_a_token_exits_with_a_one_line_message(capsys):
    assert server.main([]) == 1
    assert "configuration error: no RMC_TOKEN" in capsys.readouterr().err


def test_lan_ip_address_is_none_without_a_network(monkeypatch):
    def unreachable(self, address):
        raise OSError("network is unreachable")

    monkeypatch.setattr(socket.socket, "connect", unreachable)
    assert server.lan_ip_address() is None


def test_run_wires_settings_into_the_app_and_uvicorn(monkeypatch):
    # uvicorn.run would start a real server and block; replace it with a
    # function that records what it was given.
    calls = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **options: calls.update(app=app, **options))
    # Logging setup changes process-wide state (root logger, stderr), so skip it here.
    monkeypatch.setattr(server, "configure_logging", lambda level: None)

    server.run(settings("fake"))

    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
    assert calls["access_log"] is False
    assert calls["log_config"] is None
    assert calls["app"].title == "Remote Music Control"


def test_main_starts_the_server_when_configured(monkeypatch):
    monkeypatch.setenv("RMC_TOKEN", "t" * 40)
    started = []
    monkeypatch.setattr(server, "run", started.append)
    monkeypatch.setattr(server, "configure_logging", lambda level, log_file: None)

    assert server.main([]) == 0
    assert started[0].controller == "fake"


def test_unknown_controller_is_a_configuration_error():
    with pytest.raises(server.ConfigError):
        server.build_controller(settings("vlc"))


# --- Running without a console (pythonw.exe, as the logon task does) -------------------


def test_logs_go_to_stderr_when_there_is_a_console():
    assert server.log_destination(None, stderr=sys.stderr) is None


def test_configured_log_file_is_used(tmp_path):
    assert server.log_destination(tmp_path / "x.log", stderr=sys.stderr) == tmp_path / "x.log"


def test_logs_go_to_the_default_file_when_there_is_no_console(isolated_environment):
    # Under pythonw.exe sys.stderr is None; printing to it would crash.
    assert server.log_destination(None, stderr=None) == isolated_environment.parent / "server.log"


def test_startup_error_without_a_console_is_written_to_the_log_file(isolated_environment, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)

    assert server.main([]) == 1  # no token configured

    log = (isolated_environment.parent / "server.log").read_text(encoding="utf-8")
    assert "configuration error: no RMC_TOKEN" in log


def test_unexpected_crash_exits_with_failure_so_the_task_restarts_it(monkeypatch, caplog):
    monkeypatch.setenv("RMC_TOKEN", "t" * 40)
    monkeypatch.setattr(server, "configure_logging", lambda level, log_file: None)

    def crash(settings):
        raise RuntimeError("port already in use")

    monkeypatch.setattr(server, "run", crash)

    assert server.main([]) == 1
    assert "server stopped because of an unexpected error" in caplog.text
    assert "port already in use" in caplog.text
