// app.js — WebSocket client + top-level state. Delegates rendering to tiles.js / lines.js.

import { renderGrid, flashTilePreview, fadeOutSession, resetLayout } from "/static/tiles.js";
import { redrawLines, animateLineFor } from "/static/lines.js";

const state = {
  sessions: [],     // SessionRecord[]
  fadeoutSeconds: 30,
  wmctrlAvailable: false,

  busTotal: 0,
  busRecent: [],    // BusEvent[] (most recent last)
  busTopology: { subscribers: {} },
  busUnseen: 0,
  busPendingByTag: {},
  busAdapter: "markdown",
};

window.conductorState = state; // for ad-hoc debugging from devtools

// --- Display preferences (client-side, localStorage) ------------------------
const PREFS_KEY = "conductor.prefs.v1";
const DEFAULT_PREFS = {
  theme: "dark", lines: true, animation: true, showEnded: true,
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

function applyTheme() {
  document.documentElement.dataset.theme = prefs.theme;
}
function applyLinesVisibility() {
  const overlay = document.getElementById("lines-overlay");
  if (overlay) overlay.style.display = prefs.lines ? "" : "none";
}
function applyPrefs() {
  applyTheme();
  applyLinesVisibility();
  renderGrid(state);
  requestAnimationFrame(() => redrawLines(state));
}
applyTheme();            // apply ASAP to avoid a flash before first render
applyLinesVisibility();

const connStateEl = document.getElementById("conn-state");
const sessionCountEl = document.getElementById("session-count");

let ws = null;
let reconnectDelay = 500;

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.addEventListener("open", () => {
    setConnState(true);
    reconnectDelay = 500;
  });
  ws.addEventListener("close", () => {
    setConnState(false);
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
      state.fadeoutSeconds = payload.fadeout_seconds ?? 30;
      state.wmctrlAvailable = !!payload.wmctrl_available;
      sessionCountEl.textContent = `${state.sessions.length} session${state.sessions.length === 1 ? "" : "s"}`;
      renderGrid(state);
      requestAnimationFrame(() => redrawLines(state));
      break;
    case "session": {
      const idx = state.sessions.findIndex((s) => s.session_id === payload.session_id);
      if (idx >= 0) state.sessions[idx] = payload;
      else state.sessions.push(payload);
      renderGrid(state);
      flashTilePreview(payload.session_id);
      requestAnimationFrame(() => redrawLines(state));
      break;
    }
    case "bus": {
      state.busTotal = payload.total ?? 0;
      state.busRecent = payload.recent || [];
      state.busTopology = payload.topology || { subscribers: {} };
      state.busPendingByTag = payload.pending_by_tag || {};
      state.busAdapter = payload.adapter || state.busAdapter;
      renderGrid(state);
      requestAnimationFrame(() => redrawLines(state));
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
      requestAnimationFrame(() => {
        redrawLines(state);
        // Markdown bus: source is a tag (e.g. "[backend]"). Animate that tag's
        // line back to the bus tile to visualize "this session sent a message".
        animateLineForTag(ev.source_session);
      });
      break;
    }
  }
}

// Resolve a tag (e.g. "[backend]") to the session_id it currently maps to,
// so lines.js (which keys lines by session_id) can find the right path.
function animateLineForTag(tag) {
  if (!tag) return;
  const match = state.sessions.find((s) => s.tag === tag);
  if (match) animateLineFor(match.session_id);
}

document.getElementById("reset-layout-btn").addEventListener("click", () => {
  resetLayout();
});

document.getElementById("refresh-btn").addEventListener("click", async () => {
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

document.getElementById("settings-btn").addEventListener("click", async () => {
  // Appearance from local prefs.
  setTheme.value = prefs.theme;
  setLines.checked = prefs.lines;
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
  .addEventListener("click", () => settingsModal.classList.add("hidden"));
settingsModal.addEventListener("click", (e) => {
  if (e.target === settingsModal) settingsModal.classList.add("hidden");
});

// Appearance prefs: apply + persist locally on change.
setTheme.addEventListener("change", () => { prefs.theme = setTheme.value; savePrefs(); applyTheme(); });
setLines.addEventListener("change", () => { prefs.lines = setLines.checked; savePrefs(); applyLinesVisibility(); });
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
document.getElementById("bus-modal-close").addEventListener("click", () => modal.classList.add("hidden"));
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

connect();
