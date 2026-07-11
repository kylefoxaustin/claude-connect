// app.js — WebSocket client + top-level state. Delegates rendering to tiles.js / lines.js.

import {
  renderGrid, flashTilePreview, fadeOutSession, resetLayout,
  getGroups, renameGroup, recolorGroup, deleteGroup, setGroupCollapsed, GROUP_COLORS,
} from "/static/tiles.js";
import { redrawLines, animateLineFor } from "/static/lines.js";

// --- Auth token (for remote/phone access over Tailscale) --------------------
// Stored per-browser. When the server has no token configured (the localhost
// default) this stays empty and is simply never sent — nothing changes locally.
const AUTH_KEY = "conductor.authToken.v1";
const _origFetch = window.fetch.bind(window);
// An in-memory token wins over localStorage. This is what makes the native
// desktop app work even though pywebview runs in private mode (no persistent
// storage): app.py seeds the token into this variable, so we never depend on
// localStorage surviving — and never need to reload the page to pick it up.
// The native app passes the token in the URL hash (`#t=…`). That's deliberate:
// it needs NO event timing (app.js is a module, so it runs *after* pywebview's
// page-load event — a seed fired on that event silently no-ops), and the hash
// survives a reload, which localStorage does not under pywebview's private mode.
// A hash is never sent to the server, and the native window has no address bar.
function tokenFromHash() {
  try {
    const m = /(?:^|[#&])t=([^&]*)/.exec(location.hash || "");
    return m ? decodeURIComponent(m[1]) : "";
  } catch { return ""; }
}
function getToken() {
  if (window.__conductorInjectedToken) return window.__conductorInjectedToken;
  const h = tokenFromHash();
  if (h) return h;
  try { return localStorage.getItem(AUTH_KEY) || ""; } catch { return ""; }
}
function setToken(t) {
  window.__conductorInjectedToken = t || undefined;
  try { t ? localStorage.setItem(AUTH_KEY, t) : localStorage.removeItem(AUTH_KEY); } catch {}
}
// Adopt a hash-provided token immediately (before anything fetches).
const _hashToken = tokenFromHash();
if (_hashToken) setToken(_hashToken);

// Transparently attach the token to same-origin /api/ requests, so every
// existing fetch("/api/…") call site stays untouched. A 401 pops the unlock
// overlay. Non-/api requests (static assets) pass straight through.
window.fetch = (input, init) => {
  init = init || {};
  let url = "";
  try { url = typeof input === "string" ? input : (input && input.url) || ""; } catch {}
  if (url.startsWith("/api/")) {
    const tok = getToken();
    if (tok) {
      const headers = new Headers(init.headers || {});
      headers.set("X-Conductor-Token", tok);
      init = { ...init, headers };
    }
    return _origFetch(input, init).then((resp) => {
      if (resp.status === 401) showAuthOverlay();
      return resp;
    });
  }
  return _origFetch(input, init);
};

const state = {
  sessions: [],     // SessionRecord[]
  parked: [],       // ParkedSession[] — offline, relaunchable (dormant dock)
  resources: { resources: [] },  // shared-resource tiles (GPU, boards, …)
  push: { requests: [] },        // gated git-push approvals awaiting Kyle
  fadeoutSeconds: 30,
  wmctrlAvailable: false,

  busTotal: 0,
  busRecent: [],    // BusEvent[] (most recent last)
  busTopology: { subscribers: {} },
  busUnseen: 0,
  busPendingByTag: {},
  busActiveTags: [],  // tags auto-notified of traffic (solid line); others are passive
  busAdapter: "markdown",
};

window.conductorState = state; // for ad-hoc debugging from devtools

// --- Display preferences (client-side, localStorage) ------------------------
const PREFS_KEY = "conductor.prefs.v1";
const DEFAULT_PREFS = {
  theme: "dark", lines: true, animation: true, showEnded: true,
  // 3D view (fork ②): whether it's active, and which layout is selected.
  // Default view is 2D; when 3D is opened, it defaults to the carousel layout.
  view3d: false, layout3d: "carousel",
  // Draw the bus lines behind the tiles instead of on top (declutter).
  linesBehind: false,
  // Compact density: collapse every tile to header-only (dot + name + tag),
  // hiding the preview/tokens/path so the whole fleet fits at a glance.
  compact: false,
  // Tidy layout: pack the tiles into a flow grid instead of their free-form
  // positions. Purely a VIEW — the saved positions are never touched, so turning
  // it off restores your own layout exactly. Composes with `compact`.
  packed: false,
  // How a 📬 bubble click behaves: "confirm-busy" | "always" | "block-busy" | "always-confirm".
  busClickGuard: "confirm-busy",
};

function loadPrefs() {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") }; }
  catch { return { ...DEFAULT_PREFS }; }
}
function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch {}
}
const prefs = loadPrefs();
window.conductorPrefs = prefs; // read by tiles.js (showEnded) and lines.js (animation)
window.saveConductorPrefs = savePrefs; // scene3d.js persists its layout choice

// --- 3D view (fork ②) -------------------------------------------------------
// scene3d.js is imported lazily so a CDN miss on Three.js can never break 2D.
let view3dMod = null;
let view3dLoading = false;
const view3dBtn = document.getElementById("view3d-btn");

function setView3dBtn(on, loading) {
  view3dBtn.classList.toggle("on", !!on);
  view3dBtn.textContent = loading ? "🧊 …" : on ? "🗔 2D" : "🧊 3D";
  view3dBtn.title = on ? "Back to the 2D board" : "Toggle the experimental 3D view";
}

async function enter3D() {
  if (view3dMod) { view3dMod.activate(state, prefs.layout3d); setView3dBtn(true); return; }
  if (view3dLoading) return;
  view3dLoading = true;
  setView3dBtn(true, true);
  try {
    view3dMod = await import("/static/scene3d.js");
    view3dMod.activate(state, prefs.layout3d);
    setView3dBtn(true);
  } catch (e) {
    console.error("3D view failed to load", e);
    prefs.view3d = false; savePrefs();
    setView3dBtn(false);
    alert("Couldn't load the 3D view (Three.js may be unreachable). Staying in 2D.");
  } finally {
    view3dLoading = false;
  }
}
function exit3D() { if (view3dMod) view3dMod.deactivate(); setView3dBtn(false); }
function setView3d(on) { prefs.view3d = on; savePrefs(); if (on) enter3D(); else exit3D(); }
function refresh3D() { if (prefs.view3d && view3dMod) view3dMod.update(state); }

view3dBtn.addEventListener("click", () => setView3d(!prefs.view3d));

// 🕸 History time-lapse. Lazily imported like scene3d.js — a throw or CDN-less
// failure in heatmap.js can never affect the board. It's a transient overlay
// (no persisted pref): open it, watch, close it.
let heatmapMod = null;
const heatmapBtn = document.getElementById("heatmap-btn");
heatmapBtn.addEventListener("click", async () => {
  try {
    if (!heatmapMod) heatmapMod = await import("/static/heatmap.js");
    heatmapMod.activate();
  } catch (err) {
    console.error("heatmap failed to load", err);
  }
});

function applyTheme() {
  document.documentElement.dataset.theme = prefs.theme;
}
function applyLinesVisibility() {
  const overlay = document.getElementById("lines-overlay");
  if (overlay) overlay.style.display = prefs.lines ? "" : "none";
}
function applyLinesBehind() {
  document.body.classList.toggle("lines-behind", !!prefs.linesBehind);
}
function applyCompact() {
  document.body.classList.toggle("compact", !!prefs.compact);
  const btn = document.getElementById("compact-btn");
  if (btn) {
    btn.classList.toggle("on", !!prefs.compact);
    btn.textContent = prefs.compact ? "⊞ Expand" : "⊟ Compact";
    btn.title = prefs.compact
      ? "Restore tiles to their normal size"
      : "Collapse all tiles to a compact size (keeps them all visible)";
  }
}
// Tidy: pack tiles into a flow grid. This is a pure CSS view-mode — tiles.js's
// saved positions are never written, so toggling it off snaps every tile back to
// exactly where you put it. That's the "restore" and it's lossless by construction.
function applyPacked() {
  document.body.classList.toggle("packed", !!prefs.packed);
  const btn = document.getElementById("pack-btn");
  if (btn) {
    btn.classList.toggle("on", !!prefs.packed);
    btn.textContent = prefs.packed ? "↩ Restore" : "⊞ Tidy";
    btn.title = prefs.packed
      ? "Restore your own tile layout (positions were never changed)"
      : "Pull all tiles together into a tidy grid — your layout is kept and restored when you turn this off";
  }
}
function applyPrefs() {
  applyTheme();
  applyLinesVisibility();
  applyLinesBehind();
  applyCompact();
  applyPacked();
  renderGrid(state);
  requestAnimationFrame(() => redrawLines(state));
}
applyTheme();            // apply ASAP to avoid a flash before first render
applyLinesVisibility();
applyCompact();
applyPacked();

const connStateEl = document.getElementById("conn-state");
const sessionCountEl = document.getElementById("session-count");

let ws = null;
let reconnectDelay = 500;

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  // The token rides in the query string — a browser can't set headers on a WS
  // handshake. Empty token => omitted (local default).
  const tok = getToken();
  const q = tok ? `?token=${encodeURIComponent(tok)}` : "";
  ws = new WebSocket(`${proto}://${location.host}/ws${q}`);
  ws.addEventListener("open", () => {
    setConnState(true);
    reconnectDelay = 500;
  });
  ws.addEventListener("close", (ev) => {
    setConnState(false);
    // 1008 = policy violation: the server rejected our token. Don't hammer a
    // reconnect loop — ask for the token instead.
    if (ev && ev.code === 1008) { showAuthOverlay(); return; }
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 8000);
  });
  ws.addEventListener("error", () => ws && ws.close());
  ws.addEventListener("message", (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleMessage(msg);
  });
}

