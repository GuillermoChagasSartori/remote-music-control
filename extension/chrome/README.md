# Remote Music Control — Chrome extension

Lets the Remote Music Control server on the studio PC **search YouTube Music**,
**read the queue**, **jump within it**, and **play, play next or add songs to
the queue** — things Windows' media controls can't do. Design and findings:
[ADR 0013](../../docs/decisions/0013-chrome-extension-for-search-and-queue.md).

## Install (on the PC that plays the music)

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and select this folder:
   `<repository>\extension\chrome`
3. The card **Remote Music Control** appears, with ID
   `hgchacmedljophnblmbdmogbkafcmdol`.
4. Keep a YouTube Music tab open. The server log shows
   `Chrome extension connected (version 1.0.0)`.

After updating the repository (`git pull`), click the **reload** arrow on the
extension's card.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | Extension description, permissions, and the public `key` that fixes its ID |
| `background.js` | Service worker: WebSocket to `ws://127.0.0.1:8000/extension/ws`, keepalive, reconnect with backoff, runs page functions in the YouTube Music tab |
| `youtube-music.js` | **All YouTube Music internals**: search, queue, jump, play now, add to queue. The file to fix when YouTube Music changes |

## Notes

- **The `key` in the manifest** is a public key. Chrome derives the extension ID
  from it, so the ID is the same on every machine and folder. The server accepts
  the extension's connection only from that ID (`RMC_EXTENSION_ID`). There is no
  private key: an unpacked extension doesn't need one.
- **Permissions:** `tabs` to find the YouTube Music tab, `scripting` to run code
  in it, `alarms` to wake the worker if Chrome stopped it; host access only to
  `music.youtube.com` and the local server.
- **Port:** the server address is `127.0.0.1:8000` in `background.js` and
  `manifest.json`. If `RMC_PORT` is changed, change both.
