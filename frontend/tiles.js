// tiles.js — render Claude session tiles + Bus tile.
//
// Layout model: each tile is absolutely positioned within #grid. Positions
// (per tile key) live in localStorage and survive re-renders. New tiles
// cascade into the next free slot in a virtual row-major grid.

import { redrawLines } from "/static/lines.js";

const POS_KEY = "conductor.positions.v1";
const MIN_KEY = "conductor.minimized.v1";

function loadMinimized() {
  try { return JSON.parse(localStorage.getItem(MIN_KEY) || "{}"); }
  catch { return {}; }
}
function saveMinimized() {
  try { localStorage.setItem(MIN_KEY, JSON.stringify(minimized)); } catch {}
}
// Set of minimized tile keys -> true. Minimized tiles drop out of the grid into
// the bottom dock; their bus wire is hidden (the dock chip isn't a .tile, so
// lines.js can't resolve it). State persists across restarts.
let minimized = loadMinimized();

function setMinimized(key, on) {
  if (on) minimized[key] = true; else delete minimized[key];
  saveMinimized();
  renderGrid(window.conductorState);
  requestAnimationFrame(() => redrawLines(window.conductorState));
}

const TILE_W   = 280;
const TILE_H   = 220;   // approximate; tiles can grow taller from content
const GAP      = 16;
const OFFSET_X = 20;
const OFFSET_Y = 20;
const DRAG_THRESHOLD = 4;  // px before a click becomes a drag

function loadPositions() {
  try { return JSON.parse(localStorage.getItem(POS_KEY) || "{}"); }
  catch { return {}; }
}
function savePositions(p) {
  try { localStorage.setItem(POS_KEY, JSON.stringify(p)); } catch {}
}

let positions = loadPositions();

// While a tile is being dragged we must NOT rebuild the grid: renderGrid does a
// full `innerHTML = ""` teardown, which would destroy the node mid-gesture
// (releasing pointer capture) and leave the drop unsaved — the tile then snaps
// back on the next periodic scan. So a drag defers any render until drop. The
// same applies to a resize gesture (native grip).
let isDragging = false;
let isResizing = false;
let renderPending = false;
let resizeIdleTimer = null;
let resizeSaveTimer = null;

// One observer for all tiles. Persists a tile's size only when the *user*
// resized it (the grip sets inline width, which our restore also sets — content
// growth never does), and freezes rebuilds for the duration of the gesture.
const tileResizeObserver = new ResizeObserver((entries) => {
  let changed = false;
  for (const entry of entries) {
    const el = entry.target;
    if (!el.style.width) continue;  // not user-resized / not restored
    const key = el.dataset.tileKey;
    if (!key) continue;
    const w = Math.round(el.offsetWidth);
    const h = Math.round(el.offsetHeight);
    const p = positions[key] || {};
    if (p.w !== w || p.h !== h) {
      positions[key] = { ...p, w, h };
      changed = true;
    }
  }
  if (!changed) return;
  // A real size change = an active resize gesture: freeze rebuilds, debounce the
  // save, and keep lines tracking the moving edge.
  isResizing = true;
  clearTimeout(resizeIdleTimer);
  resizeIdleTimer = setTimeout(() => {
    isResizing = false;
    if (renderPending) { renderPending = false; renderGrid(window.conductorState); }
  }, 250);
  clearTimeout(resizeSaveTimer);
  resizeSaveTimer = setTimeout(() => savePositions(positions), 200);
  redrawLines(window.conductorState);
});

function tileKeyForSession(s) { return `session:${s.session_id}`; }
const BUS_KEY = "bus:bus";

export function resetLayout() {
  positions = {};
  savePositions(positions);
  renderGrid(window.conductorState);
  requestAnimationFrame(() => redrawLines(window.conductorState));
}

function viewportCols() {
  return Math.max(1, Math.floor((window.innerWidth - 2 * OFFSET_X + GAP) / (TILE_W + GAP)));
}

function clampX(x) {
  const maxX = Math.max(OFFSET_X, window.innerWidth - TILE_W - OFFSET_X);
  return Math.min(Math.max(0, x), maxX);
}

// Find next free slot in row-major order that doesn't overlap any stored position.
function nextCascadeSlot() {
  const cols = viewportCols();
  const occupied = Object.values(positions);
  const minDx = (TILE_W + GAP) / 2;
  const minDy = (TILE_H + GAP) / 2;
  for (let row = 0; row < 200; row++) {
    for (let col = 0; col < cols; col++) {
      const x = OFFSET_X + col * (TILE_W + GAP);
      const y = OFFSET_Y + row * (TILE_H + GAP);
      const overlap = occupied.some(p => Math.abs(p.x - x) < minDx && Math.abs(p.y - y) < minDy);
      if (!overlap) return { x, y };
    }
  }
  return { x: OFFSET_X, y: OFFSET_Y };
}

