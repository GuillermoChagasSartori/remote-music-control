"""Tests of the app's Windows-only parts — run only on Windows (e.g. the CI Windows job).

The window and the tray icon need a desktop session, which CI doesn't have;
they are covered by docs/testing-on-windows.md. What CI can check: the modules
import with their Windows-only packages, and the single-instance objects work.
"""

import sys
import threading

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only app parts")


def test_app_modules_import():
    import webview  # noqa: F401

    from remote_music_control.app import main, tray  # noqa: F401

    assert tray.ICON_FILE.is_file()


def test_only_the_first_instance_is_first_and_a_later_one_can_ask_it_to_show():
    from remote_music_control.app.single_instance import SingleInstance

    # Both objects live in this one process, which is enough: the names are
    # what a second copy of the app would find.
    first = SingleInstance()
    second = SingleInstance()
    assert first.is_first and not second.is_first

    shown = threading.Event()
    first.call_when_asked_to_show(shown.set)
    second.ask_first_instance_to_show()
    assert shown.wait(timeout=5)
