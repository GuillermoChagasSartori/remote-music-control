// Remote Music Control — Chrome extension background service worker.
//
// Keeps one WebSocket open to the Remote Music Control server on this PC and
// answers its requests (search, queue, jump, play) by running functions inside
// the YouTube Music tab. The functions that touch YouTube Music's internals
// are all in youtube-music.js. The message protocol is described in
// src/remote_music_control/extension_bridge.py. See ADR 0013.

import { PAGE_FUNCTIONS } from "./youtube-music.js";

const SERVER_URL = "ws://127.0.0.1:8000/extension/ws";
const VERSION = chrome.runtime.getManifest().version;

// Chrome stops an idle Manifest V3 service worker after ~30 s. Traffic on an
// open WebSocket keeps it alive (Chrome 116+), so a small message is sent
// every 20 s. Measured in the Phase 8 spike: 23 minutes without a drop.
const KEEPALIVE_INTERVAL_MS = 20000;

// Reconnect with *exponential backoff*: wait 1 s, then 2, 4, 8… up to 30 s,
// so a stopped server isn't hammered with attempts, while a server that
// restarts quickly is reached again within a second or two.
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let socket = null;
let reconnectDelayMs = RECONNECT_MIN_MS;
let reconnectTimer = null;

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
  }
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  socket = new WebSocket(SERVER_URL);

  socket.onopen = () => {
    reconnectDelayMs = RECONNECT_MIN_MS;
    send({ type: "hello", version: VERSION });
  };

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return; // not JSON: ignore
    }
    if (message.type === "request") {
      handleRequest(message);
    }
  };

  socket.onclose = () => {
    socket = null;
    scheduleReconnect();
  };

  // Errors are always followed by "close", which schedules the reconnect.
  socket.onerror = () => {};
}

function scheduleReconnect() {
  if (reconnectTimer !== null) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, reconnectDelayMs);
  reconnectDelayMs = Math.min(reconnectDelayMs * 2, RECONNECT_MAX_MS);
}

setInterval(() => send({ type: "keepalive" }), KEEPALIVE_INTERVAL_MS);

// If Chrome stopped the worker anyway, these wake it up and reconnect.
chrome.alarms.create("keep-connected", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();

// --- Answering requests ------------------------------------------------------

class RequestError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

async function handleRequest({ id, op, args }) {
  const operation = OPERATIONS[op];
  try {
    if (!operation) throw new RequestError("unknown_op", `unknown operation '${op}'`);
    const result = await operation(args || {});
    send({ type: "response", id, ok: true, result });
  } catch (error) {
    send({
      type: "response",
      id,
      ok: false,
      error: { kind: error.kind || "failed", message: error.message || String(error) },
    });
  }
}

async function findMusicTab() {
  const tabs = await chrome.tabs.query({ url: "https://music.youtube.com/*" });
  if (tabs.length === 0) {
    throw new RequestError("no_tab", "no YouTube Music tab is open in Chrome");
  }
  // With several tabs open, the one making sound is the one being listened to.
  return tabs.find((tab) => tab.audible) || tabs[0];
}

// Run one function from youtube-music.js inside the page. world "MAIN" runs it
// in the page's own JavaScript context, where YouTube Music's objects live.
// Page functions never throw: they return { ok, value } or { ok, kind, message }.
async function runInMusicTab(func, args) {
  const tab = await findMusicTab();
  const [injection] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, world: "MAIN", func, args });
  const outcome = injection && injection.result;
  if (!outcome || typeof outcome !== "object") {
    throw new RequestError("failed", "no result from the YouTube Music tab");
  }
  if (!outcome.ok) {
    throw new RequestError(outcome.kind || "failed", outcome.message || "failed in the YouTube Music tab");
  }
  return outcome.value;
}

const OPERATIONS = {
  search: ({ query }) => runInMusicTab(PAGE_FUNCTIONS.search, [String(query)]),
  get_queue: () => runInMusicTab(PAGE_FUNCTIONS.getQueue, []),
  jump: ({ index }) => runInMusicTab(PAGE_FUNCTIONS.jumpTo, [Number(index)]),
  play: ({ video_id: videoId, position }) =>
    position === "now"
      ? runInMusicTab(PAGE_FUNCTIONS.playNow, [String(videoId)])
      : runInMusicTab(PAGE_FUNCTIONS.addToQueue, [String(videoId), String(position)]),
};
