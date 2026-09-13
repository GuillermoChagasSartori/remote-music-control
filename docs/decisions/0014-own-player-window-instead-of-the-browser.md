# 0014 — The app shows YouTube Music in its own window

**Status:** Accepted · 2026-09-13 · Supersedes 0003, 0011 and 0013 · Based on a spike on the studio PC

## Context

Remote Music Control is going to be distributed to other people as a download
from a website: enter the site, download, install, done. Up to Phase 8 it
needed a developer's setup on the studio PC — a repository clone, uv, a
PowerShell script for the logon task, and a Chrome extension loaded in
developer mode for search and the queue (ADR 0013). None of that is
acceptable for a customer.

The extension was the hardest part to remove. Publishing it in the Chrome Web
Store costs a registration fee and a review, and installing any extension is an
extra step outside our installer. Two alternatives were considered:

1. **Automate the user's browser from outside** with Windows UI Automation
   (reading and clicking the page's accessibility tree). No extension, but slow,
   dependent on the page's visible layout and language, and unable to search
   without disturbing what the user sees.
2. **Show YouTube Music in our own window**, using WebView2 — the Chromium-based
   browser component built into Windows 10 and 11 — and run the page code from
   ADR 0013 in it directly.

Option 2 was chosen with the owner, on condition that a spike confirmed it. The
question that could sink it: Google blocks sign-in inside some embedded
browsers ("This browser or app may not be secure").

## Findings (spike on the studio PC, WebView2 runtime 152, pywebview 6.2.1)

| Question | Result |
|---|---|
| Google sign-in inside the window | **Works.** Normal sign-in with email and password; no warning |
| Sign-in survives closing and reopening the window | **Yes**, with a persistent profile folder (`private_mode=False`, `storage_path`) |
| Search, read the queue, jump, play now, play next, add at end | **All work**, with the unchanged page functions from ADR 0013 |
| Playback starts from code without a click in the window | **Yes** (no autoplay block) |
| Windows media controls (SMTC) see the window | **Yes**, as app id `msedgewebview2.exe`; the existing Windows adapter paused, resumed and skipped it unchanged |
| Per-app volume | **Works**; the audio session belongs to a `msedgewebview2.exe` process **whose parent chain leads to our process** |
| Can our process give the window its own SMTC name (AppUserModelID)? | **No**: the id stays `msedgewebview2.exe` |
| Can the window reuse accounts from the user's Chrome? | **No, by design**: WebView2 has its own profile. Reading Chrome's cookies or passwords is what password-stealing malware does; Chrome encrypts them against it |
| Waiting for async page functions | pywebview's `evaluate_js` returns immediately for a Promise unless given a callback, which then receives the resolved value |

## Decision

- **The product is a Windows app**: a window showing `music.youtube.com`, with
  the server (API, web page, pairing page) running inside the same process.
  Phones and computers on the LAN keep using the web page, as before.
- **Window library: pywebview** (BSD licence). It wraps WebView2 on Windows in a
  few lines of Python, and its `evaluate_js` gives what the library adapter
  needs.
- **Search and the queue: `PageLibraryController`**
  (`adapters/page_library.py`). It wraps `youtube-music.js` in a script with a
  call to one function and has the page evaluate it. The `LibraryController`
  port, the API, the web page and the CLI don't change. The window sits behind
  a small `YouTubeMusicPage` interface, so the adapter is tested on Linux with
  a stand-in.
- **Removed:** the Chrome extension, its WebSocket endpoint and bridge, the
  `websockets` dependency, `RMC_EXTENSION_ID`; and the developer path for the
  studio PC — `RMC_CONTROLLER`, `RMC_PLAYER_APPS` and the logon-task scripts.
  `music-server` remains as the development server with the fake adapters.
  Tag `v0.8.0` keeps the extension-based version.
- **Closing the window hides it in the tray**, so music keeps playing; the tray
  menu has Quit.
- **Start at logon: an ordinary "run at logon" registry entry**, chosen in the
  installer (ticked by default). The watchdog task of ADR 0011 goes: it would
  reopen the app a minute after the user chose Quit. A crash is no longer
  restarted until the next logon — acceptable for a desktop app, and visible
  to the user, who can reopen it from the Start menu.
- **Volume is tied to our own process tree**, not just the process name, so
  other WebView2 apps (Teams, the new Outlook, Widgets) are never changed.
- **Languages:** English and Portuguese, for the app and the installer.

## Consequences

- One download, no extension, no developer mode, no browser requirements
  beyond the WebView2 runtime that Windows 10 and 11 ship.
- The customer signs in to YouTube Music once, in our window. Typing the
  password can't be avoided (see findings); a passkey through Windows Hello, if
  the account has one, should make it a fingerprint or PIN — still to be tested.
- Music plays in our window instead of the customer's browser tab.
- **Media controls are matched by name only.** Windows reports every WebView2
  app as `msedgewebview2.exe`, so if another WebView2 app publishes a media
  session at the same time, play/pause could reach it. The adapter prefers the
  session that is playing; the case is rare and documented.
- **Higher risk under YouTube's terms of service** than a browser extension:
  an app that embeds YouTube Music is more visible than a tab. The owners have
  been told; it doesn't change the technical design.
- The fragility of ADR 0013 remains: the page functions use undocumented
  internals. They still live in one file, `youtube-music.js`.
- The studio PC's development setup (logon task running `music-server` from a
  clone) is removed along with its scripts; the studio PC runs the app instead.
