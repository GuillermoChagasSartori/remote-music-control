"""WindowsMediaController: the real adapter, for a browser playing on Windows.

Two Windows APIs are combined behind the one MediaController port:

- **SMTC** (System Media Transport Controls, via pywinrt) for play/pause/skip
  and for reading what is playing. Browsers publish their media sessions to it;
  it is what the Windows media flyout uses. See docs/decisions/0002.
- **Core Audio** (via pycaw) for the volume of the browser process only, not
  the whole system. SMTC has no volume control.

Both only see media and audio from the *interactive desktop session*. A process
started over SSH or as a Windows service runs in session 0 and gets "access
denied" from SMTC; see docs/decisions/0003.

This module imports Windows-only packages, so it must only be imported on
Windows. server.py imports it lazily, only when RMC_CONTROLLER=windows.
"""

import sys

if sys.platform != "win32":
    raise ImportError("the Windows media adapter can only be used on Windows")

# COM (the Windows component system under both pywinrt and pycaw) requires each
# thread to choose a threading model. pywinrt uses the multi-threaded apartment;
# comtypes (imported by pycaw) reads this flag on import and would otherwise ask
# for the single-threaded one. It must be set before pycaw is imported.
sys.coinit_flags = 0  # 0 = COINIT_MULTITHREADED

import asyncio  # noqa: E402  (imports after the flag, on purpose)
import time  # noqa: E402
from collections.abc import Awaitable, Callable  # noqa: E402

import psutil  # noqa: E402
from pycaw.pycaw import AudioUtilities  # noqa: E402
from winrt.windows.media.control import (  # noqa: E402
    GlobalSystemMediaTransportControlsSession as SmtcSession,
)
from winrt.windows.media.control import (  # noqa: E402
    GlobalSystemMediaTransportControlsSessionManager as SmtcSessionManager,
)
from winrt.windows.media.control import (  # noqa: E402
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as SmtcStatus,
)

from ..media_controller import (  # noqa: E402
    MediaController,
    MediaControllerError,
    NoMediaSessionError,
    NowPlaying,
    PlaybackStatus,
    validate_volume,
)

# SMTC has more states than our port (closed, opened, changing...). Anything
# that isn't clearly playing or paused is reported as stopped.
STATUS_FROM_SMTC = {
    SmtcStatus.PLAYING: PlaybackStatus.PLAYING,
    SmtcStatus.PAUSED: PlaybackStatus.PAUSED,
}

# Chrome deletes its SMTC session on every track change and creates a new one
# ~0.8–1 s later (measured). A session missing for less than this long is
# treated as "changing tracks", not "player closed". This is a *grace period*
# (a form of debouncing): short blips are absorbed instead of reported.
SESSION_GAP_GRACE_SECONDS = 2.0
SESSION_WAIT_POLL_SECONDS = 0.1

# After a skip, the new track takes ~1 s to appear (see the gap above). Skip
# commands wait up to this long for it, so whoever reads the state right after
# "next" sees the new track rather than the old one.
SKIP_SETTLE_TIMEOUT_SECONDS = 2.0