function setConnState(up) {
  connStateEl.textContent = up ? "live" : "disconnected";
  connStateEl.classList.toggle("conn-up", up);
  connStateEl.classList.toggle("conn-down", !up);
}

function handleMessage({ kind, payload }) {
  switch (kind) {
    case "sessions":
      state.sessions = payload.sessions || [];
      state.parked = payload.parked || [];
      state.fadeoutSeconds = payload.fadeout_seconds ?? 30;
      state.wmctrlAvailable = !!payload.wmctrl_available;
      sessionCountEl.textContent = `${state.sessions.length} session${state.sessions.length === 1 ? "" : "s"}`;
      renderGrid(state);
      requestAnimationFrame(() => redrawLines(state));
      refresh3D();
      break;
    case "session": {
      const idx = state.sessions.findIndex((s) => s.session_id === payload.session_id);
      if (idx >= 0) state.sessions[idx] = payload;
      else state.sessions.push(payload);
      renderGrid(state);
      flashTilePreview(payload.session_id);
      requestAnimationFrame(() => redrawLines(state));
      refresh3D();
      break;
    }
    case "bus": {
      state.busTotal = payload.total ?? 0;
      state.busRecent = payload.recent || [];
      state.busTopology = payload.topology || { subscribers: {} };
      state.busPendingByTag = payload.pending_by_tag || {};
      state.busActiveTags = payload.active_tags || [];
      state.busAdapter = payload.adapter || state.busAdapter;
      renderGrid(state);
      requestAnimationFrame(() => redrawLines(state));
      refresh3D();
      break;
    }
    case "resources": {
      state.resources = payload || { resources: [] };
      renderGrid(state);
      requestAnimationFrame(() => redrawLines(state));
      break;
    }
    case "push": {
      state.push = payload || { requests: [] };
      renderPushInbox(state);
      break;
    }
    case "bus_event": {
      const ev = payload.event;
      state.busTotal = payload.total ?? state.busTotal + 1;
      state.busRecent.push(ev);
      while (state.busRecent.length > 20) state.busRecent.shift();
      if (payload.topology) state.busTopology = payload.topology;
      state.busUnseen += 1;
      renderGrid(state);
      refresh3D();
      requestAnimationFrame(() => {
        redrawLines(state);
        // Directed messages from the dashboard carry a leading "@to [tag]…" line;
        // animate toward the addressees. Otherwise animate the sender's own line
        // back to the bus tile ("this session sent a message").
        const to = parseToTags(ev.payload_summary);
        if (to.length) to.forEach(animateLineForTag);
        else animateLineForTag(ev.source_session);
      });
      break;
    }
  }
}