function ensurePosition(key) {
  if (!positions[key]) {
    positions[key] = nextCascadeSlot();
    savePositions(positions);
  }
  return positions[key];
}

function applyPosition(tile, key) {
  const p = ensurePosition(key);
  tile.style.left = clampX(p.x) + "px";
  tile.style.top  = Math.max(0, p.y) + "px";
  // Restore a user-set size (if any). Tiles the user never resized stay
  // auto-height (CSS min-height); resized ones get an explicit box + scroll.
  if (p.w) tile.style.width = p.w + "px";
  if (p.h) tile.style.height = p.h + "px";
}

function updateGridExtent() {
  // Grow #grid's min-height so the body scroll covers the lowest tile.
  const grid = document.getElementById("grid");
  if (!grid) return;
  let maxBottom = 0;
  for (const child of grid.children) {
    const bottom = child.offsetTop + child.offsetHeight;
    if (bottom > maxBottom) maxBottom = bottom;
  }
  grid.style.minHeight = (maxBottom + OFFSET_Y) + "px";
}

export function renderGrid(state) {
  // Defer rebuilds during an active drag or resize; the gesture flushes it after.
  if (isDragging || isResizing) { renderPending = true; return; }
  const grid = document.getElementById("grid");
  tileResizeObserver.disconnect();

  // Always render the Bus tile; session tiles go to the grid unless minimized
  // (ended ones optional). Minimized sessions render as dock chips instead.
  const showEnded = window.conductorPrefs ? window.conductorPrefs.showEnded : true;
  const items = [];
  items.push({ key: BUS_KEY, render: () => busTile(state) });
  const dockSessions = [];
  for (const s of state.sessions) {
    if (!showEnded && s.status === "ended") continue;
    const key = tileKeyForSession(s);
    if (minimized[key]) dockSessions.push({ key, s });
    else items.push({ key, render: () => sessionTile(s, state) });
  }

  // Garbage-collect layout + minimized state for tiles that no longer exist.
  const liveKeys = new Set([...items.map(it => it.key), ...dockSessions.map(d => d.key)]);
  let mutated = false;
  for (const k of Object.keys(positions)) {
    if (!liveKeys.has(k)) { delete positions[k]; mutated = true; }
  }
  if (mutated) savePositions(positions);
  let minMutated = false;
  for (const k of Object.keys(minimized)) {
    if (!liveKeys.has(k)) { delete minimized[k]; minMutated = true; }
  }
  if (minMutated) saveMinimized();

  grid.innerHTML = "";
  for (const it of items) {
    const node = it.render();
    node.dataset.tileKey = it.key;
    grid.appendChild(node);
    applyPosition(node, it.key);
    wirePointerDrag(node, it.key);
    tileResizeObserver.observe(node);
  }

  // Bottom dock for minimized sessions.
  const dock = document.getElementById("dock");
  if (dock) {
    dock.innerHTML = "";
    for (const d of dockSessions) dock.appendChild(dockChip(d.s, d.key, state));
    document.body.classList.toggle("has-dock", dockSessions.length > 0);
  }
  updateGridExtent();
}

// A minimized session as a tiny dock chip: status dot + name + 📬, click to
// restore. Still live — renderGrid rebuilds the dock on every update.
function dockChip(s, key, state) {
  const pending = s.pending_count || 0;
  return el("div", {
    class: "dock-chip",
    title: `${s.title || "(untitled)"} · ${statusLabel(s.status)}`
      + (pending ? ` · 📬 ${pending}` : "") + "\nClick to restore",
    onclick: () => setMinimized(key, false),
  },
    el("span", { class: `status-dot ${s.status}`, title: statusLabel(s.status) }),
    el("span", { class: "dock-chip-name" }, s.title || "(untitled)"),
    pending ? el("span", { class: "dock-chip-badge" }, `📬${pending}`) : null,
  );
}

function statusLabel(status) {
  return {
    active: "active", warm: "warm", idle: "idle", dormant: "dormant",
    waiting: "waiting", ended: "ended",
  }[status] || status;
}

