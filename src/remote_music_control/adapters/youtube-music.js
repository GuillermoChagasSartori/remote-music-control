// Remote Music Control — everything that depends on YouTube Music's internals.
//
// YouTube Music has no public API for search or the queue. These functions
// use the web app's own, undocumented machinery, found and verified in the
// Phase 8 spike (ADR 0013) and again inside the app's own window (ADR 0014).
// When Google changes YouTube Music and a feature breaks, this is the one file
// to fix.
//
// The functions run INSIDE the YouTube Music page shown in the app's window:
// page_library.py wraps this whole file in a script, adds a call to one
// function and has the window evaluate it. Each function is self-contained
// (small helpers are repeated rather than shared), so a fix to one can't
// break another.
//
// Each returns { ok: true, value } or { ok: false, kind, message } and never
// throws. kind "not_found" and "page_changed" are understood by the server.

async function search(query) {
  try {
    if (typeof ytcfg === "undefined" || !ytcfg.get("INNERTUBE_API_KEY")) {
      return { ok: false, kind: "page_changed", message: "YouTube Music isn't ready in this tab (ytcfg missing)" };
    }
    // The same search request the page itself makes, with the user's session.
    const response = await fetch(
      `/youtubei/v1/search?key=${encodeURIComponent(ytcfg.get("INNERTUBE_API_KEY"))}&prettyPrint=false`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context: ytcfg.get("INNERTUBE_CONTEXT"), query }),
      },
    );
    if (!response.ok) {
      return { ok: false, kind: "page_changed", message: `YouTube Music search failed (HTTP ${response.status})` };
    }
    const data = await response.json();

    const text = (runs) => (runs || []).map((run) => run.text).join("");
    const isArtistOrChannel = (run) => {
      const pageType = run.navigationEndpoint?.browseEndpoint?.browseEndpointContextSupportedConfigs
        ?.browseEndpointContextMusicConfig?.pageType || "";
      return /ARTIST|USER_CHANNEL/.test(pageType);
    };
    const artistOf = (runs) => runs.filter(isArtistOrChannel).map((run) => run.text).join(", ") || null;
    const durationOf = (runs) => runs.map((run) => run.text.trim()).find((t) => /^\d+(:\d{2})+$/.test(t)) || null;
    const songs = [];
    const seen = new Set();
    const addSong = (videoId, title, artist, duration) => {
      if (!videoId || seen.has(videoId) || songs.length >= 20) return;
      seen.add(videoId);
      songs.push({ video_id: videoId, title: title || "(untitled)", artist, duration });
    };
    // `cardArtist`: inside an artist's "top result" card, songs omit the artist
    // from their own line, because the card itself is the artist.
    const visit = (node, cardArtist) => {
      if (!node || typeof node !== "object" || songs.length >= 20) return;

      const card = node.musicCardShelfRenderer;
      if (card) {
        const titleRuns = card.title?.runs || [];
        const subtitleRuns = card.subtitle?.runs || [];
        // A "top result" card can itself be a song: its title plays it directly.
        addSong(titleRuns[0]?.navigationEndpoint?.watchEndpoint?.videoId, text(titleRuns), artistOf(subtitleRuns), durationOf(subtitleRuns));
        const artist = titleRuns.some(isArtistOrChannel) ? text(titleRuns) : null;
        for (const child of card.contents || []) visit(child, artist);
        return;
      }

      const item = node.musicResponsiveListItemRenderer;
      // Only results with a playable video id: songs and videos, not artists or albums.
      if (item?.playlistItemData?.videoId) {
        const columns = (item.flexColumns || []).map((column) => column.musicResponsiveListItemFlexColumnRenderer?.text?.runs || []);
        const detailRuns = columns[1] || [];
        const fixedRuns = (item.fixedColumns || []).flatMap((column) => column.musicResponsiveListItemFixedColumnRenderer?.text?.runs || []);
        addSong(item.playlistItemData.videoId, text(columns[0]), artistOf(detailRuns) || cardArtist, durationOf([...detailRuns, ...fixedRuns]));
      }
      for (const value of Object.values(node)) visit(value, cardArtist);
    };
    visit(data, null);
    return { ok: true, value: songs };
  } catch (error) {
    return { ok: false, kind: "page_changed", message: `search failed in YouTube Music: ${error}` };
  }
}