// Extract recipient tags from a directed message's leading "@to [a] [b]" line.
function parseToTags(summary) {
  const line = String(summary || "").split("\n")[0];
  if (!line.startsWith("@to ")) return [];
  return line.slice(4).match(/\[[^\]]+\]/g) || [];
}

// Resolve a tag (e.g. "[backend]") to the session_id it currently maps to,
// so lines.js (which keys lines by session_id) can find the right path.
function animateLineForTag(tag) {
  if (!tag) return;
  const match = state.sessions.find((s) => s.tag === tag);
  if (match) animateLineFor(match.session_id);
  if (prefs.view3d && view3dMod) view3dMod.animateForTag(tag);
}

document.getElementById("reset-layout-btn")?.addEventListener("click", () => {
  resetLayout();
});

document.getElementById("compact-btn")?.addEventListener("click", () => {
  prefs.compact = !prefs.compact;
  savePrefs();
  applyCompact();
  // Tiles changed size -> re-anchor the bus wires.
  requestAnimationFrame(() => redrawLines(state));
});

document.getElementById("pack-btn")?.addEventListener("click", () => {
  prefs.packed = !prefs.packed;
  savePrefs();
  applyPacked();
  // Tiles moved -> re-anchor the bus wires to their new spots.
  requestAnimationFrame(() => redrawLines(state));
});

document.getElementById("refresh-btn")?.addEventListener("click", async () => {
  try {
    const r = await fetch("/api/sessions");
    if (r.ok) {
      const payload = await r.json();
      handleMessage({ kind: "sessions", payload });
    }
  } catch (e) {
    console.warn("refresh failed", e);
  }
});

window.addEventListener("resize", () => requestAnimationFrame(() => redrawLines(state)));

// Settings modal wiring.
const settingsModal = document.getElementById("settings-modal");
const setTheme = document.getElementById("set-theme");
const setLines = document.getElementById("set-lines");
const setLinesBehind = document.getElementById("set-lines-behind");
const setAnimation = document.getElementById("set-animation");
const setShowEnded = document.getElementById("set-showended");
const setBusGuard = document.getElementById("set-bus-guard");
const setInterval_ = document.getElementById("set-interval");
const setFadeout = document.getElementById("set-fadeout");
const settingsStatus = document.getElementById("settings-status");

function flashSettingsStatus(text) {
  settingsStatus.textContent = text;
  settingsStatus.style.opacity = "1";
  setTimeout(() => { settingsStatus.style.opacity = "0"; }, 1500);
}

// Show the running version (matches the release tag) in the settings header —
// fetched once at load from /api/health.
fetch("/api/health").then((r) => (r.ok ? r.json() : null)).then((h) => {
  const el = document.getElementById("settings-version");
  if (el && h && h.version) el.textContent = `v${h.version}`;
}).catch(() => {});

