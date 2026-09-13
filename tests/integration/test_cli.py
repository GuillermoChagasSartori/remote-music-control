"""Integration tests: the `music` CLI talking to the real app, in-process.

`cli.make_client` is replaced with a function returning FastAPI's TestClient,
so each command goes through real argument parsing, real HTTP requests to the
real app, and real output formatting — just without a network.
"""

import io
import socket

import httpx2
import pytest
from fastapi.testclient import TestClient

from remote_music_control import cli

from ..support import TOKEN


@pytest.fixture
def run(app, monkeypatch, capsys):
    """Run `music <args>` and return (exit code, stdout, stderr)."""

    def fake_make_client(url, token):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return TestClient(app, headers=headers)

    monkeypatch.setattr(cli, "make_client", fake_make_client)

    def run_cli(*args):
        exit_code = cli.main(list(args))
        captured = capsys.readouterr()
        return exit_code, captured.out, captured.err

    return run_cli


@pytest.fixture
def with_token(monkeypatch):
    monkeypatch.setenv("RMC_TOKEN", TOKEN)


def test_now_shows_the_current_track(run, with_token):
    code, out, _ = run("now")
    assert code == 0
    assert out == "⏸ Signal Path — The Test Patterns (Loopback)\nvolume 50%\n"


def test_next_prints_the_new_track(run, with_token):
    code, out, _ = run("next")
    assert code == 0
    assert out.startswith("⏸ Low Latency")


def test_play_then_toggle(run, with_token):
    assert run("play")[1].startswith("▶")
    assert run("toggle")[1].startswith("⏸")


def test_volume_commands(run, with_token):
    assert run("vol", "30")[1] == "volume 30%\n"
    assert run("up")[1] == "volume 35%\n"
    assert run("down", "50")[1] == "volume 0%\n"
    assert run("mute")[1] == "volume 0% (muted)\n"
    assert run("unmute")[1] == "volume 0%\n"
    assert run("vol")[1] == "volume 0%\n"


def test_health_confirms_the_token(run, with_token):
    code, out, _ = run("health")
    assert code == 0
    assert "token accepted" in out


def test_missing_token_is_explained(run, isolated_environment):
    code, _, err = run("now")
    assert code == 1
    assert "the token is not set" in err
    assert str(isolated_environment) in err  # tells the user which file to edit


def test_wrong_token_is_explained(run, monkeypatch):
    monkeypatch.setenv("RMC_TOKEN", "wrong-token-wrong-token-wrong-token")
    code, _, err = run("next")
    assert code == 1
    assert "rejected by the server" in err


def test_closed_player_shows_the_servers_explanation(run, with_token, fake):
    fake.session_open = False
    code, _, err = run("play")
    assert code == 1
    assert "HTTP 409: no media session" in err


def test_invalid_volume_is_rejected_before_any_request(run, with_token, capsys):
    with pytest.raises(SystemExit) as exit_info:
        run("vol", "150")
    assert exit_info.value.code == 2
    assert "must be between 0 and 100" in capsys.readouterr().err


def test_unreachable_server_gives_a_clear_message(with_token, capsys):
    # Uses the real make_client (not the TestClient) against a port nothing
    # listens on: the operating system picks a free port, which is then closed.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]

    code = cli.main(["--url", f"http://127.0.0.1:{free_port}", "now"])

    assert code == 1
    assert "cannot connect to server" in capsys.readouterr().err


# --- Failures below the HTTP level ---------------------------------------------------------
#
# httpx2.MockTransport lets a real client run without any server: every request
# is handed to our function, which here simulates a network failure.


def client_failing_with(error):
    def handler(request):
        raise error

    return lambda url, token: httpx2.Client(base_url=url, transport=httpx2.MockTransport(handler))


def test_unreachable_pc_is_reported_as_cannot_connect(with_token, monkeypatch, capsys):
    # A PC that is switched off doesn't refuse the connection; it never answers,
    # and httpx2 raises ConnectTimeout (a TimeoutException, not a ConnectError).
    monkeypatch.setattr(cli, "make_client", client_failing_with(httpx2.ConnectTimeout("no reply")))
    assert cli.main(["now"]) == 1
    assert "cannot connect to server" in capsys.readouterr().err


def test_slow_server_gives_a_timeout_message(with_token, monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_client", client_failing_with(httpx2.ReadTimeout("too slow")))
    assert cli.main(["now"]) == 1
    assert "did not answer in time" in capsys.readouterr().err


def test_other_network_failure_is_reported(with_token, monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_client", client_failing_with(httpx2.RemoteProtocolError("connection dropped")))
    assert cli.main(["now"]) == 1
    assert "request failed: connection dropped" in capsys.readouterr().err


def test_broken_config_file_is_reported(isolated_environment, capsys):
    isolated_environment.write_text("not a key value line\n")
    assert cli.main(["now"]) == 1
    assert "configuration error" in capsys.readouterr().err


def test_output_is_utf8_even_when_redirected_to_a_legacy_encoding(run, with_token, monkeypatch):
    # Imitates Windows redirecting output to a file or pipe: a cp1252 text
    # stream, which can't encode "▶" or "—" and used to crash the CLI.
    redirected = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr("sys.stdout", redirected)

    exit_code = cli.main(["now"])

    redirected.flush()
    assert exit_code == 0
    assert redirected.buffer.getvalue().decode("utf-8").startswith("⏸ Signal Path — The Test Patterns")


def test_timeouts_allow_slow_commands_but_detect_unreachable_servers_quickly():
    assert cli.REQUEST_TIMEOUT.connect == 3.0
    assert cli.REQUEST_TIMEOUT.read >= 5.0  # slowest real command measured at ~4.5 s


# --- Library commands against the fake library ----------------------------------------------


def test_search_command(run, with_token):
    code, out, _ = run("search", "hexagon")
    assert code == 0
    assert out == " 1. Port and Adapter — Hexagon Club · 4:05  [fake0000003]\n 2. Walking Skeleton — Hexagon Club · 3:33  [fake0000004]\n"


def test_queue_jump_and_add_commands(run, with_token):
    code, out, _ = run("queue")
    assert code == 0 and out.splitlines()[0].startswith("▶   1. Signal Path")

    assert run("jump", "3")[:2] == (0, "playing queue item 3\n")
    assert run("queue")[1].splitlines()[2].startswith("▶   3. Port and Adapter")

    code, out, _ = run("add", "fake0000007", "--next")
    assert (code, out) == (0, "will play next\n")
    assert "4. Read Your Writes" in run("queue")[1]


def test_library_unavailable_is_explained(run, with_token, library):
    library.available = False
    code, _, err = run("queue")
    assert code == 1
    assert "HTTP 503" in err and "not ready" in err
