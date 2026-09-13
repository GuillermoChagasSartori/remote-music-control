"""Unit tests for configuration loading.

Every test passes an explicit `environ` dict that includes RMC_CONFIG_FILE
pointing into pytest's `tmp_path` (a fresh temporary directory per test), so
nothing reads or writes the real user config file.
"""

import stat
import sys
from pathlib import Path

import pytest

from remote_music_control import config
from remote_music_control.config import (
    MIN_TOKEN_LENGTH,
    ConfigError,
    create_config_file,
    default_config_path,
    generate_token,
    load_client_settings,
    load_server_settings,
    read_config_file,
)

GOOD_TOKEN = "t" * MIN_TOKEN_LENGTH


def environment(tmp_path: Path, **variables: str) -> dict[str, str]:
    return {"RMC_CONFIG_FILE": str(tmp_path / "config.env"), **variables}


def write_config(tmp_path: Path, text: str, encoding: str = "utf-8") -> None:
    (tmp_path / "config.env").write_text(text, encoding=encoding)


# --- Server settings ------------------------------------------------------------


def test_defaults_when_only_the_token_is_set(tmp_path):
    settings = load_server_settings(environment(tmp_path, RMC_TOKEN=GOOD_TOKEN))
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.log_level == "INFO"
    assert settings.token == GOOD_TOKEN


def test_missing_token_is_an_error_that_explains_how_to_fix_it(tmp_path):
    with pytest.raises(ConfigError, match="music-server init"):
        load_server_settings(environment(tmp_path))


def test_short_token_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="too short"):
        load_server_settings(environment(tmp_path, RMC_TOKEN="short"))


def test_values_are_read_from_the_config_file(tmp_path):
    write_config(tmp_path, f"RMC_TOKEN={GOOD_TOKEN}\nRMC_HOST=0.0.0.0\nRMC_PORT=9000\n")
    settings = load_server_settings(environment(tmp_path))
    assert (settings.host, settings.port) == ("0.0.0.0", 9000)


def test_environment_variables_override_the_config_file(tmp_path):
    write_config(tmp_path, f"RMC_TOKEN={GOOD_TOKEN}\nRMC_PORT=9000\n")
    settings = load_server_settings(environment(tmp_path, RMC_PORT="9100"))
    assert settings.port == 9100


def test_empty_environment_variable_does_not_hide_the_config_file(tmp_path):
    write_config(tmp_path, f"RMC_TOKEN={GOOD_TOKEN}\n")
    settings = load_server_settings(environment(tmp_path, RMC_TOKEN=""))
    assert settings.token == GOOD_TOKEN


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({"RMC_PORT": "eighty"}, "not a number"),
        ({"RMC_PORT": "70000"}, "valid range"),
        ({"RMC_PORT": "0"}, "valid range"),
        ({"RMC_LOG_LEVEL": "LOUD"}, "RMC_LOG_LEVEL"),
    ],
)
def test_invalid_values_are_reported(tmp_path, variables, message):
    with pytest.raises(ConfigError, match=message):
        load_server_settings(environment(tmp_path, RMC_TOKEN=GOOD_TOKEN, **variables))


def test_log_file_is_optional(tmp_path):
    assert load_server_settings(environment(tmp_path, RMC_TOKEN=GOOD_TOKEN)).log_file is None
    settings = load_server_settings(environment(tmp_path, RMC_TOKEN=GOOD_TOKEN, RMC_LOG_FILE=str(tmp_path / "s.log")))
    assert settings.log_file == tmp_path / "s.log"


def test_log_level_is_case_insensitive(tmp_path):
    settings = load_server_settings(environment(tmp_path, RMC_TOKEN=GOOD_TOKEN, RMC_LOG_LEVEL="debug"))
    assert settings.log_level == "DEBUG"


# --- Client settings --------------------------------------------------------------


def test_client_defaults(tmp_path):
    settings = load_client_settings(environment(tmp_path))
    assert settings.server_url == "http://127.0.0.1:8000"
    assert settings.token is None