document.getElementById("settings-btn")?.addEventListener("click", async () => {
  // Appearance from local prefs.
  setTheme.value = prefs.theme;
  setLines.checked = prefs.lines;
  setLinesBehind.checked = prefs.linesBehind;
  setAnimation.checked = prefs.animation;
  setShowEnded.checked = prefs.showEnded;
  setBusGuard.value = prefs.busClickGuard;
  // Behavior from the server (settings.toml).
  try {
    const r = await fetch("/api/settings");
    if (r.ok) {
      const s = await r.json();
      setInterval_.value = s.interval_seconds;
      setFadeout.value = s.end_fadeout_seconds;
    }
  } catch (e) { console.warn("settings fetch failed", e); }
  settingsStatus.textContent = "";
  settingsModal.classList.remove("hidden");
});
document.getElementById("settings-modal-close")
  ?.addEventListener("click", () => settingsModal.classList.add("hidden"));
settingsModal.addEventListener("click", (e) => {
  if (e.target === settingsModal) settingsModal.classList.add("hidden");
});

// Appearance prefs: apply + persist locally on change.
setTheme.addEventListener("change", () => { prefs.theme = setTheme.value; savePrefs(); applyTheme(); });
setLines.addEventListener("change", () => { prefs.lines = setLines.checked; savePrefs(); applyLinesVisibility(); });
setLinesBehind.addEventListener("change", () => {
  prefs.linesBehind = setLinesBehind.checked; savePrefs(); applyLinesBehind();
  requestAnimationFrame(() => redrawLines(state));  // refresh the front anchor layer
});
setAnimation.addEventListener("change", () => { prefs.animation = setAnimation.checked; savePrefs(); });
setShowEnded.addEventListener("change", () => {
  prefs.showEnded = setShowEnded.checked; savePrefs();
  renderGrid(state); requestAnimationFrame(() => redrawLines(state));
});
setBusGuard.addEventListener("change", () => {
  prefs.busClickGuard = setBusGuard.value; savePrefs();
  // Re-render so block-busy badges enable/disable to match the new policy.
  renderGrid(state); requestAnimationFrame(() => redrawLines(state));
});

// Behavior settings: persist to settings.toml via the API.
async function postSettings(body) {
  try {
    const r = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (r.ok) {
      const s = await r.json();
      setInterval_.value = s.interval_seconds;
      setFadeout.value = s.end_fadeout_seconds;
      flashSettingsStatus("Saved to settings.toml");
    } else {
      flashSettingsStatus("Save failed");
    }
  } catch (e) {
    console.warn("settings save failed", e);
    flashSettingsStatus("Save failed");
  }
}
setInterval_.addEventListener("change", () => postSettings({ interval_seconds: parseFloat(setInterval_.value) }));
setFadeout.addEventListener("change", () => postSettings({ end_fadeout_seconds: parseFloat(setFadeout.value) }));

// Bus modal wiring.
const modal = document.getElementById("bus-modal");
const modalFeed = document.getElementById("bus-modal-feed");
document.getElementById("bus-modal-close")?.addEventListener("click", () => modal.classList.add("hidden"));
modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.add("hidden"); });

window.openBusModal = function openBusModal() {
  state.busUnseen = 0;
  renderGrid(state);
  modalFeed.innerHTML = "";
  for (const ev of [...state.busRecent].reverse()) {
    const li = document.createElement("li");
    const t = new Date(ev.timestamp * 1000).toLocaleTimeString();
    li.innerHTML = `<span style="opacity:0.6;">${t}</span> <span class="src">${escapeHtml(ev.source_session)}</span> → <span class="dst">${escapeHtml(ev.destination_session)}</span><span class="topic">${escapeHtml(ev.topic)}</span> ${escapeHtml(ev.payload_summary)}`;
    modalFeed.appendChild(li);
  }
  modal.classList.add = modal.classList.add; // satisfy linter no-op
  modal.classList.remove("hidden");
};

// Compose modal wiring — send a bus message from the dashboard (the human).
const composeModal = document.getElementById("compose-modal");
const composeText = document.getElementById("compose-text");
const composeAll = document.getElementById("compose-all");
const composeList = document.getElementById("compose-recipient-list");
const composePing = document.getElementById("compose-ping");
const composeSend = document.getElementById("compose-send");
const composeStatus = document.getElementById("compose-status");

function closeCompose() { composeModal.classList.add("hidden"); }
document.getElementById("compose-modal-close")?.addEventListener("click", closeCompose);
composeModal.addEventListener("click", (e) => { if (e.target === composeModal) closeCompose(); });

function syncComposeEnabled() {
  const all = composeAll.checked;
  for (const cb of composeList.querySelectorAll("input[type=checkbox]")) cb.disabled = all;
  // Ping only makes sense for specific recipients (broadcast-ping = focus-steal all).
  composePing.disabled = all;
  if (all) composePing.checked = false;
}

