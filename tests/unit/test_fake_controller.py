"""Unit tests for FakeMediaController.

The fake stands in for the real player in every other test, so it must behave
correctly itself — otherwise the API tests would be testing against a lie.

Controller methods are async; `asyncio.run()` runs one coroutine to completion
from ordinary synchronous test code, so no pytest plugin is needed.
"""

import asyncio

import pytest

from remote_music_control.adapters.fake import FakeMediaController
from remote_music_control.media_controller import (
    MediaController,
    NoMediaSessionError,
    PlaybackStatus,
)

TRACKS = (
    ("First", "Artist A", "Album A"),
    ("Second", "Artist B", "Album B"),
    ("Third", "Artist C", "Album C"),
)


@pytest.fixture
def player() -> FakeMediaController:
    return FakeMediaController(tracks=TRACKS)


def now_playing(player):
    return asyncio.run(player.now_playing())


def test_starts_paused_on_first_track_at_half_volume(player):
    track = now_playing(player)
    assert (track.title, track.artist, track.album) == TRACKS[0]
    assert track.status == PlaybackStatus.PAUSED
    assert asyncio.run(player.get_volume()) == 50
    assert asyncio.run(player.is_muted()) is False


def test_play_and_pause(player):
    asyncio.run(player.play())
    assert now_playing(player).status == PlaybackStatus.PLAYING
    asyncio.run(player.pause())
    assert now_playing(player).status == PlaybackStatus.PAUSED


def test_toggle_alternates_between_playing_and_paused(player):
    asyncio.run(player.toggle_play_pause())
    assert now_playing(player).status == PlaybackStatus.PLAYING
    asyncio.run(player.toggle_play_pause())
    assert now_playing(player).status == PlaybackStatus.PAUSED


def test_next_advances_and_wraps_to_the_first_track(player):
    titles = []
    for _ in range(len(TRACKS)):
        asyncio.run(player.next_track())
        titles.append(now_playing(player).title)
    assert titles == ["Second", "Third", "First"]


def test_previous_wraps_from_first_to_last_track(player):
    asyncio.run(player.previous_track())
    assert now_playing(player).title == "Third"


def test_set_volume_is_remembered(player):
    asyncio.run(player.set_volume(80))
    assert asyncio.run(player.get_volume()) == 80


# `parametrize` runs the same test once per value, reported as separate tests.
@pytest.mark.parametrize("level", [-1, 101, 1000])
def test_set_volume_rejects_out_of_range_and_keeps_old_value(player, level):
    with pytest.raises(ValueError):
        asyncio.run(player.set_volume(level))
    assert asyncio.run(player.get_volume()) == 50


def test_mute_and_unmute(player):
    asyncio.run(player.set_muted(True))
    assert asyncio.run(player.is_muted()) is True
    asyncio.run(player.set_muted(False))
    assert asyncio.run(player.is_muted()) is False


def test_closed_player_reports_nothing_playing(player):
    player.session_open = False
    assert now_playing(player) is None


@pytest.mark.parametrize(
    "call",
    [
        lambda p: p.play(),
        lambda p: p.pause(),
        lambda p: p.toggle_play_pause(),
        lambda p: p.next_track(),
        lambda p: p.previous_track(),
        lambda p: p.get_volume(),
        lambda p: p.set_volume(10),
        lambda p: p.is_muted(),
        lambda p: p.set_muted(True),
    ],
    ids=["play", "pause", "toggle", "next", "previous", "get_volume", "set_volume", "is_muted", "set_muted"],
)
def test_closed_player_rejects_every_command(player, call):
    # This is the port's contract (media_controller.py): every method except
    # now_playing() raises NoMediaSessionError when nothing is open.
    player.session_open = False
    with pytest.raises(NoMediaSessionError):
        asyncio.run(call(player))


def test_reopened_player_works_again(player):
    player.session_open = False
    player.session_open = True
    asyncio.run(player.next_track())
    assert now_playing(player).title == "Second"


def test_needs_at_least_one_track():
    with pytest.raises(ValueError):
        FakeMediaController(tracks=())


def test_port_refuses_an_adapter_with_missing_methods():
    # MediaController is an abstract base class: Python won't instantiate a
    # subclass that forgot to implement its abstract methods.
    class IncompleteAdapter(MediaController):
        async def play(self) -> None: ...

    with pytest.raises(TypeError):
        IncompleteAdapter()