class WindowsMediaController(MediaController):
    def __init__(self, player_apps: tuple[str, ...]) -> None:
        """`player_apps`: executable names to control, e.g. ("chrome.exe",).

        The same names match both the SMTC session's app id and the audio
        session's process name — for browsers like Chrome they are identical.
        """
        if not player_apps:
            raise ValueError("WindowsMediaController needs at least one player app name")
        self._player_apps = tuple(name.lower() for name in player_apps)
        # The session manager is requested once and kept. Individual sessions
        # are NOT kept: they are looked up on every call, so when the browser
        # is closed and reopened the next call simply finds the new session.
        self._manager: SmtcSessionManager | None = None
        # For the grace period: when a session was last seen, and what it showed.
        self._last_seen_at = 0.0  # time.monotonic() value; 0 = never
        self._last_now_playing: NowPlaying | None = None

    def _in_grace_period(self) -> bool:
        # monotonic() is a clock that only moves forward, unaffected by the
        # user or NTP changing the wall-clock time — the right tool for timeouts.
        return time.monotonic() - self._last_seen_at < SESSION_GAP_GRACE_SECONDS

    # --- Finding the player -------------------------------------------------

    async def _find_session(self) -> SmtcSession | None:
        if self._manager is None:
            self._manager = await SmtcSessionManager.request_async()

        candidates = [
            session
            for session in self._manager.get_sessions()
            if session.source_app_user_model_id.lower() in self._player_apps
        ]
        if not candidates:
            return None
        self._last_seen_at = time.monotonic()
        # If more than one matching app has a session, prefer the one playing.
        for session in candidates:
            if session.get_playback_info().playback_status == SmtcStatus.PLAYING:
                return session
        return candidates[0]

    async def _require_session(self) -> SmtcSession:
        session = await self._find_session()
        # Session missing but seen moments ago: probably mid track change, so
        # wait for it to come back instead of failing (e.g. "next" pressed twice).
        while session is None and self._in_grace_period():
            await asyncio.sleep(SESSION_WAIT_POLL_SECONDS)
            session = await self._find_session()
        if session is None:
            raise NoMediaSessionError(
                f"no media session from {', '.join(self._player_apps)} — is the player open?"
            )
        return session

    def _audio_controls(self) -> list:
        """The per-application volume controls of every matching audio session.

        A browser can own several audio sessions; all of them are changed
        together so the volume behaves as one control.
        """
        controls = []
        for audio_session in AudioUtilities.GetAllSessions():
            try:
                process = audio_session.Process
                name = process.name().lower() if process is not None else ""
            except psutil.Error:
                continue  # the process exited while we were looking; skip it
            if name in self._player_apps:
                controls.append(audio_session.SimpleAudioVolume)
        if not controls:
            raise NoMediaSessionError(
                f"no audio session from {', '.join(self._player_apps)} — is the player open?"
            )
        return controls

    # --- Transport ------------------------------------------------------------

    async def _send(self, action: str, command: Callable[[SmtcSession], Awaitable[bool]]) -> None:
        """Run one SMTC command and turn its failure modes into port errors."""
        session = await self._require_session()
        try:
            accepted = await command(session)
        except OSError as error:  # WinRT failures surface as OSError
            raise MediaControllerError(f"'{action}' failed: {error}") from error
        # SMTC commands return False when the player refuses (e.g. the control
        # is disabled). Silently ignoring that would hide real problems.
        if not accepted:
            raise MediaControllerError(f"the player refused '{action}'")

    async def play(self) -> None:
        await self._send("play", lambda session: session.try_play_async())

    async def pause(self) -> None:
        await self._send("pause", lambda session: session.try_pause_async())

    async def toggle_play_pause(self) -> None:
        await self._send("play/pause", lambda session: session.try_toggle_play_pause_async())

    async def next_track(self) -> None:
        before = await self.now_playing()
        await self._send("next", lambda session: session.try_skip_next_async())
        await self._wait_for_track_change(before)

    async def previous_track(self) -> None:
        before = await self.now_playing()
        await self._send("previous", lambda session: session.try_skip_previous_async())
        await self._wait_for_track_change(before)

    async def _wait_for_track_change(self, before: NowPlaying | None) -> None:
        """Return once the playing track differs from `before`, or after a timeout.

        The timeout matters: "previous" late in a song restarts the same track,
        so there may be no change to wait for. The command already succeeded;
        this only delays the reply until the new state is readable.
        """
        deadline = time.monotonic() + SKIP_SETTLE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(SESSION_WAIT_POLL_SECONDS)
            current = await self.now_playing()
            if before is None or current is None:
                return
            if (current.title, current.artist) != (before.title, before.artist):
                return

    # --- Volume ----------------------------------------------------------------
    #
    # pycaw calls are synchronous, but they are fast local calls, so running
    # them directly inside async methods is fine (docs/decisions/0005).
    #
    # Volume depends only on the browser's *audio* session, not the SMTC one:
    # the audio session survives track changes, so volume keeps working during
    # the SMTC gap described at the top of this file.

    async def get_volume(self) -> int:
        # Windows stores volume as a float 0.0–1.0; the port uses integers 0–100.
        return round(self._audio_controls()[0].GetMasterVolume() * 100)

    async def set_volume(self, level: int) -> None:
        validate_volume(level)
        for control in self._audio_controls():
            control.SetMasterVolume(level / 100, None)  # None: no event context

    async def is_muted(self) -> bool:
        return bool(self._audio_controls()[0].GetMute())

    async def set_muted(self, muted: bool) -> None:
        for control in self._audio_controls():
            control.SetMute(muted, None)

    # --- State -------------------------------------------------------------------

    async def now_playing(self) -> NowPlaying | None:
        session = await self._find_session()
        if session is not None:
            try:
                properties = await session.try_get_media_properties_async()
                smtc_status = session.get_playback_info().playback_status
            except OSError:
                # The session vanished between finding and reading it; treat it
                # like a missing session below.
                session = None
            else:
                self._last_now_playing = NowPlaying(
                    title=properties.title,
                    artist=properties.artist,
                    album=properties.album_title or None,  # SMTC reports "" for "no album"
                    status=STATUS_FROM_SMTC.get(smtc_status, PlaybackStatus.STOPPED),
                )
                return self._last_now_playing

        # No session right now. Within the grace period, keep showing the last
        # track, so clients don't flash "nothing playing" on every skip.
        if self._in_grace_period():
            return self._last_now_playing
        self._last_now_playing = None
        return None
