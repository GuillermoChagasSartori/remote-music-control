"""Run the HTTP server on a background thread, so the window can have the main thread.

`uvicorn.run()` (used by the development server) takes over the thread it is
called on until the server stops. In the app, the main thread belongs to the
window, so the server gets a thread of its own. uvicorn.Server offers what that
needs: `started` tells when it is listening, `should_exit` asks it to stop.
"""

import logging
import threading
import time
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI

logger = logging.getLogger(__name__)

START_TIMEOUT_SECONDS = 20.0
POLL_SECONDS = 0.05


class ServerStartError(Exception):
    """The server couldn't start listening (e.g. the port is in use)."""


class BackgroundServer:
    def __init__(self, build_app: Callable[[], FastAPI], host: str, port: int) -> None:
        """`build_app` runs on the server's thread, not the caller's.

        That matters on Windows: the media adapter sets up COM (the Windows
        component system) for the thread that imports it, in a mode that
        would conflict with the window's thread.
        """
        self._build_app = build_app
        self._host = host
        self._port = port
        self._server: uvicorn.Server | None = None
        self._error: BaseException | None = None
        # daemon=True: if the program ends without stopping the server first,
        # this thread doesn't keep it alive.
        self._thread = threading.Thread(target=self._run, name="http-server", daemon=True)

    def _run(self) -> None:
        try:
            config = uvicorn.Config(
                self._build_app(),
                host=self._host,
                port=self._port,
                log_config=None,  # use the app's logging setup (see server.configure_logging)
                access_log=False,  # the web page polls every second (see server.run)
            )
            self._server = uvicorn.Server(config)
            self._server.run()
        except BaseException as error:
            # BaseException, because uvicorn reports a port already in use by
            # calling sys.exit(), which raises SystemExit.
            self._error = error

    def start(self) -> None:
        """Start the server and return once it is listening. Raises ServerStartError."""
        self._thread.start()
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._server is not None and self._server.started:
                logger.info("listening on %s:%d", self._host, self._port)
                return
            if not self._thread.is_alive():
                break
            time.sleep(POLL_SECONDS)
        self.stop()
        if isinstance(self._error, SystemExit) or self._error is None:
            # uvicorn has already logged the reason, e.g. "address already in use".
            raise ServerStartError(f"the server couldn't listen on port {self._port} (is it already in use?)")
        raise ServerStartError(f"the server couldn't start: {self._error}") from self._error

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=10)