function openCompose() {
  composeStatus.textContent = "";
  // Rebuild the recipient list from current (non-ended) sessions.
  composeList.innerHTML = "";
  for (const s of state.sessions) {
    if (s.status === "ended") continue;
    const li = document.createElement("li");
    const id = `cr-${s.session_id}`;
    li.innerHTML = `<label><input type="checkbox" value="${escapeHtml(s.tag)}" id="${id}" /> `
      + `<span class="cr-tag">${escapeHtml(s.tag)}</span> <span class="cr-title">${escapeHtml(s.title)}</span></label>`;
    composeList.appendChild(li);
  }
  composeList.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => { if (cb.checked) composeAll.checked = false; syncComposeEnabled(); });
  });
  syncComposeEnabled();
  composeModal.classList.remove("hidden");
  composeText.focus();
}
document.getElementById("compose-btn")?.addEventListener("click", openCompose);
composeAll.addEventListener("change", syncComposeEnabled);

async function sendCompose() {
  const text = composeText.value.trim();
  if (!text) { composeStatus.textContent = "Enter a message."; return; }
  const recipients = composeAll.checked
    ? []
    : [...composeList.querySelectorAll("input[type=checkbox]:checked")].map((cb) => cb.value);
  if (!composeAll.checked && recipients.length === 0) {
    composeStatus.textContent = "Pick recipients, or choose All.";
    return;
  }
  composeSend.disabled = true;
  composeStatus.textContent = "Sending…";
  try {
    const r = await fetch("/api/bus/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, recipients, ping: composePing.checked }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      composeStatus.textContent = `Failed: ${err.detail || r.status}`;
      return;
    }
    const body = await r.json();
    const to = body.recipients === "all" ? "all sessions" : recipients.join(", ");
    const ping = (body.pinged && body.pinged.length) ? ` · pinged ${body.pinged.length}` : "";
    composeStatus.textContent = `Sent to ${to}${ping}.`;
    composeText.value = "";
    setTimeout(closeCompose, 900);
  } catch (e) {
    composeStatus.textContent = "Send error.";
    console.warn("compose send error", e);
  } finally {
    composeSend.disabled = false;
  }
}
composeSend.addEventListener("click", sendCompose);
composeText.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") sendCompose();
});

// Toggle a tag's bus membership active <-> passive (writes the active-tags file).
window.toggleBusActive = async function toggleBusActive(tag, makeActive) {
  try {
    const r = await fetch("/api/bus/active", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag, active: makeActive }),
    });
    if (!r.ok) { console.warn("active toggle failed", r.status); return; }
    const body = await r.json();
    state.busActiveTags = body.active_tags || state.busActiveTags;
    renderGrid(state);
    requestAnimationFrame(() => redrawLines(state));
  } catch (e) {
    console.warn("active toggle error", e);
  }
};

// Groups management panel (assignment happens per-tile via the ▦ menu).
const groupsModal = document.getElementById("groups-modal");
const groupsList = document.getElementById("groups-list");
document.getElementById("groups-btn")?.addEventListener("click", () => { renderGroupsList(); groupsModal.classList.remove("hidden"); });
document.getElementById("groups-modal-close")?.addEventListener("click", () => groupsModal.classList.add("hidden"));
groupsModal.addEventListener("click", (e) => { if (e.target === groupsModal) groupsModal.classList.add("hidden"); });

function renderGroupsList() {
  const gs = getGroups();
  groupsList.innerHTML = "";
  if (!gs.length) {
    groupsList.innerHTML = '<li class="groups-empty">No groups yet. Use a tile’s ▦ menu → “New group”.</li>';
    return;
  }
  for (const g of gs) {
    const li = document.createElement("li");
    li.className = "groups-row";

    const swatch = document.createElement("button");
    swatch.className = "group-row-swatch";
    swatch.style.background = g.color;
    swatch.title = "Click to recolor";
    swatch.addEventListener("click", () => {
      const i = GROUP_COLORS.indexOf(g.color);
      recolorGroup(g.id, GROUP_COLORS[(i + 1) % GROUP_COLORS.length]);
      renderGroupsList();
    });

    const name = document.createElement("input");
    name.className = "group-row-name";
    name.value = g.name;
    name.addEventListener("change", () => renameGroup(g.id, name.value.trim() || g.name));

    const count = document.createElement("span");
    count.className = "group-row-count";
    count.textContent = `${g.members.length}`;

    const collapseBtn = document.createElement("button");
    collapseBtn.className = "group-row-btn";
    collapseBtn.textContent = g.collapsed ? "Restore" : "Minimize";
    collapseBtn.addEventListener("click", () => { setGroupCollapsed(g.id, !g.collapsed); renderGroupsList(); });

    const del = document.createElement("button");
    del.className = "group-row-btn";
    del.textContent = "Ungroup";
    del.title = "Delete the group (tiles stay)";
    del.addEventListener("click", () => { deleteGroup(g.id); renderGroupsList(); });

    li.append(swatch, name, count, collapseBtn, del);
    groupsList.appendChild(li);
  }
}

