"""Unit tests for processes.py, with real child processes of the test run."""

import os
import subprocess
import sys

import psutil

from remote_music_control.processes import is_descendant_of

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


def test_a_child_and_a_grandchild_are_descendants():
    # The child starts a grandchild and prints its id, like WebView2's helper processes.
    code = "import subprocess, sys, time; p = subprocess.Popen(%r); print(p.pid, flush=True); time.sleep(30)" % SLEEP
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        grandchild = psutil.Process(int(child.stdout.readline()))
        assert is_descendant_of(psutil.Process(child.pid), os.getpid())
        assert is_descendant_of(grandchild, os.getpid())
        assert is_descendant_of(grandchild, child.pid)
    finally:
        for process in psutil.Process(child.pid).children(recursive=True) + [psutil.Process(child.pid)]:
            process.kill()
        child.wait()
        child.stdout.close()


def test_an_unrelated_process_is_not_a_descendant():
    child = subprocess.Popen(SLEEP)
    try:
        # This test process was not started by its own child.
        assert not is_descendant_of(psutil.Process(os.getpid()), child.pid)
    finally:
        child.kill()
        child.wait()
