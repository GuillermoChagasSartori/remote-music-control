// Remote Music Control — web client.
//
// Plain JavaScript with no framework and no build step (docs/decisions/0007).
// The page keeps no state of its own that matters: every second it asks the
// server for the current state and redraws. Buttons send a command, then ask
// for the state straight away instead of waiting for the next poll.

"use strict";

const POLL_INTERVAL_MS = 1000;
// After the user touches the volume slider, ignore the server's volume for this
// long, so a poll can't yank the slider back from under their finger.
const VOLUME_INPUT_GRACE_MS = 1500;
const MESSAGE_DURATION_MS = 4000;
const TOKEN_STORAGE_KEY = "remote-music-control.token";

const STATUS_LABELS = { playing: "Playing", paused: "Paused", stopped: "Stopped" };
const STATUS_SYMBOLS = { playing: "▶", paused: "⏸", stopped: "■" };

const player = document.getElementById("player");
const banner = document.getElementById("banner");
const statusLabel = document.getElementById("status");
const titleText = document.getElementById("title");
const artistText = document.getElementById("artist");
const albumText = document.getElementById("album");
const volumeSlider = document.getElementById("volume");
const volumeValue = document.getElementById("volume-value");
const muteButton = document.getElementById("mute");
const controls = document.querySelectorAll(".control, #volume");
const tokenForm = document.getElementById("token-form");
const tokenInput = document.getElementById("token-input");

// --- The access token -----------------------------------------------------
//
// The token is kept in localStorage so the browser remembers it between
// visits, and sent in an Authorization header with every API request.
//
// Pairing link: opening http://<server>:8000/#token=<token> stores the token
// and then removes it from the address bar. The part after "#" (the URL
// *fragment*) is never sent to the server, so it can't end up in any log.

let token = null;

function loadToken() {
  const match = location.hash.match(/^#token=(.+)$/);
  if (match) {
    // Remove the token from the address bar first, whatever happens next.
    history.replaceState(null, "", location.pathname + location.search);
    try {
      saveToken(decodeURIComponent(match[1]));
      return;
    } catch {
      // A damaged link (e.g. a cut-off "%" escape): ignore it and fall back to
      // a saved token or the token form, instead of stopping the whole script.
    }
  }
  try {
    token = localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    token = null;  // storage blocked (e.g. some private modes): ask each visit
  }
}

function saveToken(value) {
  token = value;
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, value);
  } catch {
    // Storage blocked: the token still works until the tab is closed.
  }
}

function showTokenForm(message) {
  clearTimeout(pollTimer);  // no point polling without a valid token
  player.dataset.status = "locked";
  statusLabel.textContent = "Locked";
  document.title = "Music";
  tokenForm.hidden = false;
  if (message) showBanner(message, "message");
  tokenInput.focus();
}

tokenForm.addEventListener("submit", (event) => {
  event.preventDefault();  // handle it here instead of reloading the page
  saveToken(tokenInput.value.trim());
  tokenInput.value = "";
  tokenForm.hidden = true;
  hideBanner();
  player.dataset.status = "connecting";
  schedulePoll(0);
});

// --- Talking to the server ------------------------------------------------

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// The single function that sends HTTP requests. Every call goes through here,
// so cross-cutting concerns like the token are handled in one place.
async function api(method, path, body) {
  const options = { method, headers: {} };
  if (token) {
    options.headers["Authorization"] = `Bearer ${token}`;
  }
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }

  // fetch() only throws on network failure (server down, Wi-Fi gone). An HTTP
  // error status like 409 still "succeeds", so it is checked separately below.
  const response = await fetch(path, options);

  if (!response.ok) {
    let detail = null;
    try {
      detail = (await response.json()).detail;
    } catch {
      // Body wasn't JSON; fall back to the status code.
    }
    const message = typeof detail === "string" ? detail : `Server error (HTTP ${response.status})`;
    throw new ApiError(response.status, message);
  }
  return response.status === 204 ? null : response.json();
}

// --- Drawing the state ----------------------------------------------------

let lastMuted = false;
let lastVolumeInputAt = 0;

