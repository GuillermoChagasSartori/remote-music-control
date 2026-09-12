"""FakeMediaController: an in-memory player that runs on any operating system.

In testing vocabulary this is a *fake* — a working, simplified implementation
(as opposed to a *mock*, which only records calls, or a *stub*, which only
returns canned answers). It behaves like a real player: skipping changes the
track, volume is remembered, and so on. That lets the server, web UI, CLI and
tests be developed on Linux. See docs/decisions/0001.
"""

from ..media_controller import MediaController, NowPlaying, PlaybackStatus, validate_volume

# Invented tracks, so screenshots in the public README show no real artists.
DEMO_TRACKS: tuple[tuple[str, str, str], ...] = (
    ("Signal Path", "The Test Patterns", "Loopback"),
    ("Low Latency", "The Test Patterns", "Loopback"),
    ("Port and Adapter", "Hexagon Club", "Clean Architecture"),
    ("Walking Skeleton", "Hexagon Club", "Clean Architecture"),
    ("Two Machines", "Studio & Bedroom", "Same Network"),
)


class FakeMediaController(MediaController):
    # No locking is needed: the server runs these coroutines on a single event
    # loop, and no method awaits in the middle of changing state, so two
    # requests can never interleave inside one method.

    def __init__(self, tracks: tuple[tuple[str, str, str], ...] = DEMO_TRACKS) -> None:
        if not tracks:
            raise ValueError("FakeMediaController needs at least one track")
        self._tracks = tracks
        self._index = 0
        self._status = PlaybackStatus.PAUSED
        self._volume = 50
        self._muted = False

    # --- Transport ---

    async def play(self) -> None:
        self._status = PlaybackStatus.PLAYING

    async def pause(self) -> None:
        self._status = PlaybackStatus.PAUSED

    async def toggle_play_pause(self) -> None:
        if self._status == PlaybackStatus.PLAYING:
            self._status = PlaybackStatus.PAUSED
        else:
            self._status = PlaybackStatus.PLAYING

    async def next_track(self) -> None:
        # Modulo wraps from the last track back to the first, like a looping queue.
        self._index = (self._index + 1) % len(self._tracks)

    async def previous_track(self) -> None:
        self._index = (self._index - 1) % len(self._tracks)

    # --- Volume ---

    async def get_volume(self) -> int:
        return self._volume

    async def set_volume(self, level: int) -> None:
        validate_volume(level)
        self._volume = level

    async def is_muted(self) -> bool:
        return self._muted

    async def set_muted(self, muted: bool) -> None:
        self._muted = muted

    # --- State ---

    async def now_playing(self) -> NowPlaying | None:
        title, artist, album = self._tracks[self._index]
        return NowPlaying(title=title, artist=artist, album=album, status=self._status)
