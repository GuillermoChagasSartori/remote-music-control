"""Unit tests for WebViewPage, with a stand-in for pywebview's window.

The stand-in behaves like pywebview in the way that matters: evaluate_js
returns at once, and the Promise's value arrives later through the callback,
on a different thread.
"""

import asyncio
import threading

import pytest

from remote_music_control.app.page import READY_CHECK_SCRIPT, WebViewPage
from remote_music_control.library import LibraryError, LibraryUnavailableError


class FakeWindow:
    def __init__(self, answer=None, delay=0.01, error=None):
        self.answer = answer
        self.delay = delay
        self.error = error
        self.scripts = []

    def evaluate_js(self, script, callback=None):
        self.scripts.append(script)
        if self.error:
            raise self.error
        if self.answer is not None or callback:
            answer = self.answer(script) if callable(self.answer) else self.answer
            threading.Timer(self.delay, callback, args=(answer,)).start()
        return "true"  # what pywebview returns for a Promise


def loaded_page(window):
    page = WebViewPage(window)
    page.on_loaded()
    return page


def test_evaluate_waits_for_the_value_from_another_thread():
    window = FakeWindow(answer={"ok": True, "value": 42})
    assert asyncio.run(loaded_page(window).evaluate("1 + 1")) == {"ok": True, "value": 42}


def test_every_script_is_wrapped_in_a_promise():
    # Otherwise pywebview never calls (or forgets) the callback for plain values.
    window = FakeWindow(answer=1)
    asyncio.run(loaded_page(window).evaluate("getQueue()"))
    assert window.scripts == ["Promise.resolve(getQueue())"]


def test_nothing_is_sent_before_the_page_has_loaded():
    window = FakeWindow(answer=1)
    page = WebViewPage(window)
    with pytest.raises(LibraryUnavailableError, match="hasn't loaded"):
        asyncio.run(page.evaluate("1"))
    assert window.scripts == []


def test_navigating_away_makes_the_page_unavailable_until_it_loads_again():
    window = FakeWindow(answer=1)
    page = loaded_page(window)
    page.on_before_load()
    with pytest.raises(LibraryUnavailableError):
        asyncio.run(page.evaluate("1"))
    page.on_loaded()
    assert asyncio.run(page.evaluate("1")) == 1


def test_a_window_error_becomes_a_library_error():
    window = FakeWindow(error=RuntimeError("window destroyed"))
    with pytest.raises(LibraryError, match="window destroyed"):
        asyncio.run(loaded_page(window).evaluate("1"))


def test_a_late_value_after_the_caller_gave_up_is_ignored():
    window = FakeWindow(answer=1, delay=0.2)
    page = loaded_page(window)

    async def scenario():
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await asyncio.wait_for(page.evaluate("1"), 0.01)
        await asyncio.sleep(0.3)  # the value arrives now; nothing may crash

    asyncio.run(scenario())


@pytest.mark.parametrize(("answer", "ready"), [(True, True), (False, False), ("true", False), (None, False)])
def test_ready_only_when_the_check_says_exactly_true(answer, ready):
    window = FakeWindow(answer=lambda script: answer)
    assert asyncio.run(loaded_page(window).is_ready()) is ready
    assert window.scripts == [f"Promise.resolve({READY_CHECK_SCRIPT})"]


def test_not_ready_before_loading_or_when_the_window_fails():
    assert asyncio.run(WebViewPage(FakeWindow(answer=True)).is_ready()) is False
    assert asyncio.run(loaded_page(FakeWindow(error=RuntimeError("gone"))).is_ready()) is False
