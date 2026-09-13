"""FakeLibraryController: an in-memory catalogue and queue that runs anywhere.

Like the fake media player (page 02 of the walkthrough), it *behaves*: search
filters a catalogue, "play now" replaces the queue as YouTube Music does, "play
next" inserts after the current song. That lets the API, web page, CLI and
tests be developed on Linux.
"""

from ..library import (
    InsertPosition,
    LibraryController,
    LibraryUnavailableError,
    Queue,
    QueueItem,
    QueueItemNotFoundError,
    Song,
)

# Invented, like the fake player's tracks: no real artists in screenshots.
CATALOGUE: tuple[Song, ...] = (
    Song("fake0000001", "Signal Path", "The Test Patterns", "3:12"),
    Song("fake0000002", "Low Latency", "The Test Patterns", "2:48"),
    Song("fake0000003", "Port and Adapter", "Hexagon Club", "4:05"),
    Song("fake0000004", "Walking Skeleton", "Hexagon Club", "3:33"),
    Song("fake0000005", "Two Machines", "Studio & Bedroom", "5:01"),
    Song("fake0000006", "Grace Period", "Studio & Bedroom", "2:59"),
    Song("fake0000007", "Read Your Writes", "Eventual Consistency", "3:40"),
    Song("fake0000008", "Cross-Site Hijack", "Eventual Consistency", "4:22"),
)


class FakeLibraryController(LibraryController):
    # As in the fake player: no method awaits while changing state, so requests
    # can't interleave and no lock is needed.

    def __init__(self, catalogue: tuple[Song, ...] = CATALOGUE, available: bool = True) -> None:
        self._catalogue = catalogue
        self._queue: list[Song] = list(catalogue[:4])
        self._current = 0
        # Public on purpose: set to False to simulate the YouTube Music window
        # not being ready (the "library unavailable" path).
        self.available = available

    def _require_available(self) -> None:
        if not self.available:
            raise LibraryUnavailableError("the YouTube Music window is not ready")

    async def is_available(self) -> bool:
        return self.available

    async def search(self, query: str) -> list[Song]:
        self._require_available()
        words = query.lower().split()
        return [
            song
            for song in self._catalogue
            if all(word in f"{song.title} {song.artist}".lower() for word in words)
        ]

    async def get_queue(self) -> Queue:
        self._require_available()
        items = tuple(
            QueueItem(
                index=index,
                video_id=song.video_id,
                title=song.title,
                artist=song.artist,
                duration=song.duration,
                is_current=index == self._current,
                is_autoplay=False,
            )
            for index, song in enumerate(self._queue)
        )
        return Queue(items=items, current_index=self._current if self._queue else None)

    async def jump_to(self, index: int) -> None:
        self._require_available()
        if not 0 <= index < len(self._queue):
            raise QueueItemNotFoundError(f"there is no queue item {index}")
        self._current = index

    async def play(self, video_id: str, position: InsertPosition) -> None:
        self._require_available()
        song = self._find(video_id)
        if position == InsertPosition.NOW:
            # YouTube Music starts a radio: the song, then related ones.
            self._queue = [song] + [other for other in self._catalogue if other != song][:3]
            self._current = 0
        elif position == InsertPosition.NEXT:
            self._queue.insert(self._current + 1, song)
        else:
            self._queue.append(song)

    def _find(self, video_id: str) -> Song:
        for song in self._catalogue:
            if song.video_id == video_id:
                return song
        # A made-up id still plays in YouTube Music; the fake names it plainly.
        return Song(video_id, f"Song {video_id}", None, None)
