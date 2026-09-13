"""Smoke tests for the Windows adapter — run only on Windows (e.g. the CI Windows job).

A *smoke test* checks that something starts at all, not that it is fully
correct. Real behaviour needs a logged-in desktop session with a browser
playing, which CI machines don't have; that is covered by the manual procedure
in docs/testing-on-windows.md.

These tests catch the failures CI *can* see: a Windows-only dependency that no
longer installs or imports, or the adapter no longer satisfying the port.
"""

import sys

import pytest

from remote_music_control.media_controller import MediaController, NowPlaying, PlaybackStatus

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only adapter")


def test_adapter_imports_and_implements_the_port():
    from remote_music_control.adapters.windows import WindowsMediaController

    controller = WindowsMediaController(player_apps=("chrome.exe",))
    assert isinstance(controller, MediaController)


def test_adapter_needs_at_least_one_player_app():
    from remote_music_control.adapters.windows import WindowsMediaController

    with pytest.raises(ValueError):
        WindowsMediaController(player_apps=())


def test_track_change_detection():
    from remote_music_control.adapters.windows import _is_different_track

    before = NowPlaying(title="A", artist="X", album=None, status=PlaybackStatus.PLAYING)
    same = NowPlaying(title="A", artist="X", album=None, status=PlaybackStatus.PAUSED)
    other = NowPlaying(title="B", artist="X", album=None, status=PlaybackStatus.PLAYING)

    assert _is_different_track(other, before)
    assert not _is_different_track(same, before)
    assert _is_different_track(same, None)
