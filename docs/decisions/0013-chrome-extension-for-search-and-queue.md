# 0013 — A Chrome extension for search and the queue

**Status:** Accepted · 2026-09-13 · Based on a spike (branch `spike-phase8`)

## Context

P1 asks for **searching YouTube Music and playing a result**, and for
**viewing the queue and jumping within it**. SMTC (ADR 0002) only offers
transport controls and the current track: it knows nothing about search or the
queue. That information exists only inside the YouTube Music web app running in
the browser on the studio PC.

Decisions taken with the owner before the spike: Chrome first (Firefox after
the project succeeds in Chrome); search inside the YouTube Music tab using the
signed-in session; songs and videos only in results; tapping a result offers
**play now**, **play next** and **add to queue**; the queue view shows the
queue and jumps within it; the extension is installed unpacked (developer mode).

Nothing here is documented by Google, so the approach was tested first with a
**spike**: a throwaway relay server on `127.0.0.1:8765` and a minimal Manifest V3
extension, loaded on the studio PC (Chrome 153), with probes run from a
terminal over the relay.

## Findings (measured on the studio PC)

| Question | Result |
|---|---|
| Can an MV3 background service worker keep a WebSocket to a local server? | **Yes.** 23 min on one worker without a drop; keepalive every 20 s, never late; reconnected ~2 s after a server restart; only disconnects were extension reloads (code 1001) |
| Chrome local-network permission prompt? | **None** for an extension with host permission for `http://127.0.0.1:…` |
| WebSocket `Origin` header | `chrome-extension://<extension id>` — usable to accept only our extension |
| Read the queue | **Yes**, from the page's queue store (`ytmusic-app.queue.store`, a Redux-style store): items with `videoId`, title, byline, duration, and `selectedItemIndex`. The rendered `ytmusic-player-queue-item` elements expose the same data via `.data` |
| Jump in the queue | **Yes**, by clicking the queue item's play button inside the page; confirmed through SMTC |
| Search without disturbing the tab | **Yes**, `POST /youtubei/v1/search` from the page with `ytcfg` context: signed in (personalized), ~0.6 s |
| Play a search result now | **Yes**, dispatching a `yt-navigate` event with a `watchEndpoint` on `ytmusic-app`: no page reload. **Replaces the queue** with a radio for that song, as clicking a song in YouTube Music does |
| Play next / add to queue | **Yes**, in two steps: `app.networkManager.fetch("/music/get_queue", {videoIds, queueInsertPosition, queueContextParams})` returns `queueDatas[].content`; then `ytmusic-player-queue.dispatch({type: "ADD_ITEMS", payload: {index, items, nextQueueItemId, shuffleEnabled: false, shouldAssignIds: true}})`. Song appears at the intended position in the store and the visible queue; **playback is not interrupted** |
| Approaches that did **not** add to the queue | Passing the menu's `queueAddEndpoint` to `resolveCommand` or `handleServiceEndpoint`; a `yt-action` event; creating a `ytmusic-menu-service-item-renderer` and clicking or tapping it |

A lesson from the spike itself: the probe helper's PowerShell `ConvertTo-Json`
serializes only two levels deep by default, silently turning deeper arguments
into text. Several failed attempts above were re-run after fixing it; the
store-dispatch approach was the one that worked with intact arguments.

## Decision

- **Architecture:**
  ```
  phone / Ubuntu / CLI ──HTTP──▶ server ──WebSocket──▶ extension background worker
                                   ▲                      │ chrome.scripting (world: MAIN)
                                   └────── replies ◀──────┘ YouTube Music tab
  ```
  Clients keep talking only to the server. The server forwards library requests
  to the extension over one WebSocket and waits for the reply (request/response
  matched by id — RPC over WebSocket).
- **A second port, `LibraryController`** (search, queue, jump, play now / next /
  at end), with an extension-backed adapter and a fake, so the API, web page, CLI
  and tests stay independent of Chrome and run on Linux and in CI.
- **All YouTube Music internals live in one extension file**, so changes by
  Google are fixed in one place.
- **Security of the WebSocket endpoint:** browsers let any web page open a
  WebSocket to `127.0.0.1` (no CORS protection — *Cross-Site WebSocket
  Hijacking*). The server accepts the extension's connection only from
  loopback, with a loopback `Host` header, and with
  `Origin: chrome-extension://<our id>`. The extension gets a fixed ID through
  a public `key` in its manifest, so the allowed origin never changes.
  *(Revised during implementation — see "Implementation notes".)*
- **New dependency:** `websockets`, the WebSocket implementation uvicorn needs.
- **Installation:** unpacked in Chrome developer mode, from the repository folder.

## Consequences

- Search and the queue work against the user's real, signed-in YouTube Music.
- **Fragile by nature:** `ytcfg`, the search endpoint's JSON shape, the queue
  store's `ADD_ITEMS` action and the `yt-navigate` event are all undocumented
  and can change without notice. Mitigations: one isolated extension file, clear
  errors reported to clients when a probe-like check fails, and manual checks in
  the Windows checklist.
- "Play now" replaces the queue (YouTube Music's own behaviour).
- Library features need Chrome with the extension loaded and a YouTube Music tab
  open; without them the API answers with a clear error, while playback controls
  (SMTC) keep working.
- Each extension update needs one click on "reload" in `chrome://extensions`.
- Firefox needs a separate adaptation later (background page instead of a
  service worker, and signing by Mozilla for permanent installation).

## Implementation notes — 2026-09-13

Decisions and findings from building the real extension, after the spike:

- **No token for the extension (changed from the plan above).** The token was
  meant as an extra check on the extension's WebSocket. Working it through, it
  adds nothing: web pages can't forge the `Origin` header (the browser sets it),
  other devices are stopped by the loopback check even with a forged origin, and
  a program already running on the studio PC could read the config file that
  holds the token anyway. Dropping it removed a pairing step for the extension.
  Tests cover the refusals — a web page's origin, another extension, no origin,
  another device forging the origin, a DNS-rebinding host — plus a control case
  proving the legitimate extension is accepted.
- **"Add to queue" goes to the end of the user's queue, before autoplay.**
  YouTube Music's visible list is the queue followed by autoplay suggestions;
  its own "Add to queue" inserts before the suggestions. The API keeps that
  behaviour, and each queue item carries `is_autoplay` so the web page and CLI
  can label the suggestions.
- **Search "top result" cards.** The first shelf of results can be an artist
  card (its songs omit the artist, which is the card's title) or a song card
  (the card itself is playable). Both are handled; the first version missed the
  top song entirely and showed songs without artists.
- **Known transient:** right after an insert, an item can be labelled autoplay
  for one refresh (the page's store updates a moment after its list); the next
  refresh corrects it.
