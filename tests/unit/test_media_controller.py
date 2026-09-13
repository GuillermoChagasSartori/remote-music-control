"""Unit tests for the rules defined next to the port: volume validation and steps."""

import asyncio

import pytest

from remote_music_control.adapters.fake import FakeMediaController
from remote_music_control.media_controller import change_volume, validate_volume


@pytest.mark.parametrize("level", [0, 1, 50, 99, 100])
def test_validate_volume_accepts_0_to_100(level):
    validate_volume(level)  # passes if nothing is raised


@pytest.mark.parametrize("level", [-1, 101])
def test_validate_volume_rejects_values_outside_0_to_100(level):
    with pytest.raises(ValueError, match="between 0 and 100"):
        validate_volume(level)


@pytest.mark.parametrize(
    ("start", "delta", "expected"),
    [
        (50, +10, 60),
        (50, -10, 40),
        (95, +10, 100),  # clamped at the top instead of rejected
        (5, -10, 0),  # clamped at the bottom
        (100, +5, 100),
        (0, -5, 0),
    ],
)
def test_change_volume_moves_and_clamps(start, delta, expected):
    player = FakeMediaController()
    asyncio.run(player.set_volume(start))

    returned = asyncio.run(change_volume(player, delta))

    assert returned == expected
    assert asyncio.run(player.get_volume()) == expected
