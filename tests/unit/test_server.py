"""Unit tests for the server entry point: adapter selection, `init`, startup errors."""

import logging
import os
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
def test_windows_adapter_elsewhere_is_a_configuration_error():
    with pytest.raises(server.ConfigError, match="RMC_CONTROLLER=windows can't be used here"):
        server.build_controller(settings("windows"))


def test_init_creates_a_config_file_with_a_token(isolated_environment, capsys):
    # `isolated_environment` (conftest.py) points RMC_CONFIG_FILE at a temp file.
    # `capsys` captures what the code prints.
    assert server.main(["init"]) == 0

    token = read_config_file(isolated_environment)["RMC_TOKEN"]
    printed = capsys.readouterr().out
    assert len(token) >= 32
    assert f"#token={token}" in printed
    assert "/pair" in printed


def test_init_never_replaces_an_existing_config_file(isolated_environment, capsys):
    isolated_environment.write_text("RMC_TOKEN=keep-me\n")

    assert server.main(["init"]) == 1

    assert isolated_environment.read_text() == "RMC_TOKEN=keep-me\n"
    assert "already exists" in capsys.readouterr().err


def test_server_without_a_token_exits_with_a_one_line_message(capsys):
    assert server.main([]) == 1
    assert "configuration error: no RMC_TOKEN" in capsys.readouterr().err


def test_run_wires_settings_into_the_app_and_uvicorn(monkeypatch):
    # uvicorn.run would start a real server and block; replace it with a
    # function that records what it was given.
    calls = {}
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **options: calls.update(app=app, **options))

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


# --- The rotating log file ------------------------------------------------------------


def write_log_lines(path, count, max_bytes=2000):
    handler = server.LockTolerantRotatingFileHandler(path, max_bytes=max_bytes, backup_count=3)
    log = logging.getLogger(f"rotation-test-{path.name}")
    log.propagate = False  # keep these lines out of pytest's own log capture
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        for number in range(count):
            log.info("line %04d %s", number, "x" * 40)
    finally:
        log.removeHandler(handler)
        handler.close()


def all_lines(folder):
    return [line for file in sorted(folder.glob("server.log*")) for line in file.read_text().splitlines()]


def test_log_rotates_into_numbered_backups(tmp_path):
    write_log_lines(tmp_path / "server.log", 400)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["server.log", "server.log.1", "server.log.2", "server.log.3"]


def test_locked_log_loses_no_lines_and_keeps_its_backups(tmp_path, monkeypatch):
    # Existing backups that a failed rotation must not destroy.
    for number in (1, 2, 3):
        (tmp_path / f"server.log.{number}").write_text(f"backup {number}\n")

    # Simulate Windows refusing to rename server.log while another program
    # has it open (e.g. Get-Content -Wait).
    real_replace = os.replace

    def locked_replace(source, destination):
        if str(source).endswith("server.log"):
            raise PermissionError("The file is being used by another process")
        return real_replace(source, destination)

    monkeypatch.setattr(server.os, "replace", locked_replace)

    write_log_lines(tmp_path / "server.log", 400)

    lines = all_lines(tmp_path)
    assert sum(line.startswith("line ") for line in lines) == 400  # nothing lost
    for number in (1, 2, 3):  # backups untouched
        assert (tmp_path / f"server.log.{number}").read_text() == f"backup {number}\n"


def test_rotation_resumes_once_the_lock_is_released(tmp_path, monkeypatch):
    real_replace = os.replace
    locked = {"value": True}

    def sometimes_locked(source, destination):
        if locked["value"] and str(source).endswith("server.log"):
            raise PermissionError("in use")
        return real_replace(source, destination)

    monkeypatch.setattr(server.os, "replace", sometimes_locked)
    write_log_lines(tmp_path / "server.log", 200)
    locked["value"] = False
    write_log_lines(tmp_path / "server.log", 400)

    # Rotation works again: backups exist, never more than three, and the newest
    # line is in the current file. (Older lines age out, as rotation intends.)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["server.log", "server.log.1", "server.log.2", "server.log.3"]
    assert "line 0399" in (tmp_path / "server.log").read_text()


def test_rotating_handler_needs_at_least_one_backup(tmp_path):
    with pytest.raises(ValueError):
        server.LockTolerantRotatingFileHandler(tmp_path / "server.log", max_bytes=1000, backup_count=0)


@pytest.fixture
def installed_handlers(monkeypatch):
    """Record what configure_logging would install, without changing the real logging setup."""
    handlers = []
    monkeypatch.setattr(server.logging, "basicConfig", lambda **options: handlers.extend(options["handlers"]))
    yield handlers
    for handler in handlers:
        handler.close()


def test_configure_logging_uses_the_console_when_there_is_one(installed_handlers):
    server.configure_logging("INFO", log_file=None)
    assert type(installed_handlers[0]) is server.logging.StreamHandler


def test_configure_logging_uses_a_rotating_file_when_configured(installed_handlers, tmp_path):
    server.configure_logging("INFO", log_file=tmp_path / "logs" / "server.log")
    assert isinstance(installed_handlers[0], server.LockTolerantRotatingFileHandler)
    assert (tmp_path / "logs").is_dir()  # the folder was created


@pytest.mark.skipif(sys.platform == "win32", reason="checks the behaviour on non-Windows systems")
def test_main_reports_the_windows_adapter_on_linux_as_a_configuration_error(monkeypatch, caplog):
    monkeypatch.setenv("RMC_TOKEN", "t" * 40)
    monkeypatch.setenv("RMC_CONTROLLER", "windows")
    monkeypatch.setattr(server, "configure_logging", lambda level, log_file: None)

    assert server.main([]) == 1
    assert "configuration error: RMC_CONTROLLER=windows can't be used here" in caplog.text
