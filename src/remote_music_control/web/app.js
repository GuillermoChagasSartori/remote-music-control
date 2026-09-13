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
  } else if (player.dataset.status !== "locked") {
    schedulePoll(0);  // came back: refresh immediately
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

// --- Start ------------------------------------------------------------------

setControlsEnabled(false);
loadToken();
if (token) {
  schedulePoll(0);
} else {
  showTokenForm();
}
