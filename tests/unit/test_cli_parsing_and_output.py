"""Unit tests for the CLI's pure parts: argument parsing and output formatting.

The CLI talking to a real app is covered in tests/integration/test_cli.py.
"""

import argparse

import httpx2
import pytest

from remote_music_control import cli


def track_state(album="Loopback", status="playing", volume=40, muted=False):
    return {
        "now_playing": {"title": "Signal Path", "artist": "The Test Patterns", "album": album, "status": status},
        "volume": volume,
        "muted": muted,
    }


# --- Output -------------------------------------------------------------------------


def test_format_state_shows_symbol_track_album_and_volume():
    assert cli.format_state(track_state()) == "▶ Signal Path — The Test Patterns (Loopback)\nvolume 40%"


def test_format_state_leaves_out_a_missing_album():
    assert cli.format_state(track_state(album=None, status="paused")).startswith(
        "⏸ Signal Path — The Test Patterns\n"
    )


def test_format_state_when_nothing_is_playing():
    text = cli.format_state({"now_playing": None, "volume": None, "muted": None})
    assert text.startswith("nothing playing")


def test_format_volume_marks_muted():
    assert cli.format_volume({"volume": 35, "muted": True}) == "volume 35% (muted)"


def test_server_error_message_prefers_the_servers_explanation():
    response = httpx2.Response(409, json={"detail": "no media session"})
    assert cli.server_error_message(response) == "server returned HTTP 409: no media session"


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(422, json={"detail": [{"msg": "validation details"}]}),  # detail isn't text
        httpx2.Response(500, text="Internal Server Error"),  # body isn't JSON
    ],
)
def test_server_error_message_falls_back_to_the_status_code(response):
    assert cli.server_error_message(response) == f"server returned HTTP {response.status_code}"


# --- Argument parsing ------------------------------------------------------------------


@pytest.mark.parametrize("text", ["0", "40", "100"])
def test_volume_level_accepts_whole_numbers_0_to_100(text):
    assert cli.volume_level(text) == int(text)


@pytest.mark.parametrize("text", ["-1", "101", "loud", "4.5"])
def test_volume_level_rejects_other_input(text):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.volume_level(text)


def test_volume_step_rejects_zero():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.volume_step("0")


def test_parser_attaches_the_right_handler_and_arguments():
    parser = cli.build_parser("http://example:8000")

    args = parser.parse_args(["vol", "40"])
    assert (args.handler, args.level, args.url) == (cli.run_volume, 40, "http://example:8000")

    args = parser.parse_args(["next"])
    assert (args.handler, args.path) == (cli.run_transport, "/api/next")

    args = parser.parse_args(["up"])
    assert (args.handler, args.step) == (cli.run_volume_step, None)


def test_parser_requires_a_command():
    # argparse reports usage errors by exiting with status 2.
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser("http://example:8000").parse_args([])
    assert exit_info.value.code == 2