// --- Relaunch (fleet recovery) ----------------------------------------------
// Bring dormant sessions back after a reboot/crash. Pick individually or "launch
// everything"; sort by recency, name, or TOKENS — the token sort matters because
// the fattest-context sessions are the ones that will auto-compact on resume.
const relaunchModal = document.getElementById("relaunch-modal");
const relaunchList = document.getElementById("relaunch-list");
const relaunchAllCb = document.getElementById("relaunch-all");
const relaunchSort = document.getElementById("relaunch-sort");
const relaunchGo = document.getElementById("relaunch-go");
const relaunchStatus = document.getElementById("relaunch-status");
const LS_RELAUNCH_SORT = "conductor.relaunchSort.v1";

function fmtTok(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}
function fmtAge(ts) {
  const s = Math.max(0, Date.now() / 1000 - (Number(ts) || 0));
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}
const parkedOut = (p) => (p.tokens && p.tokens.output) || 0;
const parkedTotal = (p) => (p.tokens && p.tokens.total) || 0;

function sortedParked() {
  const list = [...(state.parked || [])];
  const name = (p) => String(p.tag || p.title || "").toLowerCase();
  switch (relaunchSort.value) {
    case "oldest":     list.sort((a, b) => a.last_activity_at - b.last_activity_at); break;
    case "az":         list.sort((a, b) => name(a).localeCompare(name(b))); break;
    case "za":         list.sort((a, b) => name(b).localeCompare(name(a))); break;
    case "tokens":     list.sort((a, b) => parkedTotal(b) - parkedTotal(a)); break;
    case "tokens-asc": list.sort((a, b) => parkedTotal(a) - parkedTotal(b)); break;
    default:           list.sort((a, b) => b.last_activity_at - a.last_activity_at); // recent
  }
  return list;
}

function syncRelaunchSelection() {
  const boxes = [...relaunchList.querySelectorAll("input[type=checkbox]")];
  const sel = boxes.filter((b) => b.checked);
  relaunchAllCb.checked = boxes.length > 0 && sel.length === boxes.length;
  relaunchAllCb.indeterminate = sel.length > 0 && sel.length < boxes.length;
  relaunchGo.disabled = sel.length === 0;
  relaunchGo.textContent = sel.length
    ? `Relaunch ${sel.length} session${sel.length > 1 ? "s" : ""}`
    : "Relaunch selected";
}

function renderRelaunchList() {
  // Preserve ticks across a re-sort.
  const checked = new Set(
    [...relaunchList.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.value),
  );
  relaunchList.innerHTML = "";
  const list = sortedParked();
  if (!list.length) {
    relaunchList.innerHTML =
      '<li class="relaunch-empty">No dormant sessions — the whole fleet is already running. 🎉</li>';
    relaunchGo.disabled = true;
    return;
  }
  for (const p of list) {
    const li = document.createElement("li");
    li.className = "relaunch-row";
    li.innerHTML =
      `<label><input type="checkbox" value="${escapeHtml(p.project)}"${checked.has(p.project) ? " checked" : ""} />`
      + `<span class="rl-name">${escapeHtml(p.tag || p.title)}</span>`
      + `<span class="rl-meta">${escapeHtml(fmtAge(p.last_activity_at))}</span>`
      + `<span class="rl-tok" title="output ${parkedOut(p).toLocaleString()} · total ${parkedTotal(p).toLocaleString()}">`
      + `${fmtTok(parkedOut(p))} out · ${fmtTok(parkedTotal(p))} total</span></label>`;
    relaunchList.appendChild(li);
  }
  relaunchList.querySelectorAll("input[type=checkbox]")
    .forEach((cb) => cb.addEventListener("change", syncRelaunchSelection));
  syncRelaunchSelection();
}

relaunchAllCb?.addEventListener("change", () => {
  relaunchList.querySelectorAll("input[type=checkbox]")
    .forEach((cb) => { cb.checked = relaunchAllCb.checked; });
  syncRelaunchSelection();
});
relaunchSort?.addEventListener("change", () => {
  try { localStorage.setItem(LS_RELAUNCH_SORT, relaunchSort.value); } catch {}
  renderRelaunchList();
});

function openRelaunch() {
  try { relaunchSort.value = localStorage.getItem(LS_RELAUNCH_SORT) || "recent"; } catch {}
  relaunchStatus.textContent = "";
  relaunchAllCb.checked = false;
  relaunchAllCb.indeterminate = false;
  renderRelaunchList();
  relaunchModal.classList.remove("hidden");
}
document.getElementById("relaunch-btn")?.addEventListener("click", openRelaunch);
document.getElementById("relaunch-modal-close")
  ?.addEventListener("click", () => relaunchModal.classList.add("hidden"));
relaunchModal?.addEventListener("click", (e) => {
  if (e.target === relaunchModal) relaunchModal.classList.add("hidden");
});

