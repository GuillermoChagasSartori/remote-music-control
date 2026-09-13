"""All configuration, in one place: environment variables and one config file.

This follows factor III of the *twelve-factor app* methodology ("store config in
the environment"): anything that differs between machines — which adapter to
use, which address to listen on, the token — comes from outside the code.

Values are looked up in this order (first match wins):

1. real environment variables (handy for one-off overrides);
2. the per-user config file, `config.env` (where the token lives);
3. defaults defined below.

The config file sits in the user's config directory, outside the repository,
so the token can never be committed by accident:

- Linux:   ~/.config/remote-music-control/config.env  (XDG Base Directory spec)
- Windows: %APPDATA%\\remote-music-control\\config.env

All variables share the prefix RMC_ (Remote Music Control) so they can't clash
with other programs' settings.
"""

import os
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONTROLLER_CHOICES = ("fake", "windows")
LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR")

DEFAULT_CONTROLLER = "fake"
# Loopback by default: a fresh install is unreachable from the network until
# RMC_HOST is set deliberately (to 0.0.0.0 on the Windows PC).
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SERVER_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
# Executable names whose media session and audio the Windows adapter controls.
DEFAULT_PLAYER_APPS = ("chrome.exe", "firefox.exe")
DEFAULT_LOG_LEVEL = "INFO"

# secrets.token_urlsafe(32) produces 43 characters (32 random bytes). Anything
# much shorter was probably typed by hand and may be guessable.
MIN_TOKEN_LENGTH = 32


class ConfigError(Exception):
    """A configuration problem the user must fix; shown as a one-line message."""


@dataclass(frozen=True)
class ServerSettings:
    controller: str
    host: str
    port: int
    player_apps: tuple[str, ...]
    token: str
    log_level: str
    log_file: Path | None  # None: log to stderr (see server.log_destination)


@dataclass(frozen=True)
class ClientSettings:
    server_url: str
    token: str | None


# --- The config file ------------------------------------------------------------


def default_config_path(environ: Mapping[str, str] = os.environ) -> Path:
    # Empty variables count as unset here too (as in load_values): Path("") would
    # mean "the current folder". The XDG spec says the same for XDG_CONFIG_HOME.
    if environ.get("RMC_CONFIG_FILE", "").strip():
        return Path(environ["RMC_CONFIG_FILE"].strip())
    if sys.platform == "win32":
        base = environ.get("APPDATA", "").strip() or Path.home() / "AppData" / "Roaming"
    else:
        base = environ.get("XDG_CONFIG_HOME", "").strip() or Path.home() / ".config"
    return Path(base) / "remote-music-control" / "config.env"


def default_log_path(environ: Mapping[str, str] = os.environ) -> Path:
    """Where the server logs when it has no console: next to the config file."""
    return default_config_path(environ).parent / "server.log"


def read_config_file(path: Path) -> dict[str, str]:
    """Parse a simple `KEY=VALUE` file. Blank lines and `#` comments are ignored.

    Deliberately minimal (no quotes, no variable expansion): the file only ever
    holds a handful of plain values, and a 20-line parser we can read beats a
    dependency with features we don't need.
    """
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    # "utf-8-sig" also accepts a leading byte order mark (BOM), an invisible
    # marker that Windows PowerShell 5 and older Notepad put at the start of
    # "UTF-8" files. Plain "utf-8" would make it part of the first line.
    text = path.read_text(encoding="utf-8-sig")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ConfigError(f"{path}, line {line_number}: expected KEY=VALUE, got {raw_line!r}")
        values[key.strip()] = value.strip()
    return values


def load_values(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Merge the config file and the environment; the environment wins.

    An environment variable set to an empty string counts as unset, so a stray
    `RMC_TOKEN=` in a shell profile can't silently hide the file's real token.
    """
    set_in_environment = {key: value for key, value in environ.items() if value.strip()}
    return {**read_config_file(default_config_path(environ)), **set_in_environment}


def create_config_file(path: Path, lines: list[str]) -> None:
    """Create a new config file readable only by the current user.

    O_EXCL makes creation fail if the file already exists, so an existing token
    is never overwritten. On Linux, mode 0o600 means owner read/write only. On
    Windows the mode is ignored; files under %APPDATA% are readable only by the
    user, administrators and the SYSTEM account, by default.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


def generate_token() -> str:
    # `secrets` (not `random`) is the standard-library module for security: it
    # uses the operating system's cryptographically secure random source.
    return secrets.token_urlsafe(32)


# --- Settings --------------------------------------------------------------------
#
# `environ` is a parameter (defaulting to the real environment) so tests can
# pass a plain dict instead of modifying os.environ.


def load_server_settings(environ: Mapping[str, str] = os.environ) -> ServerSettings:
    values = load_values(environ)
    config_path = default_config_path(environ)

    controller = values.get("RMC_CONTROLLER", DEFAULT_CONTROLLER).strip().lower()
    if controller not in CONTROLLER_CHOICES:
        raise ConfigError(
            f"RMC_CONTROLLER={controller!r} is not valid; choose one of: {', '.join(CONTROLLER_CHOICES)}"
        )

    raw_port = values.get("RMC_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        raise ConfigError(f"RMC_PORT={raw_port!r} is not a number") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"RMC_PORT={port} is outside the valid range 1–65535")

    # Comma-separated list, e.g. RMC_PLAYER_APPS=chrome.exe,msedge.exe
    raw_apps = values.get("RMC_PLAYER_APPS", ",".join(DEFAULT_PLAYER_APPS))
    player_apps = tuple(name.strip().lower() for name in raw_apps.split(",") if name.strip())
    if not player_apps:
        raise ConfigError("RMC_PLAYER_APPS must name at least one application, e.g. chrome.exe")

    token = values.get("RMC_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            f"no RMC_TOKEN configured. Run `music-server init` to create {config_path} with a new token."
        )
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(
            f"RMC_TOKEN is too short ({len(token)} characters, minimum {MIN_TOKEN_LENGTH}). "
            "Generate one with `music-server init` or `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`."
        )

    log_level = values.get("RMC_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
    if log_level not in LOG_LEVEL_CHOICES:
        raise ConfigError(
            f"RMC_LOG_LEVEL={log_level!r} is not valid; choose one of: {', '.join(LOG_LEVEL_CHOICES)}"
        )

    raw_log_file = values.get("RMC_LOG_FILE", "").strip()

    return ServerSettings(
        controller=controller,
        host=values.get("RMC_HOST", DEFAULT_HOST).strip(),
        port=port,
        player_apps=player_apps,
        token=token,
        log_level=log_level,
        log_file=Path(raw_log_file) if raw_log_file else None,
    )


def load_client_settings(environ: Mapping[str, str] = os.environ) -> ClientSettings:
    values = load_values(environ)
    return ClientSettings(
        server_url=values.get("RMC_SERVER_URL", DEFAULT_SERVER_URL).strip(),
        token=values.get("RMC_TOKEN", "").strip() or None,
    )
