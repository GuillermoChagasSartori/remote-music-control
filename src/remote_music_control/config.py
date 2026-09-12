"""All configuration, in one place, read from environment variables.

This follows factor III of the *twelve-factor app* methodology ("store config in
the environment"): anything that differs between machines — which adapter to
use, which port to listen on, the server address — comes from environment
variables, never from values edited into the code. Every variable has a sensible
default, so the app runs with no configuration at all during development.

All variables share the prefix RMC_ (Remote Music Control) so they can't clash
with other programs' settings.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

CONTROLLER_CHOICES = ("fake",)  # "windows" is added in Phase 4

DEFAULT_CONTROLLER = "fake"
# Loopback only for now: nothing outside this PC can connect until Phase 5
# adds the bearer token and chooses the LAN bind address deliberately.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SERVER_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


@dataclass(frozen=True)
class ServerSettings:
    controller: str
    host: str
    port: int


@dataclass(frozen=True)
class ClientSettings:
    server_url: str


# `environ` is a parameter (defaulting to the real environment) so tests can
# pass a plain dict instead of modifying os.environ.


def load_server_settings(environ: Mapping[str, str] = os.environ) -> ServerSettings:
    controller = environ.get("RMC_CONTROLLER", DEFAULT_CONTROLLER).strip().lower()
    if controller not in CONTROLLER_CHOICES:
        raise ValueError(
            f"RMC_CONTROLLER={controller!r} is not valid; choose one of: {', '.join(CONTROLLER_CHOICES)}"
        )

    raw_port = environ.get("RMC_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError(f"RMC_PORT={raw_port!r} is not a number") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"RMC_PORT={port} is outside the valid range 1–65535")

    return ServerSettings(
        controller=controller,
        host=environ.get("RMC_HOST", DEFAULT_HOST),
        port=port,
    )


def load_client_settings(environ: Mapping[str, str] = os.environ) -> ClientSettings:
    return ClientSettings(server_url=environ.get("RMC_SERVER_URL", DEFAULT_SERVER_URL))