relaunchGo?.addEventListener("click", async () => {
  const projects = [...relaunchList.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.value);
  if (!projects.length) return;
  const n = projects.length;
  if (!window.confirm(
    `Relaunch ${n} session${n > 1 ? "s" : ""}?\n\n`
    + `Each resumes with --continue in its own terminal window. They launch one at a `
    + `time (staggered), so a big fleet takes a few minutes to fully come back.`)) return;
  relaunchGo.disabled = true;
  relaunchStatus.textContent = "Launching…";
  try {
    const r = await fetch("/api/relaunch-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projects }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    const skipped = (body.skipped || []).length;
    relaunchStatus.textContent = `Launching ${body.launching}`
      + (skipped ? ` · ${skipped} skipped` : "") + " — they'll appear as they come up.";
    setTimeout(() => relaunchModal.classList.add("hidden"), 2400);
  } catch (err) {
    relaunchStatus.textContent = `Failed: ${err.message}`;
    relaunchGo.disabled = false;
  }
});

window.requestFocus = async function requestFocus(sessionId) {
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/focus`, { method: "POST" });
    if (!r.ok) console.warn("focus failed", r.status);
  } catch (e) {
    console.warn("focus error", e);
  }
};

// Is this Claude actively working? jsonl touched in the last 30s (active/warm).
// Best-effort: a session blocked on a quiet long tool call can still read idle.
function sessionLooksBusy(status) {
  return status === "active" || status === "warm";
}

// Push-approval inbox: a banner listing gated `git push`es awaiting Kyle. One
// click writes the token the PreToolUse gate consumes on the session's next push.
function renderPushInbox(state) {
  const box = document.getElementById("push-inbox");
  if (!box) return;
  const reqs = (state.push && state.push.requests) || [];
  if (!reqs.length) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false;
  const rows = reqs.map((r) => {
    const meta = document.createElement("div");
    meta.className = "push-req-meta";
    meta.innerHTML = `<strong>🔐 ${r.repo_name}</strong> wants to push`
      + (r.created ? ` <span class="push-when">· ${r.created}</span>` : "");
    meta.title = r.cmd || "";
    const approve = document.createElement("button");
    approve.className = "push-approve"; approve.textContent = "Approve push";
    approve.onclick = () => window.decidePush(r.key, "approve", approve);
    const deny = document.createElement("button");
    deny.className = "push-deny"; deny.textContent = "Dismiss";
    deny.onclick = () => window.decidePush(r.key, "deny", deny);
    const row = document.createElement("div");
    row.className = "push-req";
    row.append(meta, approve, deny);
    return row;
  });
  const title = document.createElement("div");
  title.className = "push-inbox-title";
  title.textContent = `🔐 ${reqs.length} push${reqs.length > 1 ? "es" : ""} awaiting your approval — nothing hits a repo without your click`;
  box.replaceChildren(title, ...rows);
}
window.renderPushInbox = renderPushInbox;

window.decidePush = async function decidePush(key, action, btn) {
  if (btn) { btn.disabled = true; btn.textContent = action === "approve" ? "approving…" : "…"; }
  try {
    const r = await fetch(`/api/push/${encodeURIComponent(key)}/${action}`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    // the next scan re-broadcasts the (now shorter) request list and re-renders
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = action === "approve" ? "Approve push" : "Dismiss"; }
    window.alert(`Could not ${action} push: ${err.message}`);
  }
};

// Hand on a lease whose owner's session is gone. Always user-initiated, always
// confirmed — the backend refuses unless it has flagged the lease as orphaned.
window.reclaimResource = async function reclaimResource(name, btn) {
  if (!window.confirm(
    `Reclaim "${name}"?\n\nIts owner's session is no longer running. This hands the resource `
    + `to the next Claude in the queue, or frees it if nobody is waiting.`)) return;
  if (btn) { btn.disabled = true; btn.textContent = "reclaiming…"; }
  try {
    const r = await fetch(`/api/resources/${encodeURIComponent(name)}/reclaim`, { method: "POST" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    // "offered:<tag>" | "freed" — the next scan re-renders the tile either way.
    const msg = String(data.result || "").startsWith("offered:")
      ? `handed to [${String(data.result).slice(8)}]` : "freed";
    if (btn) btn.textContent = msg;
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = "reclaim"; }
    window.alert(`Could not reclaim "${name}": ${err.message}`);
  }
};

