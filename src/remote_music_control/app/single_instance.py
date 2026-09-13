"""One running copy of the app per Windows user session (Windows only).

Opening the app from the Start menu while it already runs in the tray should
show the existing window, not start a second copy that would fail to listen on
the same port and play music twice.

Two named kernel objects, found by name by any process in the same session:

- a *mutex* ("mutual exclusion" lock): the first copy creates it; a later copy
  finds it already exists and knows it isn't alone;
- an *event*: the later copy signals it, and the first copy — waiting on it in
  a background thread — shows its window.

Windows deletes both when the processes holding them end, even after a crash,
so a stale lock can never stop the app from starting. This kind of object
is called *interprocess communication* (IPC), and the pattern a *single-instance
application*.
"""

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

# "Local\" scopes the names to this user's logon session: another user signed
# in on the same PC (fast user switching) gets their own copy.
MUTEX_NAME = "Local\\RemoteMusicControl.Instance"
EVENT_NAME = "Local\\RemoteMusicControl.ShowWindow"

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
kernel32.WaitForSingleObject.restype = wintypes.DWORD


class SingleInstance:
    def __init__(self) -> None:
        # Kept open for the life of the process: closing the handle would let
        # a second copy believe it is the first.
        self._mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        self.is_first = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        # bManualReset=False makes it an auto-reset event, bInitialState=False
        # starts it unsignalled: each signal wakes the waiting thread exactly once.
        self._show_event = kernel32.CreateEventW(None, False, False, EVENT_NAME)
        if not self._mutex or not self._show_event:
            raise OSError(ctypes.get_last_error(), "couldn't create the single-instance objects")

    def ask_first_instance_to_show(self) -> None:
        kernel32.SetEvent(self._show_event)

    def call_when_asked_to_show(self, show: Callable[[], None]) -> None:
        """Run `show` every time another copy of the app is started."""

        def wait_for_requests() -> None:
            while kernel32.WaitForSingleObject(self._show_event, INFINITE) == WAIT_OBJECT_0:
                show()

        threading.Thread(target=wait_for_requests, name="show-requests", daemon=True).start()
