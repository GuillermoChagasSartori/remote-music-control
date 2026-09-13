"""A small process helper, kept apart from the Windows adapter so it can be tested anywhere."""

import psutil


def is_descendant_of(process: psutil.Process, ancestor_pid: int) -> bool:
    """True if `ancestor_pid` started `process`, directly or through other processes.

    WebView2 plays audio in a helper process started by its browser process,
    which our app started: app -> msedgewebview2.exe -> msedgewebview2.exe
    (measured, ADR 0014). Walking up the parent chain finds our app in it.

    Raises psutil.Error if the process has already exited.
    """
    return any(parent.pid == ancestor_pid for parent in process.parents())