window.requestCheck = async function requestCheck(sessionId, status) {
  const guard = (window.conductorPrefs && window.conductorPrefs.busClickGuard) || "confirm-busy";
  const busy = sessionLooksBusy(status);

  // block-busy: tiles.js already disables the badge while busy; guard here too
  // in case status changed between render and click.
  if (guard === "block-busy" && busy) return;

  if (guard === "always-confirm" || (guard === "confirm-busy" && busy)) {
    const prompt = busy
      ? "This Claude looks busy (mid-task). Inject /msg-check anyway? Keystrokes are queued and may interrupt its current work."
      : "Inject /msg-check into this Claude?";
    if (!window.confirm(prompt)) return;
  }
  // "always", or a confirmed/idle case above, falls through to inject.

  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/check`, { method: "POST" });
    if (!r.ok) {
      console.warn("check failed", r.status);
      return;
    }
    const body = await r.json().catch(() => ({}));
    // The server typed /msg-check into the live Claude window. The badge isn't
    // cleared here — it clears on the next scan once that Claude's own check
    // bumps <tag>.last-seen. If injection failed (no X / window not found),
    // warn so the click doesn't look silently broken.
    if (body.injected === false) {
      console.warn(
        "could not type /msg-check into the session window",
        body.wmctrl_available ? "(window not found)" : "(wmctrl/xdotool unavailable)",
      );
    }
  } catch (e) {
    console.warn("check error", e);
  }
};

// Relaunch a parked (offline) session: open `claude --continue` in its folder in
// a tracked terminal, then the backend injects /rc once it's up. The chip shows
// "launching…" optimistically; it disappears on its own when the now-live
// session arrives on the next scan. On error we surface why and let renderGrid
// restore the chip to its normal state.
window.requestRelaunch = async function requestRelaunch(project, projectDir) {
  try {
    const r = await fetch("/api/relaunch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project }),
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      console.warn("relaunch failed", r.status, body.detail || "");
      window.alert(`Couldn't relaunch: ${body.detail || r.status}`);
      renderGrid(state); // clear the optimistic "launching…" chip state
    }
  } catch (e) {
    console.warn("relaunch error", e);
    window.alert("Relaunch request failed — is Conductor still running?");
    renderGrid(state);
  }
};

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Periodically prune ENDED sessions client-side once the fade animation is done.
setInterval(() => {
  const now = Date.now() / 1000;
  let mutated = false;
  for (const s of state.sessions) {
    if (s.status === "ended" && s.ended_at && now - s.ended_at > state.fadeoutSeconds) {
      fadeOutSession(s.session_id);
      mutated = true;
    }
  }
  if (mutated) renderGrid(state);
}, 1000);

// --- Auth unlock overlay ----------------------------------------------------
// Shown only when the server rejects us (401 / WS 1008) — i.e. a token is
// configured (remote access). Local default never triggers it.
let authOverlayShown = false;
function showAuthOverlay(errMsg) {
  if (authOverlayShown) {
    if (errMsg) { const e = document.querySelector(".auth-err"); if (e) e.textContent = errMsg; }
    return;
  }
  authOverlayShown = true;
  const overlay = document.createElement("div");
  overlay.className = "auth-overlay";
  overlay.innerHTML = `
    <form class="auth-card">
      <h2><img src="/static/logo.svg" alt="" width="22" height="22" /> Unlock Conductor</h2>
      <p>This dashboard is protected. Enter your access token to continue.</p>
      <input type="password" inputmode="text" autocomplete="current-password"
             placeholder="Access token" aria-label="Access token" />
      <div class="auth-err">${errMsg ? escapeHtml(errMsg) : ""}</div>
      <button type="submit">Unlock</button>
    </form>`;
  const input = overlay.querySelector("input");
  const err = overlay.querySelector(".auth-err");
  overlay.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const tok = input.value.trim();
    if (!tok) { err.textContent = "Enter a token."; return; }
    setToken(tok);
    // Validate before dismissing so a wrong token doesn't silently fail later.
    try {
      const r = await _origFetch("/api/auth/check", { headers: { "X-Conductor-Token": tok } });
      if (r.ok) {
        overlay.remove();
        authOverlayShown = false;
        boot();               // re-run the full startup with the accepted token
        return;
      }
    } catch {}
    err.textContent = "That token was rejected.";
  });
  document.body.appendChild(overlay);
  input.focus();
}

// Native-app seam: app.py (which knows the configured token) calls this after
// the window loads, so the DESKTOP window auto-unlocks — you never type a token
// on the machine that's running the server. The phone/browser still must enter it.
window.__conductorSeedToken = (t) => {
  if (!t) return;
  setToken(t);           // in-memory + localStorage — no reload, so no flicker
  if (!booted) boot();   // (re)try startup with the token now available
};

// Register the service worker (installable PWA + offline shell). Best-effort;
// only works over a secure context (https / localhost), which is exactly the
// Tailscale-serve setup. A failure is a no-op — the app still runs.
function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("sw register failed", e));
  }
}

// Startup: confirm auth (or that it's disabled), then wire the live connection.
function dismissAuthOverlay() {
  const o = document.querySelector(".auth-overlay");
  if (o) o.remove();
  authOverlayShown = false;
}

// Startup: confirm auth (or that it's disabled), then wire the live connection.
// Concurrency-safe: boot() can run more than once (module load AND the token
// seed), so it re-checks `booted` after the await — whichever call authenticates
// first wins, the others no-op instead of double-connecting or re-showing the
// overlay. No page reload anywhere (that caused the desktop flicker loop).
let booted = false;
async function boot() {
  if (booted) return;
  let ok = false;
  try {
    const t = getToken();
    const r = await _origFetch("/api/auth/check", { headers: t ? { "X-Conductor-Token": t } : {} });
    ok = r.ok;
    if (r.status === 401 && !booted) showAuthOverlay();
  } catch {
    ok = true;  // network error (server down): proceed; the WS reconnect UI shows it
  }
  if (booted || !ok) return;
  booted = true;
  dismissAuthOverlay();     // clear a stray overlay a racing boot() may have shown
  connect();
  registerServiceWorker();
  // Restore the 3D view if it was active last session (guarded import, so a CDN
  // miss just falls back to 2D with a notice).
  setView3dBtn(false);
  if (prefs.view3d) enter3D();
}
boot();
