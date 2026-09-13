"""Shared test setup.

pytest loads this file automatically. Functions marked @pytest.fixture are
*fixtures*: reusable setup that a test receives simply by naming it as a
parameter (e.g. `def test_x(client):`). pytest creates a fresh one per test,
so tests can't leak state into each other.
"""

import os

import pytest
from fastapi.testclient import TestClient

from remote_music_control.adapters.fake import FakeMediaController
from remote_music_control.api import create_app

# Long enough to satisfy the server's minimum length rule.
TOKEN = "test-token-0123456789-abcdefghijklmnopqrstuvwxyz"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Give every test an empty RMC_* environment and its own config file path.

    autouse=True applies it to every test without being requested. Without it,
    tests would read the developer's real config file — including the real
    token — and pass or fail depending on whose machine runs them.
    `monkeypatch` undoes these changes after each test.
    """
    for name in list(os.environ):
        if name.startswith("RMC_"):
            monkeypatch.delenv(name)
    config_file = tmp_path / "config.env"
    monkeypatch.setenv("RMC_CONFIG_FILE", str(config_file))
    return config_file


@pytest.fixture
def fake() -> FakeMediaController:
    return FakeMediaController()


@pytest.fixture
def app(fake):
    return create_app(fake, token=TOKEN)


@pytest.fixture
def client(app) -> TestClient:
    """An HTTP client for the real app, sending the correct token.

    TestClient runs the app in-process: real routing, validation, middleware
    and error handlers, with no server or network port involved.
    raise_server_exceptions=False lets the app's own 500 handling answer, as it
    would in production, instead of re-raising errors inside the test.
    """
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}, raise_server_exceptions=False)


@pytest.fixture
def anonymous_client(app) -> TestClient:
    """The same app, but a client that sends no token."""
    return TestClient(app, raise_server_exceptions=False)
