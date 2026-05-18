// app.js — WebSocket client + top-level state. Delegates rendering to tiles.js / lines.js.

import { renderGrid, flashTilePreview, fadeOutSession } from "/static/tiles.js";
import { redrawLines, animateLineFor } from "/static/lines.js";

const state = {
  sessions: [],     // SessionRecord[]
  skippy: [],       // SkippyTile[]
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
      state.skippy = payload.skippy || [];
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

window.requestCheck = async function requestCheck(sessionId) {
  try {
    const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/check`, { method: "POST" });
    if (!r.ok) {
      console.warn("check failed", r.status);
      return;
    }
    // Server already broadcasts the updated session record; nothing else to do.
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