function ago(ts) {
  if (!ts) return "—";
  const sec = Math.max(0, Date.now() / 1000 - ts);
  if (sec < 1.5) return "just now";
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function el(tag, props = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "dataset") for (const [dk, dv] of Object.entries(v)) e.dataset[dk] = dv;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") e.innerHTML = v;
    else if (v !== undefined && v !== null) e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

function sessionTile(s, state) {
  const focusBtn = el("button", {
    class: "icon-btn",
    title: state.wmctrlAvailable ? "Focus terminal" : "wmctrl not installed",
    disabled: state.wmctrlAvailable ? null : "true",
    onclick: (e) => {
      e.stopPropagation();
      if (state.wmctrlAvailable) window.requestFocus(s.session_id);
    },
  }, "▶");

  const minimizeBtn = el("button", {
    class: "icon-btn",
    title: "Minimize to dock (keeps monitoring)",
    onclick: (e) => { e.stopPropagation(); setMinimized(tileKeyForSession(s), true); },
  }, "–");

  const pending = s.pending_count || 0;
  const guard = (window.conductorPrefs && window.conductorPrefs.busClickGuard) || "confirm-busy";
  const busy = s.status === "active" || s.status === "warm";
  const blocked = guard === "block-busy" && busy;
  const pendingBadge = pending > 0
    ? el("span", {
        class: blocked ? "pending-badge busy-blocked" : "pending-badge",
        title: blocked
          ? `${pending} unread — Claude is busy; injection disabled (Settings → Bus bubble click)`
          : `${pending} unread bus message(s) — click to run /msg-check in this Claude (raises its window)`,
        onclick: (e) => {
          e.stopPropagation();
          if (!blocked) window.requestCheck(s.session_id, s.status);
        },
      }, `📬 ${pending}`)
    : null;

  const busActive = (state.busActiveTags || []).includes(s.tag);
  const tagChip = s.tag
    ? el("span", {
        class: `tag-chip bus-toggle ${busActive ? "bus-active" : "bus-passive"}`,
        title: busActive
          ? `${s.tag} · Active — auto-notified of new bus messages (gets broadcasts). Click to make Passive.`
          : `${s.tag} · Passive — can send/read manually but won't get broadcasts. Click to make Active.`,
        onclick: (e) => { e.stopPropagation(); window.toggleBusActive(s.tag, !busActive); },
      }, s.tag)
    : null;

  const tile = el("div", {
    class: `tile status-${s.status}` + (s.status === "ended" ? " fading-out" : ""),
    dataset: { sessionId: s.session_id, projectDir: s.project_dir, tag: s.tag || "" },
    ondblclick: () => {
      if (state.wmctrlAvailable) window.requestFocus(s.session_id);
    },
  },
    el("div", { class: "tile-header" },
      el("div", { class: "tile-title-wrap" },
        el("span", { class: `status-dot ${s.status}`, title: statusLabel(s.status) }),
        el("span", { class: "tile-title", title: s.title || "" }, s.title || "(untitled)"),
      ),
      el("div", { class: "tile-actions" }, pendingBadge, focusBtn, minimizeBtn),
    ),
    el("div", { class: "tile-projectdir", title: s.project_dir },
      tagChip, tagChip ? " " : null, s.project_dir,
    ),
    el("div", { class: "tile-preview" }, s.preview || ""),
    el("div", { class: "tile-footer" },
      el("span", {}, `msgs: ${s.message_count}`),
      el("span", {}, `⏱ ${ago(s.last_activity_at)}`),
    ),
  );

  if (s.status === "ended") {
    requestAnimationFrame(() => tile.classList.add("fading"));
  }
  return tile;
}

function busTile(state) {
  const total = state.busTotal || 0;
  const pendingByTag = state.busPendingByTag || {};
  // Split pending into "active" (tags with a live tile right now) vs the full
  // backlog (includes dormant tags like a frontend session not launched in days).
  const activeTags = new Set(
    (state.sessions || []).filter((s) => s.status !== "ended" && s.tag).map((s) => s.tag),
  );
  let activePending = 0;
  let allPending = 0;
  for (const [tag, n] of Object.entries(pendingByTag)) {
    const c = n || 0;
    allPending += c;
    if (activeTags.has(tag)) activePending += c;
  }
  const pendingTitle = `${activePending} unread for active sessions`
    + (allPending > activePending ? ` · ${allPending} total incl. dormant tags` : "");
  const recentItems = (state.busRecent || []).slice(-5).reverse().map((ev) => {
    const t = new Date(ev.timestamp * 1000).toLocaleTimeString();
    const body = ev.payload_summary || "";
    return `${t} ${ev.source_session}: ${body}`;
  });
  const previewText = recentItems.length ? recentItems.join("\n") : "no events yet";
  const adapter = state.busAdapter || "markdown";

  return el("div", {
    class: "tile bus-tile",
    dataset: { busTile: "1" },
    onclick: (e) => {
      // Only open modal on a plain click — not the end of a drag (handled in pointerup).
      if (e.target.closest("button, .pending-badge")) return;
      if (!tileWasDragged) window.openBusModal();
    },
  },
    el("div", { class: "tile-header" },
      el("div", { class: "tile-title-wrap" },
        el("span", { class: "status-dot active" }),
        el("span", { class: "tile-title" }, "Bus",
          el("span", { class: "bus-badge msgs", title: `${total} messages on the bus` }, `📨 ${total}`),
          activePending > 0
            ? el("span", { class: "bus-badge pending", title: pendingTitle }, `📬 ${activePending}`)
            : null,
        ),
      ),
    ),
    el("div", { class: "tile-projectdir" }, `claude-bus · ${adapter}`),
    el("div", { class: "tile-preview" }, previewText),
    el("div", { class: "tile-footer" },
      el("span", { title: "all unread across every tag, including dormant ones" },
        `${allPending} unread`),
      el("span", {}, `tags: ${Object.keys(state.busTopology?.subscribers || {}).length}`),
    ),
  );
}

// --- Pointer-based drag -----------------------------------------------------
// Uses pointer events with a small movement threshold so simple clicks (and
// double-clicks for focus) still work. Updates lines.js in real time as you
// drag so the SVG connections track the tile.

let tileWasDragged = false; // read by bus-tile onclick to suppress modal-after-drag

function wirePointerDrag(tile, key) {
  let pointerId = null;
  let startX = 0, startY = 0;
  let origX  = 0, origY  = 0;
  let dragging = false;

  tile.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (e.target.closest("button, .pending-badge, .bus-toggle")) return;
    // Bottom-right ~18px is the native resize grip — let the browser handle it
    // instead of starting a tile drag.
    const r = tile.getBoundingClientRect();
    if (e.clientX > r.right - 18 && e.clientY > r.bottom - 18) return;
    pointerId = e.pointerId;
    startX = e.clientX; startY = e.clientY;
    origX = parseFloat(tile.style.left) || 0;
    origY = parseFloat(tile.style.top)  || 0;
    dragging = false;
    tileWasDragged = false;
    tile.setPointerCapture(pointerId);
  });

  tile.addEventListener("pointermove", (e) => {
    if (e.pointerId !== pointerId) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!dragging && (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD)) {
      dragging = true;
      isDragging = true;  // freeze grid rebuilds for the duration of the drag
      tile.classList.add("dragging");
      tile.style.zIndex = "100";
    }
    if (dragging) {
      tile.style.left = (origX + dx) + "px";
      tile.style.top  = Math.max(0, origY + dy) + "px";
      redrawLines(window.conductorState);
    }
  });

  function endPointer(e) {
    if (e.pointerId !== pointerId) return;
    if (dragging) {
      const x = parseFloat(tile.style.left) || 0;
      const y = parseFloat(tile.style.top)  || 0;
      // Merge, don't overwrite — preserve any persisted size (w/h) from a resize,
      // otherwise dragging a resized tile drops its size and it snaps back.
      positions[key] = { ...positions[key], x, y };
      savePositions(positions);
      tile.classList.remove("dragging");
      tile.style.zIndex = "";
      tileWasDragged = true;
      updateGridExtent();
      redrawLines(window.conductorState);
      // Let click-suppression flag reset after the click event fires.
      setTimeout(() => { tileWasDragged = false; }, 0);
    }
    try { tile.releasePointerCapture(pointerId); } catch {}
    pointerId = null;
    dragging = false;
    // Drag over: unfreeze and flush any render that arrived while dragging, so
    // the grid catches up on session/bus updates it skipped.
    isDragging = false;
    if (renderPending) {
      renderPending = false;
      renderGrid(window.conductorState);
      requestAnimationFrame(() => redrawLines(window.conductorState));
    }
  }
  tile.addEventListener("pointerup", endPointer);
  tile.addEventListener("pointercancel", endPointer);
}

// Re-clamp positions on viewport resize so tiles don't sit fully off-screen.
window.addEventListener("resize", () => {
  for (const child of document.querySelectorAll("#grid > .tile")) {
    const key = child.dataset.tileKey;
    if (!key || !positions[key]) continue;
    child.style.left = clampX(positions[key].x) + "px";
  }
  updateGridExtent();
});

// --- helpers exposed for app.js ---------------------------------------------

export function flashTilePreview(sessionId) {
  const node = document.querySelector(`.tile[data-session-id="${CSS.escape(sessionId)}"] .tile-preview`);
  if (!node) return;
  node.style.transition = "background-color 0.5s";
  node.style.backgroundColor = "rgba(63, 185, 80, 0.18)";
  setTimeout(() => { node.style.backgroundColor = ""; }, 500);
}

export function fadeOutSession(sessionId) {
  const node = document.querySelector(`.tile[data-session-id="${CSS.escape(sessionId)}"]`);
  if (node) node.classList.add("fading");
}
