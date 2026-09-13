"""Unit tests for FakeLibraryController: it must follow the library contract."""

import asyncio

import pytest

from remote_music_control.adapters.fake_library import CATALOGUE, FakeLibraryController
from remote_music_control.library import InsertPosition, LibraryUnavailableError, QueueItemNotFoundError


@pytest.fixture
def library() -> FakeLibraryController:
    return FakeLibraryController()


def queue_titles(library):
    return [item.title for item in asyncio.run(library.get_queue()).items]


def test_search_matches_all_words_in_title_or_artist(library):
    results = asyncio.run(library.search("hexagon walking"))
    assert [song.title for song in results] == ["Walking Skeleton"]


def test_search_is_case_insensitive_and_can_find_nothing(library):
    assert len(asyncio.run(library.search("THE TEST PATTERNS"))) == 2
    assert asyncio.run(library.search("no such song")) == []


def test_queue_starts_with_four_songs_and_the_first_is_current(library):
    queue = asyncio.run(library.get_queue())
    assert len(queue.items) == 4
    assert queue.current_index == 0
    assert [item.is_current for item in queue.items] == [True, False, False, False]
    assert [item.index for item in queue.items] == [0, 1, 2, 3]


def test_jump_changes_the_current_item(library):
    asyncio.run(library.jump_to(2))
    assert asyncio.run(library.get_queue()).current_index == 2


@pytest.mark.parametrize("index", [-1, 4, 99])
def test_jump_to_a_missing_item_is_an_error(library, index):
    with pytest.raises(QueueItemNotFoundError):
        asyncio.run(library.jump_to(index))


def test_play_now_replaces_the_queue_like_youtube_music(library):
    asyncio.run(library.play(CATALOGUE[6].video_id, InsertPosition.NOW))
    queue = asyncio.run(library.get_queue())
    assert queue.items[0].title == "Read Your Writes"
    assert queue.current_index == 0


def test_play_next_inserts_after_the_current_song_without_changing_it(library):
    asyncio.run(library.jump_to(1))
    asyncio.run(library.play(CATALOGUE[7].video_id, InsertPosition.NEXT))
    queue = asyncio.run(library.get_queue())
    assert queue.items[2].title == "Cross-Site Hijack"
    assert queue.current_index == 1


def test_play_at_end_appends(library):
    asyncio.run(library.play(CATALOGUE[5].video_id, InsertPosition.END))
    assert queue_titles(library)[-1] == "Grace Period"


def test_unavailable_library_rejects_everything(library):
    library.available = False
    assert asyncio.run(library.is_available()) is False
    for call in (
        lambda: library.search("x"),
        lambda: library.get_queue(),
        lambda: library.jump_to(0),
        lambda: library.play("fake0000001", InsertPosition.NEXT),
    ):
        with pytest.raises(LibraryUnavailableError):
            asyncio.run(call())