def test_client_reads_url_and_token_from_the_config_file(tmp_path):
    write_config(tmp_path, f"RMC_SERVER_URL=http://studio.local:8000\nRMC_TOKEN={GOOD_TOKEN}\n")
    settings = load_client_settings(environment(tmp_path))
    assert settings.server_url == "http://studio.local:8000"
    assert settings.token == GOOD_TOKEN


# --- The config file format ---------------------------------------------------------


def test_missing_config_file_means_no_values(tmp_path):
    assert read_config_file(tmp_path / "does-not-exist.env") == {}


def test_comments_blank_lines_and_spaces_are_ignored(tmp_path):
    write_config(tmp_path, "# a comment\n\n  RMC_PORT = 9000  \n")
    assert read_config_file(tmp_path / "config.env") == {"RMC_PORT": "9000"}


def test_value_may_contain_equals_signs(tmp_path):
    write_config(tmp_path, "RMC_TOKEN=abc=def==\n")
    assert read_config_file(tmp_path / "config.env") == {"RMC_TOKEN": "abc=def=="}


def test_byte_order_mark_from_windows_editors_is_accepted(tmp_path):
    # "utf-8-sig" writes the BOM that PowerShell 5 and old Notepad add.
    write_config(tmp_path, "# comment\nRMC_PORT=9000\n", encoding="utf-8-sig")
    assert read_config_file(tmp_path / "config.env") == {"RMC_PORT": "9000"}


def test_malformed_line_is_reported_with_its_line_number(tmp_path):
    write_config(tmp_path, "RMC_PORT=9000\nthis line has no equals sign\n")
    with pytest.raises(ConfigError, match="line 2"):
        read_config_file(tmp_path / "config.env")


# --- Config file location -----------------------------------------------------------


def test_config_path_can_be_set_explicitly(tmp_path):
    assert default_config_path({"RMC_CONFIG_FILE": str(tmp_path / "x.env")}) == tmp_path / "x.env"


def test_config_path_on_linux_follows_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "platform", "linux")
    path = default_config_path({"XDG_CONFIG_HOME": str(tmp_path)})
    assert path == tmp_path / "remote-music-control" / "config.env"


@pytest.mark.parametrize("variable", ["RMC_CONFIG_FILE", "XDG_CONFIG_HOME"])
def test_empty_path_variables_count_as_unset(monkeypatch, variable):
    monkeypatch.setattr(config.sys, "platform", "linux")
    path = default_config_path({variable: "  "})
    assert path == Path.home() / ".config" / "remote-music-control" / "config.env"


def test_empty_appdata_falls_back_to_the_usual_windows_folder(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "win32")
    path = default_config_path({"APPDATA": ""})
    assert path == Path.home() / "AppData" / "Roaming" / "remote-music-control" / "config.env"


def test_config_path_on_windows_is_under_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(config.sys, "platform", "win32")
    path = default_config_path({"APPDATA": str(tmp_path)})
    assert path == tmp_path / "remote-music-control" / "config.env"


# --- Creating the file and the token ---------------------------------------------------


def test_create_config_file_writes_the_lines_and_creates_folders(tmp_path):
    path = tmp_path / "nested" / "config.env"
    create_config_file(path, ["RMC_TOKEN=abc", "# note"])
    assert path.read_text(encoding="utf-8") == "RMC_TOKEN=abc\n# note\n"


def test_create_config_file_never_overwrites(tmp_path):
    path = tmp_path / "config.env"
    path.write_text("RMC_TOKEN=original\n")
    with pytest.raises(FileExistsError):
        create_config_file(path, ["RMC_TOKEN=replacement"])
    assert path.read_text() == "RMC_TOKEN=original\n"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
def test_create_config_file_is_readable_only_by_the_owner(tmp_path):
    path = tmp_path / "config.env"
    create_config_file(path, ["RMC_TOKEN=abc"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_generated_tokens_are_long_enough_and_different():
    tokens = {generate_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(token) >= MIN_TOKEN_LENGTH for token in tokens)