function getQueue() {
  try {
    if (!document.querySelector("ytmusic-player-queue")) {
      return { ok: false, kind: "page_changed", message: "YouTube Music's queue isn't on this page" };
    }
    const text = (value) => (value?.runs || []).map((run) => run.text).join("") || null;
    // The visible list is the user's queue followed by autoplay suggestions.
    // The queue store's `items` holds only the queue part, so its length tells
    // where autoplay begins ("add to queue" inserts before that point).
    let queueLength = Infinity;
    try {
      queueLength = document.querySelector("ytmusic-app").queue.store.store.getState().queue.items.length;
    } catch {
      // Store not reachable: treat everything as queue rather than failing.
    }
    // Only rendered items that carry their data, and not the hidden
    // "counterpart" of a song: YouTube Music renders each queue position with
    // both its song and its music-video version (#primary-renderer and
    // #counterpart-renderer) and shows one. The hidden one even keeps a stale
    // "selected" attribute. jumpTo() uses the same filter, so an index means
    // the same item in both.
    const items = [...document.querySelectorAll("ytmusic-player-queue ytmusic-player-queue-item")]
      .filter((element) => element.data?.videoId && !element.closest("#counterpart-renderer"))
      .map((element, index) => ({
        video_id: element.data.videoId,
        title: text(element.data.title) || "(untitled)",
        artist: text(element.data.shortBylineText),
        duration: text(element.data.lengthText),
        is_current: element.hasAttribute("selected"),
        is_autoplay: index >= queueLength,
      }));
    return { ok: true, value: { items } };
  } catch (error) {
    return { ok: false, kind: "page_changed", message: `reading the queue failed: ${error}` };
  }
}

function jumpTo(index) {
  try {
    // The same filter as getQueue(): skip the hidden counterpart versions.
    const elements = [...document.querySelectorAll("ytmusic-player-queue ytmusic-player-queue-item")]
      .filter((element) => element.data?.videoId && !element.closest("#counterpart-renderer"));
    const element = elements[index];
    if (!element) {
      return { ok: false, kind: "not_found", message: `there is no queue item ${index}` };
    }
    // Click the item's play button, as a user would.
    (element.querySelector("ytmusic-play-button-renderer") || element).click();
    return { ok: true, value: null };
  } catch (error) {
    return { ok: false, kind: "page_changed", message: `jumping in the queue failed: ${error}` };
  }
}

function playNow(videoId) {
  try {
    const app = document.querySelector("ytmusic-app");
    if (!app) return { ok: false, kind: "page_changed", message: "YouTube Music app element not found" };
    // The page's own navigation event: plays the song without reloading the
    // tab. YouTube Music replaces the queue with a radio for it.
    app.dispatchEvent(
      new CustomEvent("yt-navigate", { bubbles: true, composed: true, detail: { endpoint: { watchEndpoint: { videoId } } } }),
    );
    return { ok: true, value: null };
  } catch (error) {
    return { ok: false, kind: "page_changed", message: `playing the song failed: ${error}` };
  }
}

async function addToQueue(videoId, position) {
  try {
    const app = document.querySelector("ytmusic-app");
    const queueElement = document.querySelector("ytmusic-player-queue");
    const store = app?.queue?.store?.store;
    if (!app?.networkManager?.fetch || typeof queueElement?.dispatch !== "function" || !store?.getState) {
      return { ok: false, kind: "page_changed", message: "YouTube Music's queue internals weren't found" };
    }
    const insertPosition = position === "next" ? "INSERT_AFTER_CURRENT_VIDEO" : "INSERT_AT_END";
    const state = store.getState().queue;

    // Step 1: ask YouTube Music's server for the song's queue entry.
    const response = await app.networkManager.fetch("/music/get_queue", {
      queueContextParams: state.queueContextParams,
      queueInsertPosition: insertPosition,
      videoIds: [videoId],
    });
    const items = (response?.queueDatas || []).map((data) => data?.content).filter(Boolean);
    if (items.length === 0) {
      return { ok: false, kind: "page_changed", message: "YouTube Music returned no queue entry for this song" };
    }

    // Step 2: insert it into the page's queue store (a Redux-style store).
    const current = store.getState().queue;
    const index = insertPosition === "INSERT_AFTER_CURRENT_VIDEO" ? current.selectedItemIndex + 1 : current.items.length;
    queueElement.dispatch({
      type: "ADD_ITEMS",
      payload: { nextQueueItemId: current.nextQueueItemId, index, items, shuffleEnabled: false, shouldAssignIds: true },
    });
    return { ok: true, value: null };
  } catch (error) {
    return { ok: false, kind: "page_changed", message: `adding to the queue failed: ${error}` };
  }
}

// The names page_library.py calls. A plain constant, not an `export`: the file
// is evaluated as an ordinary script inside a function, not loaded as a module.
const PAGE_FUNCTIONS = { search, getQueue, jumpTo, playNow, addToQueue };