function renderState(state) {
  const track = state.now_playing;
  const hasPlayer = track !== null;

  player.dataset.status = hasPlayer ? track.status : "none";
  setControlsEnabled(hasPlayer);

  // textContent (never innerHTML): track titles come from the internet, and
  // textContent always shows them as plain text, so a title containing HTML
  // can't inject markup or scripts into the page (an XSS attack).
  if (hasPlayer) {
    statusLabel.textContent = STATUS_LABELS[track.status] ?? track.status;
    titleText.textContent = track.title;
    artistText.textContent = track.artist;
    albumText.textContent = track.album ?? "";
    document.title = `${STATUS_SYMBOLS[track.status] ?? ""} ${track.title} — ${track.artist}`;
    renderVolume(state);
  } else {
    statusLabel.textContent = "No player";
    titleText.textContent = "Nothing playing";
    artistText.textContent = "Open YouTube Music on the studio PC";
    albumText.textContent = "";
    document.title = "Music";
  }
}

// Accepts either GET /api/state or a volume endpoint's response: both carry
// `volume` and `muted`.
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

let messageTimer = null;

function showBanner(text, kind) {
  clearTimeout(messageTimer);
  banner.textContent = text;
  banner.dataset.kind = kind;
  banner.hidden = false;
  if (kind === "message") {
    messageTimer = setTimeout(hideBanner, MESSAGE_DURATION_MS);
  }
}

function hideBanner() {
  banner.hidden = true;
  banner.dataset.kind = "";
}

// One place that decides what the user sees when a request fails.
function handleError(error) {
  if (error instanceof ApiError && error.status === 401) {
    showTokenForm(token ? "The server rejected the saved token." : null);
  } else if (error instanceof ApiError) {
    showBanner(error.message, "message");
  } else {
    setConnected(false);  // network failure: fetch() threw
  }
}

// --- Polling ----------------------------------------------------------------
//
// A chain of setTimeout calls rather than setInterval: the next poll is only
// scheduled after the current one finishes, so a slow server can never cause
// requests to pile up. schedulePoll() always clears the pending timer first,
// so there is never more than one waiting.

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
    // Page Visibility API: stop polling while the tab is in the background.
    // Also stop while locked: the token form restarts polling on submit.
    if (!document.hidden && player.dataset.status !== "locked") schedulePoll(POLL_INTERVAL_MS);
  }, delayMs);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(pollTimer);
    clearTimeout(queueTimer);
  } else if (player.dataset.status !== "locked") {
    schedulePoll(0);  // came back: refresh immediately
    if (player.dataset.view === "queue") refreshQueue();
  }
});

// --- User actions -----------------------------------------------------------

// Transport buttons declare their endpoint in HTML (data-path), so one listener
// serves all of them.
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

for (const button of document.querySelectorAll("[data-volume-path]")) {
  button.addEventListener("click", async () => {
    try {
      renderVolume(await api("POST", button.dataset.volumePath));
    } catch (error) {
      handleError(error);
    }
  });
}

muteButton.addEventListener("click", async () => {
  try {
    renderVolume(await api("PUT", "/api/mute", { muted: !lastMuted }));
  } catch (error) {
    handleError(error);
  }
});

// Volume slider: *coalescing* requests. Dragging fires dozens of "input" events
// per second. Only one request is in flight at a time; while it is, newer
// positions just overwrite `pendingVolume`. When the request finishes, the
// latest position (if any) is sent. Intermediate positions are skipped, which
// is exactly what we want — only where the slider ends up matters.

let volumeRequestInFlight = false;
let pendingVolume = null;

volumeSlider.addEventListener("input", () => {
  lastVolumeInputAt = Date.now();
  volumeValue.textContent = `${volumeSlider.value}%`;
  pendingVolume = Number(volumeSlider.value);
  sendPendingVolume();
});

