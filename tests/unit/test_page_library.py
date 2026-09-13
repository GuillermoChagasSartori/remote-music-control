"""Unit tests for PageLibraryController, with a stand-in for the YouTube Music window.

`RecordingPage` plays the window's part: it records the scripts it is asked to
evaluate and answers with whatever the test prepared, as the page functions in
youtube-music.js would.
"""

import asyncio
import json
import shutil
import subprocess

import pytest

from remote_music_control.adapters.page_library import (
    PAGE_FUNCTIONS_FILE,
    PageLibraryController,
    page_function_script,
)
from remote_music_control.library import (
    InsertPosition,
    LibraryError,
    LibraryUnavailableError,
    QueueItemNotFoundError,
)

SOURCE = "const PAGE_FUNCTIONS = {};"  # the real file's content doesn't matter to these tests


class RecordingPage:
    def __init__(self, *outcomes, ready=True):
        self.outcomes = list(outcomes)
        self.scripts = []
        self.ready = ready

    async def is_ready(self):
        return self.ready

    async def evaluate(self, script):
        self.scripts.append(script)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def library_with(*outcomes, **options):
    page = RecordingPage(*outcomes)
    return PageLibraryController(page, source=SOURCE, **options), page


def called(script):
    """The function name and arguments a generated script calls (its last line)."""
    call = script.splitlines()[-2]  # e.g. return PAGE_FUNCTIONS["search"](...["x"]);
    name = json.loads(call[call.index("[") + 1 : call.index("]")])
    args = json.loads(call[call.index("(...") + 4 : -2])
    return name, args


def test_search_calls_the_page_function_and_parses_songs():
    library, page = library_with({
        "ok": True,
        "value": [
            {"video_id": "abc", "title": "Aruarian Dance", "artist": "Nujabes", "duration": "4:05"},
            {"video_id": "def", "title": "Luv(sic)", "artist": None, "duration": ""},
        ],
    })
    songs = asyncio.run(library.search("nujabes"))

    assert called(page.scripts[0]) == ("search", ["nujabes"])
    assert [song.title for song in songs] == ["Aruarian Dance", "Luv(sic)"]
    assert songs[1].artist is None and songs[1].duration is None


def test_queue_gets_indexes_the_current_item_and_autoplay_flags():
    library, _ = library_with({
        "ok": True,
        "value": {"items": [
            {"video_id": "a", "title": "One", "is_current": False},
            {"video_id": "b", "title": "Two", "is_current": True},
            {"video_id": "c", "title": "Three", "is_current": False, "is_autoplay": True},
        ]},
    })
    queue = asyncio.run(library.get_queue())

    assert [item.index for item in queue.items] == [0, 1, 2]
    assert queue.current_index == 1
    assert [item.is_autoplay for item in queue.items] == [False, False, True]


@pytest.mark.parametrize(
    ("position", "expected_call"),
    [
        (InsertPosition.NOW, ("playNow", ["xyz"])),
        (InsertPosition.NEXT, ("addToQueue", ["xyz", "next"])),
        (InsertPosition.END, ("addToQueue", ["xyz", "end"])),
    ],
)
def test_play_picks_the_page_function_for_the_position(position, expected_call):
    library, page = library_with({"ok": True, "value": None})
    asyncio.run(library.play("xyz", position))
    assert called(page.scripts[0]) == expected_call


def test_jump_sends_the_index():
    library, page = library_with({"ok": True, "value": None})
    asyncio.run(library.jump_to(3))
    assert called(page.scripts[0]) == ("jumpTo", [3])


@pytest.mark.parametrize(
    ("kind", "exception"),
    [("not_found", QueueItemNotFoundError), ("page_changed", LibraryError), (None, LibraryError)],
)
def test_error_kinds_become_port_exceptions(kind, exception):
    library, _ = library_with({"ok": False, "kind": kind, "message": "explained"})
    with pytest.raises(exception, match="explained"):
        asyncio.run(library.jump_to(9))


@pytest.mark.parametrize("outcome", [None, "text", [], {"value": 1}])
def test_a_missing_or_strange_outcome_is_a_library_error(outcome):
    library, _ = library_with(outcome)
    with pytest.raises(LibraryError):
        asyncio.run(library.get_queue())


@pytest.mark.parametrize(
    "value",
    [{"not": "a list"}, [{"title": "no video id"}], ["not an object"]],
)
def test_malformed_search_values_are_library_errors(value):
    library, _ = library_with({"ok": True, "value": value})
    with pytest.raises(LibraryError):
        asyncio.run(library.search("x"))


def test_malformed_queue_is_a_library_error():
    library, _ = library_with({"ok": True, "value": ["not", "a", "queue"]})
    with pytest.raises(LibraryError, match="unexpected queue"):
        asyncio.run(library.get_queue())


def test_no_page_is_unavailable():
    library, _ = library_with(LibraryUnavailableError("the YouTube Music window is not open"))
    with pytest.raises(LibraryUnavailableError):
        asyncio.run(library.search("x"))


def test_availability_is_the_page_being_ready():
    page = RecordingPage(ready=False)
    assert asyncio.run(PageLibraryController(page, source=SOURCE).is_available()) is False
    page.ready = True
    assert asyncio.run(PageLibraryController(page, source=SOURCE).is_available()) is True


def test_a_page_that_never_answers_times_out():
    class SilentPage(RecordingPage):
        async def evaluate(self, script):
            await asyncio.sleep(10)

    library = PageLibraryController(SilentPage(), source=SOURCE, call_timeout=0.05)
    with pytest.raises(LibraryError, match="didn't answer 'search'"):
        asyncio.run(library.search("x"))


# --- The generated script --------------------------------------------------------------


def test_arguments_are_embedded_as_json_so_they_stay_strings():
    hostile = '"); alert("hi'
    script = page_function_script(SOURCE, "search", [hostile])
    assert json.dumps(hostile) in script
    assert called(script) == ("search", [hostile])


def test_the_real_page_functions_file_defines_every_function_the_adapter_calls():
    source = PAGE_FUNCTIONS_FILE.read_text(encoding="utf-8")
    assert "export " not in source  # evaluated as a script, where `export` is a syntax error
    assert "const PAGE_FUNCTIONS = { search, getQueue, jumpTo, playNow, addToQueue };" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js to parse JavaScript")
def test_the_generated_script_is_valid_javascript(tmp_path):
    # `node --check` parses without running: it catches a syntax error in
    # youtube-music.js or in the wrapper before it reaches the studio PC.
    source = PAGE_FUNCTIONS_FILE.read_text(encoding="utf-8")
    script_file = tmp_path / "script.js"
    script_file.write_text(page_function_script(source, "search", ['a "quoted" query']), encoding="utf-8")
    result = subprocess.run(["node", "--check", str(script_file)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
