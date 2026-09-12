"""The MediaController port: everything the application needs from a media player.

This module is the *port* in ports-and-adapters (hexagonal) architecture: an
abstract interface that the rest of the application depends on. Concrete
*adapters* (the in-memory fake, the real Windows one) implement it. Nothing in
this file knows about HTTP, Windows, or any library — only plain Python.

See docs/decisions/0001 and 0005.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

MIN_VOLUME = 0
MAX_VOLUME = 100


class PlaybackStatus(StrEnum):
    # StrEnum members are real strings, so they serialize to JSON as "playing"
    # etc. without any conversion code.
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass(frozen=True)
class NowPlaying:
    """A snapshot of the current track.

    frozen=True makes it immutable: callers get a value they can read but not
    accidentally modify, so it can't drift out of sync with the real player.
    """

    title: str
    artist: str
    album: str | None
    status: PlaybackStatus


class MediaControllerError(Exception):
    """Base class for every error an adapter is allowed to raise."""


class NoMediaSessionError(MediaControllerError):
    """Raised by commands when there is nothing to control (e.g. browser closed)."""


def validate_volume(level: int) -> None:
    """Shared rule for all adapters: volume is an integer percentage 0–100."""
    if not MIN_VOLUME <= level <= MAX_VOLUME:
        raise ValueError(f"volume must be between {MIN_VOLUME} and {MAX_VOLUME}, got {level}")


class MediaController(ABC):
    """Abstract interface for controlling one media player.

    Methods are async because the real Windows API (WinRT) is asynchronous;
    see docs/decisions/0005. Adapters that have nothing to wait for (the fake)
    simply never await anything.

    Inheriting from ABC and marking methods @abstractmethod means Python refuses
    to instantiate an adapter that forgot to implement one of them.
    """

    # --- Transport ---

    @abstractmethod
    async def play(self) -> None: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def toggle_play_pause(self) -> None: ...

    @abstractmethod
    async def next_track(self) -> None: ...

    @abstractmethod
    async def previous_track(self) -> None: ...

    # --- Volume (of the player application, not the whole system) ---

    @abstractmethod
    async def get_volume(self) -> int:
        """Return the volume as an integer percentage, 0–100."""

    @abstractmethod
    async def set_volume(self, level: int) -> None:
        """Set the volume to `level` (0–100). Raises ValueError if out of range."""

    @abstractmethod
    async def is_muted(self) -> bool: ...

    @abstractmethod
    async def set_muted(self, muted: bool) -> None: ...

    # --- State ---

    @abstractmethod
    async def now_playing(self) -> NowPlaying | None:
        """Return the current track, or None if no media session exists.

        Returns None rather than raising, because "nothing is playing" is a
        normal state to display, not an error.
        """