async function sendPendingVolume() {
  if (volumeRequestInFlight) return;  // the running loop below will pick it up
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

// --- Views: player, search, queue ----------------------------------------------
//
// The three panels live in the same card; data-view on the card decides which
// one CSS shows (the same state-attribute technique as data-status).

const QUEUE_REFRESH_MS = 5000;
const searchForm = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
const queueList = document.getElementById("queue-list");
let queueTimer = null;

function showView(view) {
  player.dataset.view = view;
  for (const tab of document.querySelectorAll(".view-tab")) {
    tab.setAttribute("aria-pressed", String(tab.dataset.viewTarget === view));
  }
  clearTimeout(queueTimer);
  if (view === "search") searchInput.focus();
  if (view === "queue") refreshQueue({ scrollToCurrent: true });
}

for (const tab of document.querySelectorAll(".view-tab")) {
  tab.addEventListener("click", () => showView(tab.dataset.viewTarget));
}

// Library requests fail with 503 when the Chrome extension isn't connected.
// That's shown inside the panel, where the user is looking, not as a banner.
function showLibraryMessage(panel, text) {
  const message = panel.querySelector(".library-message");
  message.textContent = text || "";
  message.hidden = !text;
}

function handleLibraryError(panel, error) {
  if (error instanceof ApiError && error.status === 503) {
    showLibraryMessage(panel, "Search and the queue need the Chrome extension on the studio PC, with YouTube Music open. " + error.message);
  } else {
    handleError(error);
  }
}

// Build a song row's text with textContent only: titles come from the internet (XSS).
function songText(song) {
  const wrapper = document.createElement("span");
  wrapper.className = "song-text";
  const title = document.createElement("span");
  title.className = "song-title";
  title.textContent = song.title;
  const details = document.createElement("span");
  details.className = "song-details";
  details.textContent = [song.artist, song.duration].filter(Boolean).join(" · ");
  wrapper.append(title, details);
  return wrapper;
}

// --- Search ---

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const panel = searchForm.closest(".panel");
  const query = searchInput.value.trim();
  if (!query) return;
  showLibraryMessage(panel, "Searching…");
  searchResults.replaceChildren();
  try {
    const { results } = await api("GET", `/api/library/search?q=${encodeURIComponent(query)}`);
    showLibraryMessage(panel, results.length ? "" : "No songs or videos found.");
    renderSearchResults(results);
  } catch (error) {
    showLibraryMessage(panel, "");
    handleLibraryError(panel, error);
  }
});

function renderSearchResults(results) {
  const rows = results.map((song) => {
    const row = document.createElement("li");
    row.append(songText(song));
    for (const [position, label, extraClass] of [["now", "Play", "primary"], ["next", "Next", ""], ["end", "Queue", ""]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `list-action ${extraClass}`.trim();
      button.textContent = label;
      button.dataset.videoId = song.video_id;
      button.dataset.position = position;
      button.setAttribute("aria-label", `${label}: ${song.title}`);
      row.append(button);
    }
    return row;
  });
  searchResults.replaceChildren(...rows);
}

// *Event delegation*: one listener on the list handles every button in it,
// including rows created later, instead of one listener per button.
searchResults.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-video-id]");
  if (!button) return;
  const panel = searchResults.closest(".panel");
  button.disabled = true;
  try {
    await api("POST", "/api/library/play", { video_id: button.dataset.videoId, position: button.dataset.position });
    const done = { now: "Playing", next: "Will play next", end: "Added to the queue" }[button.dataset.position];
    showBanner(done, "message");
    schedulePoll(0);
  } catch (error) {
    handleLibraryError(panel, error);
  } finally {
    button.disabled = false;
  }
});

// --- Queue ---

async function refreshQueue({ scrollToCurrent = false } = {}) {
  clearTimeout(queueTimer);
  const panel = queueList.closest(".panel");
  try {
    const queue = await api("GET", "/api/library/queue");
    showLibraryMessage(panel, queue.items.length ? "" : "The queue is empty.");
    renderQueue(queue);
    if (scrollToCurrent) {
      queueList.querySelector('[aria-current="true"]')?.scrollIntoView({ block: "center" });
    }
  } catch (error) {
    handleLibraryError(panel, error);
  }
  // Keep it fresh while visible (songs advance by themselves).
  if (player.dataset.view === "queue" && !document.hidden) {
    queueTimer = setTimeout(refreshQueue, QUEUE_REFRESH_MS);
  }
}

function renderQueue(queue) {
  const rows = [];
  let autoplayHeadingAdded = false;
  for (const item of queue.items) {
    if (item.is_autoplay && !autoplayHeadingAdded) {
      const heading = document.createElement("li");
      heading.className = "list-heading";
      heading.textContent = "Autoplay";
      rows.push(heading);
      autoplayHeadingAdded = true;
    }
    const row = document.createElement("li");
    if (item.is_current) row.setAttribute("aria-current", "true");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "queue-item";
    button.dataset.index = String(item.index);
    const number = document.createElement("span");
    number.className = "queue-number";
    number.textContent = item.is_current ? "▶" : String(item.index + 1);
    button.append(number, songText(item));
    row.append(button);
    rows.push(row);
  }
  queueList.replaceChildren(...rows);
}

queueList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-index]");
  if (!button) return;
  try {
    await api("POST", `/api/library/queue/${button.dataset.index}/play`);
    schedulePoll(0);
    setTimeout(refreshQueue, 800); // give YouTube Music a moment to update
  } catch (error) {
    handleLibraryError(queueList.closest(".panel"), error);
  }
});

// --- Start ------------------------------------------------------------------

setControlsEnabled(false);
loadToken();
if (token) {
  schedulePoll(0);
} else {
  showTokenForm();
}
