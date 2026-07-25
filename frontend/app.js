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
  autonomy: { windows: [] },     // live "let them talk" windows
  services: { services: [] },    // service Claudes (image_gen…): serving + queue
  waiting: { edges: [], cycles: [], bottlenecks: [], blocked_count: 0 },  // who blocks whom
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

// 🗂 Projects — the lead-owned multi-session view (Project Layer slice 4). Same lazy-overlay
// discipline as History: a failure in projects.js can never touch the board.
let projectsMod = null;
document.getElementById("projects-btn")?.addEventListener("click", async () => {
  try {
    if (!projectsMod) projectsMod = await import("/static/projects.js");
    projectsMod.activate();
  } catch (err) {
    console.error("projects view failed to load", err);
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
      if (payload.members) state.members = payload.members;
      state.silent = payload.silent || [];
      state.collisions = payload.collisions || [];
      state.lost_rc = payload.lost_rc || [];
      state.webpush = payload.webpush || null;
      sessionCountEl.textContent = `${state.sessions.length} session${state.sessions.length === 1 ? "" : "s"}`;
      renderGrid(state);
      renderFleetAlerts(state);
      applyLinkClasses();
      requestAnimationFrame(() => redrawLines(state));
      refresh3D();
      break;
    case "silent":
      state.silent = (payload && payload.silent) || [];
      renderFleetAlerts(state);
      break;
    case "collisions":
      state.collisions = (payload && payload.collisions) || [];
      renderFleetAlerts(state);
      break;
    case "lost_rc":
      state.lost_rc = (payload && payload.lost_rc) || [];
      renderFleetAlerts(state);
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
    case "projects": {
      // Project Layer (slice 4). The board itself doesn't render projects — they live in the
      // 🗂 overlay — so we just hand the update to an open overlay if there is one.
      state.projects = (payload && payload.projects) || [];
      window.__projectsOnUpdate?.(state.projects);
      break;
    }
    case "members": {
      state.members = (payload && payload.members) || [];
      // roles ride on each session in the sessions payload; a members broadcast just refreshes the
      // registry summary. Re-render so any open role selectors reflect a change made elsewhere.
      renderGrid(state);
      break;
    }
    case "autonomy": {
      state.autonomy = payload || { windows: [] };
      renderAutonomyBar();
      applyLinkClasses();
      requestAnimationFrame(() => redrawLines(state));   // repaint the green wires
      break;
    }
    case "services": {
      state.services = payload || { services: [] };
      renderGrid(state);
      requestAnimationFrame(() => redrawLines(state));
      break;
    }
    case "waiting": {
      state.waiting = payload || { edges: [], cycles: [], bottlenecks: [], blocked_count: 0 };
      updateWaitingBtn();
      if (!document.getElementById("waiting-modal").classList.contains("hidden")) renderWaiting();
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

document.getElementById("refresh-btn")?.addEventListener("click", async (e) => {
  // Force a real rescan (POST /api/rescan) — not GET /api/sessions, which only re-fetched the
  // cached last scan and so did nothing about a stale record. Visible feedback so it never again
  // looks like it did nothing.
  const btn = e.currentTarget;
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Rescanning…";
  try {
    const r = await fetch("/api/rescan", { method: "POST" });
    if (r.ok) {
      const payload = await r.json();
      handleMessage({ kind: "sessions", payload });
    }
  } catch (err) {
    console.warn("rescan failed", err);
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
});

window.addEventListener("resize", () => requestAnimationFrame(() => redrawLines(state)));

// Re-anchor the lines on SCROLL. The .lines-overlay is position:fixed and endpoints use
// viewport coords (getBoundingClientRect), so as the board scrolls beneath the stationary overlay
// the tiles move but the lines don't — they drift off their anchors (glaring with the whole fleet
// linked). capture:true catches scroll from ANY scroller (scroll events don't bubble); passive +
// rAF keep it cheap. Same reason resize redraws.
window.addEventListener("scroll", () => requestAnimationFrame(() => redrawLines(state)),
  { capture: true, passive: true });

// Self-heal on wake. A backgrounded tab — especially on a phone — can have its
// WebSocket killed WITHOUT the `close` event ever firing, so the reconnect loop never
// starts and the board silently freezes on stale state (the push inbox showing no
// pending approvals when there are some). Whenever the page becomes visible again:
// reconnect if the socket is actually dead, and resync the state that matters either
// way. No manual refresh.
async function resyncOnWake() {
  if (document.visibilityState !== "visible") return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    setConnState(false);
    connect();               // dead or dying socket -> reconnect now, don't wait
    return;                  // the fresh connection sends a full snapshot anyway
  }
  try {                      // socket claims to be alive: pull the live-critical bits
    const [p, ss] = await Promise.all([
      fetch("/api/push").then((r) => (r.ok ? r.json() : null)).catch(() => null),
      fetch("/api/sessions").then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]);
    if (p) { state.push = p; renderPushInbox(state); }
    if (ss) handleMessage({ kind: "sessions", payload: ss });
  } catch {}
}
document.addEventListener("visibilitychange", resyncOnWake);
window.addEventListener("focus", resyncOnWake);
window.addEventListener("online", resyncOnWake);

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

// Member registry (v4 §3.4): set a session's member ROLE. Observer LOWERS authority (read-only),
// Trusted RAISES it — so this is always Kyle's deliberate tap. The referee reads the members file on
// its next tool call; nothing is pushed to the session.
window.setMemberRole = async function setMemberRole(member, role) {
  if (!member) return;
  try {
    const r = await fetch(`/api/members/${encodeURIComponent(member)}/role`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!r.ok) { console.warn("role set failed", r.status); return; }
    const body = await r.json();
    // optimistic: stamp the role onto every live session of this member so the tiles update at once
    for (const s of (state.ops && state.ops.sessions) || state.sessions || []) {
      if (s.member === member) s.role = role;
    }
    renderGrid(state);
  } catch (e) {
    console.warn("role set error", e);
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

// --- 🔗 Autonomy windows ("let them talk") -----------------------------------
// The problem: a session parked at its prompt is WAITING, and WAITING is never
// auto-woken (Kyle might be typing at it). Since that's the resting state of every
// quiet session, it's what forces him to hand-click "check msgs" 30+ times. A window
// is the permission slip: "I'm not at these keyboards — let them wake each other."
let linkMode = false;
const linkSel = new Set();          // tags selected while in link mode
const linkBar = document.getElementById("link-bar");
const linkCountEl = document.getElementById("link-count");
const autonomyBar = document.getElementById("autonomy-bar");

function applyLinkClasses() {
  const members = new Set();
  for (const w of (state.autonomy && state.autonomy.windows) || []) {
    for (const m of w.members || []) members.add(m);
  }
  for (const el of document.querySelectorAll(".tile[data-tag]")) {
    const tag = el.dataset.tag;
    const picked = linkMode && linkSel.has(tag);
    el.classList.toggle("link-selected", picked);
    el.classList.toggle("in-window", members.has(tag));

    // A pulsing ring that becomes a green ✓ when picked — so it's obvious the tile
    // IS the button. Purely an indicator: the tile's own pointerdown handles the
    // click (anywhere on the tile), so this needs no listener of its own.
    const hdr = el.querySelector(".tile-header");
    if (hdr) {
      let pick = hdr.querySelector(".link-pick");
      if (!pick) {
        pick = document.createElement("span");
        pick.className = "link-pick";
        pick.setAttribute("aria-hidden", "true");
        hdr.appendChild(pick);
      }
      pick.textContent = picked ? "✓" : "";
      pick.classList.toggle("picked", picked);
    }
  }
  document.body.classList.toggle("link-mode", linkMode);
}
// tiles.js calls this after every render (it rewrites tile.className wholesale).
window.applyLinkClasses = applyLinkClasses;

function liveTags() {
  return (state.sessions || []).filter((s) => s.status !== "ended" && s.tag).map((s) => s.tag);
}

function syncLinkBar() {
  const n = linkSel.size;
  linkCountEl.textContent = n === 0 ? "none selected" : `${n} selected`;
  const go = document.getElementById("link-go");
  if (go) go.disabled = n < 2;              // a window of one means nothing
  const clear = document.getElementById("link-clear");
  if (clear) clear.disabled = n === 0;
  // "Whole fleet" flips to "Clear all" once everything is selected, so an accidental
  // select-all is undone by the very button that caused it.
  const all = document.getElementById("link-all");
  if (all) {
    const total = liveTags().length;
    const everything = total > 0 && n >= total;
    all.textContent = everything ? "Deselect all" : "Whole fleet";
    all.classList.toggle("on", everything);
  }
}

window.toggleLinkSelect = function toggleLinkSelect(tag) {
  if (linkSel.has(tag)) linkSel.delete(tag); else linkSel.add(tag);
  syncLinkBar();
  applyLinkClasses();
};

function setLinkMode(on) {
  linkMode = on;
  window.conductorLinkMode = on;     // read by tiles.js to select instead of drag
  if (!on) linkSel.clear();
  linkBar.hidden = !on;
  const btn = document.getElementById("link-btn");
  if (btn) btn.classList.toggle("on", on);
  syncLinkBar();
  applyLinkClasses();
}

document.getElementById("link-btn")?.addEventListener("click", () => setLinkMode(!linkMode));
document.getElementById("link-cancel")?.addEventListener("click", () => setLinkMode(false));
// Whole fleet <-> Deselect all. Toggling on the same button means an accidental
// select-all is undone by exactly the control that caused it.
document.getElementById("link-all")?.addEventListener("click", () => {
  const tags = liveTags();
  if (tags.length && linkSel.size >= tags.length) linkSel.clear();
  else for (const t of tags) linkSel.add(t);
  syncLinkBar();
  applyLinkClasses();
});

document.getElementById("link-clear")?.addEventListener("click", () => {
  linkSel.clear();
  syncLinkBar();
  applyLinkClasses();
});

document.getElementById("link-go")?.addEventListener("click", async () => {
  const members = [...linkSel];
  if (members.length < 2) return;
  const hours = parseFloat(document.getElementById("link-hours").value) || 8;
  const go = document.getElementById("link-go");
  go.disabled = true;
  try {
    const r = await fetch("/api/autonomy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ members, hours }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    setLinkMode(false);   // the WS broadcast repaints the bar + the green wires
  } catch (err) {
    go.disabled = false;
    window.alert(`Couldn't open the window: ${err.message}`);
  }
});

// Kyle's override on a service Claude. "Serve me next" is a HOLD on the queue, not a
// place in it: it finishes the job it's on (no wasted GPU render) and then waits for
// him rather than pulling the next one.
window.serviceAction = async function serviceAction(name, action, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "…"; }
  try {
    const r = await fetch(`/api/services/${encodeURIComponent(name)}/${action}`, { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    // the WS broadcast repaints the tile
  } catch (err) {
    if (btn) btn.disabled = false;
    window.alert(`Couldn't ${action} ${name}: ${err.message}`);
  }
};

window.endAutonomy = async function endAutonomy(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "ending…"; }
  try {
    const r = await fetch(`/api/autonomy/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = "End now"; }
    window.alert(`Couldn't end it: ${err.message}`);
  }
};

function fmtLeft(secs) {
  secs = Math.max(0, Math.round(secs));
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${secs}s`;
}

function renderAutonomyBar() {
  const wins = (state.autonomy && state.autonomy.windows) || [];
  if (!wins.length) { autonomyBar.hidden = true; autonomyBar.replaceChildren(); return; }
  autonomyBar.hidden = false;
  const now = Date.now() / 1000;
  const rows = wins.map((w) => {
    const row = document.createElement("div");
    row.className = "autonomy-row";
    const names = (w.members || []).map((t) => t.replace(/^\[|\]$/g, "").replace(/^other:/, ""));
    const shown = names.length > 4 ? `${names.slice(0, 4).join(", ")} +${names.length - 4} more` : names.join(", ");
    const meta = document.createElement("div");
    meta.className = "autonomy-meta";
    meta.innerHTML = `<strong>🔗 ${names.length} Claudes talking freely</strong>`
      + ` <span class="autonomy-left" data-expires="${w.expires}">${fmtLeft(w.expires - now)} left</span>`
      + `<div class="autonomy-members">${escapeHtml(shown)}</div>`;
    const end = document.createElement("button");
    end.className = "autonomy-end";
    end.textContent = "End now";
    end.onclick = () => window.endAutonomy(w.id, end);
    row.append(meta, end);
    return row;
  });
  const title = document.createElement("div");
  title.className = "autonomy-title";
  title.textContent = "🔗 Autonomy window — these sessions may wake each other on directed mail, "
    + "even while parked at a prompt. Busy ones are never interrupted; nothing reaches a repo without your click.";
  autonomyBar.replaceChildren(title, ...rows);
}

// Tick the countdowns without re-rendering the bar.
setInterval(() => {
  const now = Date.now() / 1000;
  for (const el of document.querySelectorAll(".autonomy-left[data-expires]")) {
    el.textContent = `${fmtLeft(parseFloat(el.dataset.expires) - now)} left`;
  }
}, 1000);


// --- ⏳ Who's blocked on whom -------------------------------------------------
// Kyle's original ask, and the last piece of the coordination arc. Every input already
// existed (directed mail, service queues, resource queues) — this is a VIEW over data we
// collect anyway. An edge A -> B means "A is blocked on B".
//
// Deliberately ACTIONABLE: showing a bottleneck without letting you clear it is half a
// feature. Each blocker gets Nudge (type /msg-check into it) and Show (raise its window).
function bareTag(t) {
  return String(t || "").replace(/^\[|\]$/g, "").replace(/^other:/, "").toLowerCase();
}
function sessionForPlain(plain) {
  return (state.sessions || []).find(
    (s) => s.status !== "ended" && bareTag(s.tag) === plain);
}
// Format a DURATION in seconds ("2h 5m" / "3m" / "40s"). Distinct from fmtAge(ts) below, which
// formats a past TIMESTAMP as "… ago" — they were both named fmtAge, which is a hard SyntaxError in
// WebKitGTK (the native desktop) and blanked the whole app; Chromium silently let the 2nd win, which
// also meant these duration call-sites were being fed to the timestamp formatter. Renamed.
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec >= 3600) return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
  if (sec >= 60) return `${Math.floor(sec / 60)}m`;
  return `${sec}s`;
}

function updateWaitingBtn() {
  const btn = document.getElementById("waiting-btn");
  if (!btn) return;
  const w = state.waiting || {};
  const hard = w.blocked_count || 0;       // genuinely trapped (resource / service queue)
  const soft = w.awaiting_count || 0;      // merely awaiting a reply
  const dead = (w.cycles || []).some((c) => c.deadlock);
  // Only the HARD count gets to shout. Twenty sessions awaiting a reply on a fast fleet
  // is a conversation, not a crisis — and a button that alarms on a healthy fleet is one
  // you stop reading, which means it won't be believed the night something deadlocks.
  btn.textContent = hard ? `⏳ ${hard} blocked` : soft ? `⏳ ${soft} waiting` : "⏳ Flowing";
  btn.classList.toggle("has-blocked", hard > 0);
  btn.classList.toggle("has-deadlock", dead);
  btn.title = dead
    ? "DEADLOCK — sessions that can never proceed without you"
    : hard
      ? `${hard} session(s) TRAPPED (queued for a board or a service)`
      : soft
        ? `Nothing is blocked. ${soft} session(s) are simply awaiting a reply — that's a conversation, not a problem.`
        : "Nobody is waiting on anybody. The fleet is flowing.";
}

function actionBtns(plain) {
  const rec = sessionForPlain(plain);
  const wrap = document.createElement("span");
  wrap.className = "wait-acts";
  if (!rec) {
    wrap.innerHTML = '<span class="wait-dead" title="No live session with this tag">offline</span>';
    return wrap;
  }
  const nudge = document.createElement("button");
  nudge.className = "wait-act";
  nudge.textContent = "Nudge";
  nudge.title = "Type /msg-check into this Claude so it goes and reads its mail";
  nudge.onclick = (e) => { e.stopPropagation(); window.requestCheck(rec.session_id, rec.status); };
  const show = document.createElement("button");
  show.className = "wait-act";
  show.textContent = "Show";
  show.title = "Raise this Claude's terminal window";
  show.onclick = (e) => { e.stopPropagation(); window.requestFocus(rec.session_id); };
  wrap.append(nudge, show);
  return wrap;
}

function renderWaiting() {
  const body = document.getElementById("waiting-body");
  if (!body) return;
  const w = state.waiting || {};
  const edges = w.edges || [], cycles = w.cycles || [], necks = w.bottlenecks || [];
  body.replaceChildren();

  if (!edges.length) {
    body.innerHTML = '<p class="wait-clear">✅ Nobody is waiting on anybody. The whole fleet is flowing.</p>';
    return;
  }
  const hard = w.blocked_count || 0, soft = w.awaiting_count || 0;
  const verdict = document.createElement("div");
  verdict.className = "wait-verdict" + (hard ? " bad" : " good");
  verdict.innerHTML = hard
    ? `<strong>${hard} session(s) genuinely TRAPPED</strong> — queued for a board or a service `
      + `they cannot proceed without.` + (soft ? ` (${soft} more are merely awaiting a reply.)` : "")
    : `<strong>✅ Nothing is blocked.</strong> ${soft} session(s) are awaiting a reply — `
      + `on a fast fleet that's a conversation in flight, not a problem. `
      + `This panel shouts only when someone genuinely <em>cannot proceed</em>.`;
  body.appendChild(verdict);

  const sec = (title, hint) => {
    const h = document.createElement("div");
    h.className = "wait-sec";
    h.innerHTML = `<h3>${title}</h3>${hint ? `<p class="wait-hint">${hint}</p>` : ""}`;
    body.appendChild(h);
    return h;
  };

  if (cycles.length) {
    sec("🔴 Cycles",
        "A cycle means nobody in it can move. Only an <strong>all-resource</strong> cycle is a true "
        + "deadlock — it will never resolve itself. A cycle through mail is a <em>mutual stall</em>: "
        + "annoying, invisible, but either side could break it by simply replying.");
    for (const c of cycles) {
      const row = document.createElement("div");
      row.className = "wait-cycle" + (c.deadlock ? " is-deadlock" : "");
      const chain = c.nodes.concat(c.nodes[0]).join(" → ");
      row.innerHTML = `<div class="wait-cycle-head">${c.deadlock ? "💀 DEADLOCK" : "🔁 Mutual stall"}`
        + `<span class="wait-kinds">${(c.kinds || []).join(", ")}</span></div>`
        + `<div class="wait-chain">${escapeHtml(chain)}</div>`
        + `<div class="wait-why">${escapeHtml(c.label)}</div>`;

      // Tell them. A stall is invisible from INSIDE it: each side thinks it is politely
      // awaiting a reply, and each is right, which is exactly why neither speaks. The only
      // actor who can see the loop is the one standing outside it — that's this panel.
      const tell = document.createElement("button");
      tell.className = "wait-tell";
      tell.textContent = c.deadlock ? "Tell them it's a deadlock" : "Tell them they're both waiting";
      tell.onclick = async () => {
        tell.disabled = true;
        tell.textContent = "Telling them…";
        try {
          // window.fetch is already wrapped to inject the auth token on /api/*.
          const r = await fetch("/api/unstall", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nodes: c.nodes }),
          });
          if (!r.ok) {
            const err = new Error((await r.json().catch(() => ({}))).detail || r.statusText);
            err.status = r.status;
            throw err;
          }
          const d = await r.json();
          tell.textContent = d.pinged.length
            ? `✅ Told them · woke ${d.pinged.join(", ")}`
            : "✅ Told them — they'll see it when they surface";
        } catch (e) {
          // These 409/429s are benign, not failures: the stall resolved itself, or they
          // were already told. Say the true thing, don't cry "Failed" (and on a resolved
          // stall there's nothing left to click, so leave the button spent).
          if (e.status === 409) { tell.textContent = "Already resolved"; }
          else if (e.status === 429) { tell.textContent = "Already told them"; tell.disabled = false; }
          else { tell.textContent = `Failed: ${e.message}`; tell.disabled = false; }
        }
      };
      row.appendChild(tell);
      body.appendChild(row);
    }
  }

  sec("🔥 Bottlenecks",
      "Who is holding up the most sessions. This is where one minute of your attention buys the most.");
  for (const b of necks.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = "wait-neck";
    const meta = document.createElement("div");
    meta.className = "wait-neck-meta";
    meta.innerHTML = `<strong>${escapeHtml(b.tag)}</strong>`
      + `<span class="wait-count">${b.count} waiting</span>`
      + `<span class="wait-age">worst ${fmtDur(b.worst_age)}</span>`
      + (b.live ? "" : '<span class="wait-dead">⚠️ no live session</span>')
      + `<div class="wait-blockees">${escapeHtml(b.blocking.join(", "))}</div>`;
    row.append(meta, actionBtns(b.tag));
    body.appendChild(row);
  }

  sec("⏳ Longest waits", "Every edge — <strong>A → B</strong> means A is blocked on B.");
  const ul = document.createElement("ul");
  ul.className = "wait-edges";
  for (const e of edges.slice(0, 25)) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="wait-src">${escapeHtml(e.src)}</span>`
      + `<span class="wait-arrow">→</span>`
      + `<span class="wait-dst">${escapeHtml(e.dst)}</span>`
      + `<span class="wait-kind k-${escapeHtml(e.kind)}">${escapeHtml(e.kind)}</span>`
      + `<span class="wait-age">${fmtDur(e.age)}</span>`
      + `<span class="wait-why">${escapeHtml(e.why)}</span>`;
    ul.appendChild(li);
  }
  body.appendChild(ul);
}

const waitingModal = document.getElementById("waiting-modal");
document.getElementById("waiting-btn")?.addEventListener("click", () => {
  renderWaiting();
  waitingModal.classList.remove("hidden");
});
document.getElementById("waiting-modal-close")
  ?.addEventListener("click", () => waitingModal.classList.add("hidden"));
waitingModal?.addEventListener("click", (e) => {
  if (e.target === waitingModal) waitingModal.classList.add("hidden");
});

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

// --- Reconstitute (DR capstone): rebuild the fleet from the roster ------------
// Reads /api/reconstitute (the plan per session) and, for the ones you tick, runs
// clone → --continue. Read-only until you press go; already-live sessions can't be
// selected; missing-transcript / dirty-repo blockers are shown, not hidden.
const reconModal = document.getElementById("reconstitute-modal");
const reconList = document.getElementById("reconstitute-list");
const reconAllCb = document.getElementById("reconstitute-all");
const reconGo = document.getElementById("reconstitute-go");
const reconStatus = document.getElementById("reconstitute-status");
const reconSummary = document.getElementById("reconstitute-summary");
let reconPlan = null;

const RECON_BADGE = {
  live: ["live", "recon-b-live"],
  present: ["relaunch", "recon-b-present"],
  clone: ["clone repo", "recon-b-clone"],
  "transcript-only": ["resume (no repo)", "recon-b-tx"],
  blocked: ["can't recover", "recon-b-blocked"],
};

function syncReconSelection() {
  const boxes = [...reconList.querySelectorAll("input[type=checkbox]:not(:disabled)")];
  const sel = boxes.filter((b) => b.checked);
  reconAllCb.checked = boxes.length > 0 && sel.length === boxes.length;
  reconAllCb.indeterminate = sel.length > 0 && sel.length < boxes.length;
  reconGo.disabled = sel.length === 0;
  reconGo.textContent = sel.length ? `Reconstitute ${sel.length}` : "Reconstitute selected";
}

function renderReconList() {
  reconList.replaceChildren();
  if (!reconPlan) { reconStatus.textContent = "Loading the recovery plan…"; return; }
  const sessions = reconPlan.sessions || [];
  const c = reconPlan.counts || {};
  reconSummary.textContent =
    `${reconPlan.session_count} sessions · ${c.live || 0} live · `
    + `${(c.present || 0) + (c.clone || 0) + (c["transcript-only"] || 0)} recoverable`
    + (c.blocked ? ` · ${c.blocked} blocked` : "");
  for (const s of sessions) {
    const li = document.createElement("li");
    li.className = "recon-item";
    const [label, cls] = RECON_BADGE[s.status] || [s.status, ""];
    const selectable = s.recoverable && s.status !== "live";
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.value = s.cwd; cb.disabled = !selectable;
    cb.addEventListener("change", syncReconSelection);
    const body = document.createElement("div");
    body.className = "recon-body";
    const repo = s.git_remote ? escapeHtml(s.git_remote)
      : (s.is_repo ? "(local repo)" : "(no repo)");
    const blockers = (s.blockers || []).map((b) =>
      `<div class="recon-blocker">⚠ ${escapeHtml(b)}</div>`).join("");
    body.innerHTML =
      `<div class="recon-head"><span class="recon-badge ${cls}">${label}</span> `
      + `<strong>${escapeHtml(s.tag || s.cwd)}</strong> `
      + `<span class="recon-sub">${fmtTok(s.tokens_out)} out · ${fmtAge(s.last_active)}</span></div>`
      + `<div class="recon-sub">${escapeHtml(s.cwd)}</div>`
      + `<div class="recon-sub">${repo}${s.git_dirty ? " · ⚠ dirty" : ""}`
      + `${s.transcripts_present ? "" : " · ⚠ no transcript on disk"}</div>`
      + blockers;
    const lbl = document.createElement("label");
    lbl.className = "recon-label" + (selectable ? "" : " recon-disabled");
    lbl.append(cb, body);
    li.append(lbl);
    reconList.append(li);
  }
  syncReconSelection();
}

async function openReconstitute() {
  reconStatus.textContent = "";
  reconAllCb.checked = false; reconAllCb.indeterminate = false;
  reconPlan = null;
  renderReconList();
  reconModal.classList.remove("hidden");
  try {
    const r = await fetch("/api/reconstitute");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    reconPlan = await r.json();
    renderReconList();
  } catch (err) {
    reconStatus.textContent = `Couldn't load the recovery plan: ${err.message}`;
  }
}
document.getElementById("reconstitute-btn")?.addEventListener("click", openReconstitute);
document.getElementById("reconstitute-modal-close")
  ?.addEventListener("click", () => reconModal.classList.add("hidden"));
reconModal?.addEventListener("click", (e) => {
  if (e.target === reconModal) reconModal.classList.add("hidden");
});
reconAllCb?.addEventListener("change", () => {
  const boxes = [...reconList.querySelectorAll("input[type=checkbox]:not(:disabled)")];
  boxes.forEach((b) => { b.checked = reconAllCb.checked; });
  syncReconSelection();
});

reconGo?.addEventListener("click", async () => {
  const cwds = [...reconList.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.value);
  if (!cwds.length) return;
  if (!window.confirm(
    `Reconstitute ${cwds.length} session${cwds.length > 1 ? "s" : ""}?\n\n`
    + `Each will clone its repo (if missing) and open 'claude --continue' in a tracked `
    + `window. They run one at a time. On THIS machine most are already present — this is `
    + `built for a fresh box after a restore.`)) return;
  reconGo.disabled = true;
  let done = 0, failed = 0;
  // Staggered — one at a time, so clones + spawns don't stampede the box.
  for (const cwd of cwds) {
    reconStatus.textContent = `Reconstituting ${done + failed + 1}/${cwds.length}…`;
    try {
      const r = await fetch("/api/reconstitute/execute", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cwd }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
      done++;
    } catch (err) {
      failed++;
      console.warn("reconstitute failed for", cwd, err.message);
    }
  }
  reconStatus.textContent = `Done — launched ${done}`
    + (failed ? `, ${failed} failed (see console)` : "") + ". They appear as they come up.";
  setTimeout(() => { openReconstitute(); }, 2500);  // refresh the plan (statuses change)
});

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
  const grants = (state.push && state.push.grants) || [];
  if (!reqs.length && !grants.length) { box.hidden = true; box.replaceChildren(); return; }
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
  // Approvals already GIVEN and not yet used. This state used to be invisible, and that
  // was the whole bug: a click that landed looked identical to a click that evaporated.
  const grantRows = grants.map((g) => {
    const meta = document.createElement("div");
    meta.className = "push-req-meta";
    const hrs = Math.max(0, Math.round(g.expires_in / 3600));
    meta.innerHTML = `<strong>✅ ${g.repo_name}</strong> approved — waiting for the session to push`
      + ` <span class="push-when">· expires in ${hrs}h</span>`;
    const revoke = document.createElement("button");
    revoke.className = "push-deny"; revoke.textContent = "Revoke";
    revoke.onclick = () => window.decidePush(g.key, "revoke", revoke);
    const row = document.createElement("div");
    row.className = "push-req push-granted";
    row.append(meta, revoke);
    return row;
  });

  const title = document.createElement("div");
  title.className = "push-inbox-title";
  title.textContent = reqs.length
    ? `🔐 ${reqs.length} push${reqs.length > 1 ? "es" : ""} awaiting your approval — nothing hits a repo without your click`
    : `✅ ${grants.length} approval${grants.length > 1 ? "s" : ""} armed — waiting for the session to push`;
  box.replaceChildren(title, ...rows, ...grantRows);
}
window.renderPushInbox = renderPushInbox;

// Fleet-health alerts (holobench). Two failure shapes of "a session's identity/reachability is
// wrong and nobody would otherwise notice":
//   • COLLISION — two live sessions posting under one tag (identity derived from the cwd).
//   • DEAD READER — a session others are directly waiting on that isn't running (silent + open ask).
// Both went unnoticed for hours/days because no signal surfaced them; this is that signal.
function fmtSilence(sec) {
  if (sec == null) return "has never posted";
  const h = sec / 3600;
  if (h >= 24) return `silent ${Math.floor(h / 24)}d`;
  if (h >= 1) return `silent ${Math.floor(h)}h`;
  return `silent ${Math.max(1, Math.floor(sec / 60))}m`;
}
function fmtAgo(sec) {
  if (sec == null) return "unknown";
  const h = sec / 3600;
  if (h >= 24) return `${Math.floor(h / 24)}d ago`;
  if (h >= 1) return `${Math.floor(h)}h ago`;
  return `${Math.max(1, Math.floor(sec / 60))}m ago`;
}
function renderFleetAlerts(state) {
  const box = document.getElementById("fleet-alerts");
  if (!box) return;
  const collisions = state.collisions || [];
  const lostRc = state.lost_rc || [];
  const silent = state.silent || [];
  const dead = silent.filter((s) => s.dead);
  const quiet = silent.filter((s) => !s.dead);   // addressed + silent but a process is still alive
  const wp = state.webpush;                       // can we page the phone? (2026-07-22)
  const wpBroken = wp && wp.healthy === false;
  if (!collisions.length && !lostRc.length && !dead.length && !quiet.length && !wpBroken) {
    box.hidden = true; box.replaceChildren(); return;
  }
  box.hidden = false;
  const rows = [];
  if (wpBroken) {
    // An app that can't alert you should at least TELL you it can't — the 2026-07-22
    // incident (paging dead 6h, a Claude blocked the whole time, nothing said so).
    const row = document.createElement("div");
    row.className = "alert-row alert-webpush";
    const fix = wp.reason === "no_subscription"
      ? `Turn on notifications for this phone (Notifications panel), or watch the inbox.`
      : `Server-side notifications are down. Blocked questions and pushes are still in the inbox below.`;
    row.innerHTML =
      `<strong>🔕 Phone notifications aren't reaching you</strong> — ${escapeHtml(wp.detail || "")}`
      + `<div class="alert-sub" style="margin-top:4px">${fix}</div>`;
    rows.push(row);
  }
  for (const c of collisions) {
    const row = document.createElement("div");
    row.className = "alert-row alert-collision";
    // Show WHAT each colliding session is doing (last activity + preview) so Kyle can tell which to
    // keep — "reshirt, reshirt" is useless; "one active 9m ago building X, one 29m ago on Y" is not.
    const recent = (c.recent || []).map((t, i) =>
      `<div class="alert-sess"><span class="alert-sess-tag">#${i + 1} · active ${fmtAgo(t.age)}</span> `
      + `<span class="alert-sub">${escapeHtml((t.preview || t.title || "(no preview)").slice(0, 120))}</span></div>`
    ).join("");
    row.innerHTML =
      `<strong>⚠️ Identity collision:</strong> ${c.count} live sessions post as `
      + `<code>[${escapeHtml(c.member)}]</code> — a reply can reach the wrong one.`
      + recent
      + `<div class="alert-sub" style="margin-top:4px">Both are live. Keep the one doing the work you want, close the other — or coordinate explicitly if the split is deliberate. In a shared repo a <code>git add -A</code> can also sweep the other session's work into your commit.</div>`;
    rows.push(row);
  }
  for (const r0 of lostRc) {
    const row = document.createElement("div");
    row.className = "alert-row alert-lostrc";
    // The rt1180 trap (§3.4.1): alive but invisible in the phone app -> looks crashed -> relaunched
    // into a duplicate. Say "alive, reconnect, DON'T relaunch" so Kyle resolves it the right way.
    row.innerHTML =
      `<strong>📵 ${escapeHtml(r0.member)} is ALIVE but lost its /RC</strong> `
      + `(${r0.lost_rc_minutes}m ago) — it's gone from the phone's Claude app, but the process is running.`
      + `<div class="alert-sub" style="margin-top:4px">Reconnect it (<code>/rc</code>) — do NOT relaunch, or you'll put a second session in the same repo.`
      + (r0.preview ? ` Last: ${escapeHtml((r0.preview || "").slice(0, 110))}` : "")
      + `</div>`;
    rows.push(row);
  }
  for (const s of dead) {
    const row = document.createElement("div");
    row.className = "alert-row alert-dead";
    const who = (s.open_ask_from || s.addressed_by || []).join(", ") || "someone";
    row.innerHTML =
      `<strong>💀 ${escapeHtml(s.tag)} isn't running</strong> — ${escapeHtml(who)} has `
      + `${s.open_ask_count} open question${s.open_ask_count === 1 ? "" : "s"} waiting on it `
      + `(${fmtSilence(s.silent_for)}). <span class="alert-sub">Relaunch it or it stays stuck.</span>`;
    rows.push(row);
  }
  for (const s of quiet) {
    const row = document.createElement("div");
    row.className = "alert-row alert-quiet";
    const who = (s.addressed_by || []).join(", ") || "someone";
    row.innerHTML =
      `<strong>🕰 ${escapeHtml(s.tag)}</strong> is being addressed by ${escapeHtml(who)} but has `
      + `${fmtSilence(s.silent_for)}. <span class="alert-sub">Its process is alive — maybe deep in a task, maybe not reading its mail.</span>`;
    rows.push(row);
  }
  const title = document.createElement("div");
  title.className = "fleet-alerts-title";
  const parts = [];
  if (collisions.length) parts.push(`${collisions.length} identity collision${collisions.length > 1 ? "s" : ""}`);
  if (lostRc.length) parts.push(`${lostRc.length} lost /RC`);
  if (dead.length) parts.push(`${dead.length} dead reader${dead.length > 1 ? "s" : ""}`);
  if (quiet.length) parts.push(`${quiet.length} unresponsive`);
  if (wpBroken) parts.push(`notifications down`);
  title.textContent = `🩺 Fleet health — ${parts.join(" · ")}`;
  box.replaceChildren(title, ...rows);
}
window.renderFleetAlerts = renderFleetAlerts;

window.decidePush = async function decidePush(key, action, btn) {
  if (btn) { btn.disabled = true; btn.textContent = action === "approve" ? "approving…" : "…"; }
  try {
    const r = await fetch(`/api/push/${encodeURIComponent(key)}/${action}`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    // the next scan re-broadcasts the (now shorter) request list and re-renders
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = action === "approve" ? "Approve push" : "Dismiss"; }
    showToast(`Couldn't ${action} the push: ${err.message}`, { kind: "warn" });
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
    // The 409 reason ("owner's session is live / not offline long enough") IS the point —
    // show it, so a refused reclaim explains itself instead of just bouncing.
    showToast(`Can't reclaim "${name}": ${err.message}`, { kind: "warn" });
  }
};

// A minimal ephemeral toast — feedback where the click happened, so an action that was
// intentionally declined (a wake into a busy/asking session) never reads as "broken".
// Optional action button (label + handler) for "go do the thing instead".
function showToast(msg, opts = {}) {
  const { kind = "info", actionLabel, onAction, ttl = 6000 } = opts;
  let host = document.getElementById("toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast-host";
    document.body.appendChild(host);
  }
  const t = document.createElement("div");
  t.className = `toast toast-${kind}`;
  const span = document.createElement("span");
  span.textContent = msg;
  t.appendChild(span);
  const kill = () => { t.classList.add("toast-out"); setTimeout(() => t.remove(), 250); };
  if (actionLabel && onAction) {
    const b = document.createElement("button");
    b.className = "toast-action";
    b.textContent = actionLabel;
    b.onclick = () => { try { onAction(); } finally { kill(); } };
    t.appendChild(b);
  }
  host.appendChild(t);
  setTimeout(kill, ttl);
}
window.showToast = showToast;

// Resource asset card — how to access + set up a shared resource (an EVK, the GPU, …).
// Sections render as <pre> via textContent: the bodies are raw notes (ssh commands, key paths)
// — preformatted preserves them exactly, and textContent means no HTML injection from a card.
window.showResourceCard = function showResourceCard(res) {
  const modal = document.getElementById("card-modal");
  const titleEl = document.getElementById("card-modal-title");
  const body = document.getElementById("card-modal-body");
  const card = res && res.card;
  if (!modal || !card) return;
  titleEl.textContent = (res.label || res.name) + (card.kind ? ` · ${card.kind}` : "");
  body.replaceChildren();
  if (card.summary) {
    const s = document.createElement("div");
    s.className = "card-summary"; s.textContent = card.summary;
    body.appendChild(s);
  }
  for (const sec of card.sections || []) {
    const wrap = document.createElement("section");
    wrap.className = "card-section" + (sec.key === "access" ? " card-access" : "");
    const h = document.createElement("h3");
    h.textContent = (sec.key === "access" ? "🔑 " : "") + sec.title;
    const pre = document.createElement("pre");
    pre.className = "card-pre"; pre.textContent = sec.body;
    wrap.append(h, pre);
    body.appendChild(wrap);
  }
  if (!(card.sections || []).length) {
    const e = document.createElement("div");
    e.className = "card-empty"; e.textContent = "This card has no sections filled in yet.";
    body.appendChild(e);
  }
  modal.classList.remove("hidden");
};
document.getElementById("card-modal-close")
  ?.addEventListener("click", () => document.getElementById("card-modal").classList.add("hidden"));
document.getElementById("card-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "card-modal") e.currentTarget.classList.add("hidden");
});

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
      // Don't fail silently — say WHY, and offer the right next action.
      if (body.reason === "asking") {
        showToast("This session is asking YOU a question — answering here would corrupt it.",
          { kind: "warn", actionLabel: "Focus it to answer",
            onAction: () => window.requestFocus(sessionId) });
      } else if (body.reason === "busy") {
        showToast("It's busy working — I didn't interrupt it. It'll read messages the moment it pauses.",
          { kind: "info" });
      } else {
        showToast(body.wmctrl_available
          ? "Couldn't reach the session's window (not found)."
          : "Can't type into the window — xdotool/wmctrl unavailable.", { kind: "warn" });
      }
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
