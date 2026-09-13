"""The LibraryController port: searching YouTube Music and managing the queue.

A second port, next to MediaController (page 01 of the walkthrough). Playback
controls come from Windows (SMTC); search and the queue exist only inside the
YouTube Music web app, which the app shows in its own window (ADR 0014).
Keeping them behind their own interface means the API, web page, CLI and tests
don't know or care how they're implemented — the fake adapter serves them on
Linux, the page adapter (adapters/page_library.py) in the Windows app.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class Song:
    """A playable search result (songs and videos only, ADR 0013)."""

    video_id: str
    title: str
    artist: str | None
    duration: str | None  # as YouTube Music shows it, e.g. "3:45"


@dataclass(frozen=True)
class QueueItem:
    index: int
    video_id: str
    title: str
    artist: str | None
    duration: str | None
    is_current: bool
    is_autoplay: bool  # YouTube Music's suggestions after the user's own queue


@dataclass(frozen=True)
class Queue:
    items: tuple[QueueItem, ...]
    current_index: int | None  # None if nothing in the queue is playing


class InsertPosition(StrEnum):
    NOW = "now"  # play immediately; YouTube Music replaces the queue with a radio for the song
    NEXT = "next"  # right after the current song, without interrupting it
    END = "end"  # at the end of the user's queue, before autoplay suggestions (as in YouTube Music)


class LibraryError(Exception):
    """Base class: the library couldn't do what was asked (e.g. YouTube Music changed)."""


class LibraryUnavailableError(LibraryError):
    """Nothing to talk to: the YouTube Music window isn't open, or hasn't loaded yet."""


class QueueItemNotFoundError(LibraryError):
    """The requested queue position doesn't exist (the queue may have changed)."""


class LibraryController(ABC):
    """Contract: every method raises LibraryUnavailableError when there is no
    YouTube Music to talk to, and LibraryError for other failures."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Whether library features can be used right now (for showing or hiding them)."""

    @abstractmethod
    async def search(self, query: str) -> list[Song]: ...

    @abstractmethod
    async def get_queue(self) -> Queue: ...

    @abstractmethod
    async def jump_to(self, index: int) -> None:
        """Play the queue item at `index`. Raises QueueItemNotFoundError if there is none."""

    @abstractmethod
    async def play(self, video_id: str, position: InsertPosition) -> None: ...
