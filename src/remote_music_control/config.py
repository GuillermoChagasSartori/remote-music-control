"""All configuration, in one place: environment variables and one config file.

This follows factor III of the *twelve-factor app* methodology ("store config in
the environment"): anything that differs between machines — which address to
listen on, the port, the token — comes from outside the code.

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

LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR")

# Loopback by default: the development server is unreachable from the network
# until RMC_HOST is set deliberately.
DEFAULT_HOST = "127.0.0.1"
# The app exists to be used from other devices, so it listens on every network
# interface. The token still protects it, and the installer's firewall rule
# admits only the local network (ADR 0009, 0014).
APP_DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_SERVER_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
DEFAULT_LOG_LEVEL = "INFO"

# secrets.token_urlsafe(32) produces 43 characters (32 random bytes). Anything
# much shorter was probably typed by hand and may be guessable.
MIN_TOKEN_LENGTH = 32


class ConfigError(Exception):
    """A configuration problem the user must fix; shown as a one-line message."""


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
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


def default_browser_profile_path(environ: Mapping[str, str] = os.environ) -> Path:
    """Where the app's window keeps its cookies (the YouTube Music sign-in) and cache.

    %LOCALAPPDATA%, not %APPDATA% like the config file: the browser cache is
    large and belongs to this PC, and "Local" is the folder Windows doesn't copy
    between PCs on networks with roaming profiles.
    """
    base = environ.get("LOCALAPPDATA", "").strip() or Path.home() / "AppData" / "Local"
    return Path(base) / "remote-music-control" / "webview"


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


def config_file_lines(token: str) -> list[str]:
    """The content of a new config file: the token, and the other settings as comments."""
    return [
        "# Remote Music Control configuration. Keep this file private.",
        "# Real environment variables with the same names take precedence.",
        f"RMC_TOKEN={token}",
        "",
        "# Address to listen on: 127.0.0.1 for this PC only, 0.0.0.0 for the local network.",
        "# Default: 0.0.0.0 in the app, 127.0.0.1 in the development server.",
        "# RMC_HOST=0.0.0.0",
        "# RMC_PORT=8000",
        "# RMC_LOG_LEVEL=INFO",
        "# Log file; default is the console, or server.log next to this file when there is none:",
        "# RMC_LOG_FILE=C:\\path\\to\\server.log",
    ]


def ensure_config_file(path: Path) -> bool:
    """Create the config file with a new token unless it exists. True if it was created.

    The app calls this on every start, so its first start sets itself up with
    no command to run. An existing file, and so the token phones are paired
    with, is never replaced.
    """
    try:
        create_config_file(path, config_file_lines(generate_token()))
    except FileExistsError:
        return False
    return True


# --- Settings --------------------------------------------------------------------
#
# `environ` is a parameter (defaulting to the real environment) so tests can
# pass a plain dict instead of modifying os.environ.


def load_server_settings(
    environ: Mapping[str, str] = os.environ, default_host: str = DEFAULT_HOST
) -> ServerSettings:
    values = load_values(environ)
    config_path = default_config_path(environ)

    raw_port = values.get("RMC_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        raise ConfigError(f"RMC_PORT={raw_port!r} is not a number") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"RMC_PORT={port} is outside the valid range 1–65535")

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
        host=values.get("RMC_HOST", default_host).strip(),
        port=port,
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
