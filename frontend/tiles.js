// tiles.js — render Claude session tiles + Bus tile.
//
// Layout model: each tile is absolutely positioned within #grid. Positions
// (per tile key) live in localStorage and survive re-renders. New tiles
// cascade into the next free slot in a virtual row-major grid.

import { redrawLines } from "/static/lines.js";

// v2: tiles are keyed by project dir (stable across reboots) instead of the
// session's ephemeral UUID — so layout/groups survive even fresh sessions. The
// bump abandons the old UUID-keyed data rather than mixing schemes.
const POS_KEY = "conductor.positions.v2";
const MIN_KEY = "conductor.minimized.v2";

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

// --- Dormant dock (parked sessions) -----------------------------------------
// Offline sessions Kyle has dismissed from the dormant dock, keyed by their real
// cwd (project_dir). "Auto + dismiss": every parked session shows by default; an
// X hides it. A dismissal is auto-cleared once a live session runs in that folder
// again, so a session you actually return to reappears when it next parks.
const PARKED_DISMISS_KEY = "conductor.parkedDismissed.v1";
function loadDismissed() {
  try { return JSON.parse(localStorage.getItem(PARKED_DISMISS_KEY) || "{}"); }
  catch { return {}; }
}
function saveDismissed() {
  try { localStorage.setItem(PARKED_DISMISS_KEY, JSON.stringify(dismissedParked)); } catch {}
}
let dismissedParked = loadDismissed();

function dismissParked(projectDir) {
  dismissedParked[projectDir] = true;
  saveDismissed();
  renderGrid(window.conductorState);
}

// --- Groups (per-tile assignment; logical/color-only) -----------------------
// A group is a named, colored set of tile keys. Membership is assigned one tile
// at a time via each tile's ▦ menu (no canvas multi-select). A tile is in at
// most one group. Collapsing a group folds its members into one dock chip.
const GROUPS_KEY = "conductor.groups.v2";
const GROUP_PALETTE = [
  "#e06c75", "#e5c07b", "#98c379", "#56b6c2", "#61afef", "#c678dd", "#d19a66", "#ff79c6",
];
function loadGroups() {
  try { return JSON.parse(localStorage.getItem(GROUPS_KEY) || "{}"); }
  catch { return {}; }
}
function saveGroups() {
  try { localStorage.setItem(GROUPS_KEY, JSON.stringify(groups)); } catch {}
}
let groups = loadGroups();

// One-time repair: older builds assigned colors by group count, which could
// collide after create/delete. Reassign duplicates to the first unused color.
(function dedupeGroupColors() {
  const used = new Set();
  let changed = false;
  for (const g of Object.values(groups)) {
    if (used.has(g.color)) {
      const c = GROUP_PALETTE.find((x) => !used.has(x));
      if (c) { g.color = c; changed = true; }
    }
    used.add(g.color);
  }
  if (changed) saveGroups();
})();

function groupForKey(key) {
  for (const g of Object.values(groups)) if (g.members.includes(key)) return g;
  return null;
}
function rerenderGroups() {
  renderGrid(window.conductorState);
  requestAnimationFrame(() => redrawLines(window.conductorState));
}
function nextGroupColor() {
  // First palette color not already in use, so groups stay visually distinct
  // (count-based indexing collides after create/delete). Falls back to cycling
  // once all are used.
  const used = new Set(Object.values(groups).map((g) => g.color));
  return GROUP_PALETTE.find((c) => !used.has(c))
    || GROUP_PALETTE[Object.keys(groups).length % GROUP_PALETTE.length];
}
function newGroupFrom(key, name) {
  const id = "g" + Date.now().toString(36);
  const n = Object.keys(groups).length;
  for (const g of Object.values(groups)) g.members = g.members.filter((k) => k !== key);
  groups[id] = {
    id,
    name: (name && name.trim()) || `Group ${n + 1}`,
    color: nextGroupColor(),
    members: [key],
    collapsed: false,
  };
  saveGroups();
  rerenderGroups();
  return groups[id];
}
// Prompt for a name, then create. Cancel aborts; blank keeps the default.
function promptNewGroup(key) {
  const def = `Group ${Object.keys(groups).length + 1}`;
  const nm = window.prompt("Name the new group:", def);
  if (nm === null) return;  // cancelled
  newGroupFrom(key, nm);
}
function addToGroup(key, id) {
  if (!groups[id]) return;
  for (const g of Object.values(groups)) g.members = g.members.filter((k) => k !== key);
  groups[id].members.push(key);
  saveGroups();
  rerenderGroups();
}
function removeFromGroup(key) {
  for (const g of Object.values(groups)) g.members = g.members.filter((k) => k !== key);
  saveGroups();
  rerenderGroups();  // empty groups are GC'd in renderGrid
}
export function getGroups() { return Object.values(groups); }
export function renameGroup(id, name) { if (groups[id]) { groups[id].name = name; saveGroups(); rerenderGroups(); } }
export function recolorGroup(id, color) { if (groups[id]) { groups[id].color = color; saveGroups(); rerenderGroups(); } }
export function deleteGroup(id) { delete groups[id]; saveGroups(); rerenderGroups(); }
export function setGroupCollapsed(id, on) { if (groups[id]) { groups[id].collapsed = !!on; saveGroups(); rerenderGroups(); } }
export const GROUP_COLORS = GROUP_PALETTE;

// Lightweight popup menu anchored to a tile's ▦ button. Closed before any group
// mutation (which re-renders), so it never gets destroyed mid-action.
let tileMenuEl = null;
function closeTileMenu() {
  if (!tileMenuEl) return;
  tileMenuEl.remove();
  tileMenuEl = null;
  document.removeEventListener("pointerdown", onDocDownForMenu, true);
}
function onDocDownForMenu(e) {
  if (tileMenuEl && !tileMenuEl.contains(e.target)) closeTileMenu();
}
function openTileMenu(anchor, key) {
  closeTileMenu();
  const g = groupForKey(key);
  const menu = document.createElement("div");
  menu.className = "tile-menu";
  const addItem = (label, fn, color) => {
    const it = document.createElement("button");
    it.className = "tile-menu-item";
    if (color) {
      const sw = document.createElement("span");
      sw.className = "tile-menu-swatch";
      sw.style.background = color;
      it.appendChild(sw);
    }
    it.appendChild(document.createTextNode(label));
    it.addEventListener("click", (e) => { e.stopPropagation(); closeTileMenu(); fn(); });
    menu.appendChild(it);
  };
  const addSep = (label) => {
    const d = document.createElement("div");
    d.className = "tile-menu-sep";
    d.textContent = label;
    menu.appendChild(d);
  };
  if (g) {
    addSep(g.name);
    addItem("Rename group", () => {
      const nm = window.prompt("Rename group:", g.name);
      if (nm && nm.trim()) renameGroup(g.id, nm.trim());
    });
    addItem("Minimize group", () => setGroupCollapsed(g.id, true));
    addItem("Remove from group", () => removeFromGroup(key));
    addItem("Delete group", () => deleteGroup(g.id));
    const others = Object.values(groups).filter((x) => x.id !== g.id);
    if (others.length) {
      addSep("Move to");
      others.forEach((x) => addItem(x.name, () => addToGroup(key, x.id), x.color));
    }
    addItem("＋ New group", () => promptNewGroup(key));
  } else {
    addItem("＋ New group from this", () => promptNewGroup(key));
    const all = Object.values(groups);
    if (all.length) {
      addSep("Add to");
      all.forEach((x) => addItem(x.name, () => addToGroup(key, x.id), x.color));
    }
  }
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  const left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
  menu.style.top = `${Math.round(r.bottom + 4)}px`;
  menu.style.left = `${Math.round(Math.max(8, left))}px`;
  tileMenuEl = menu;
  // Defer so the click that opened it doesn't immediately close it.
  setTimeout(() => document.addEventListener("pointerdown", onDocDownForMenu, true), 0);
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

// --- Retirement policy for the positions map --------------------------------
// v1.5 deliberately keeps a tile's position after its session goes away, so a
// layout survives a reboot. Correct — but it was written with no upper bound, so
// the map grows with every project dir ever opened (69 on this box) and that
// unbounded growth is what pushed a new tile ~1672 px off the bottom of the board.
//
// The fix is a policy, not amnesia: a position is kept while you still touch that
// project, and retired only after RETIRE_DAYS of never appearing on the board.
// Entries predating this policy carry no stamp — they are STAMPED, never deleted,
// so upgrading can't silently eat a layout you spent time on.
const RETIRE_DAYS = 45;
const POS_HARD_CAP = 250;          // backstop; evicts least-recently-seen first

function retireStalePositions(liveKeys) {
  const now = Date.now();
  const cutoff = now - RETIRE_DAYS * 86400000;
  let changed = false;
  for (const [k, p] of Object.entries(positions)) {
    if (!p || typeof p !== "object") { delete positions[k]; changed = true; continue; }
    if (liveKeys.has(k)) continue;                 // on the board right now
    if (typeof p.seen !== "number") { p.seen = now; changed = true; continue; }  // grace
    if (p.seen < cutoff) { delete positions[k]; changed = true; }
  }
  const entries = Object.entries(positions);
  if (entries.length > POS_HARD_CAP) {
    entries.sort((a, b) => (a[1].seen || 0) - (b[1].seen || 0));
    for (const [k] of entries.slice(0, entries.length - POS_HARD_CAP)) {
      if (!liveKeys.has(k)) { delete positions[k]; changed = true; }
    }
  }
  if (changed) savePositions(positions);
}

function stampSeen(liveKeys) {
  const now = Date.now();
  let changed = false;
  for (const k of liveKeys) {
    const p = positions[k];
    // Only re-stamp once a day: this runs on every render and localStorage writes
    // are synchronous, so stamping per-render would put a JSON serialise of the
    // whole map on the render path ~every 3 s.
    if (p && (typeof p.seen !== "number" || now - p.seen > 86400000)) {
      p.seen = now; changed = true;
    }
  }
  if (changed) savePositions(positions);
}

// Reconciliation registry. renderGrid reuses the SAME outer .tile node per key
// across renders instead of `innerHTML = ""` teardown + rebuild. Preserving node
// identity means a running CSS transition (the end-fade), the attached drag
// handlers, and the resize observer all survive a re-render. The old teardown
// recreated every tile on each WS update, which restarted the ended tile's
// opacity transition from 1 — so when several sessions tore down at once the
// burst of updates made ended tiles blink ~10× before finally disappearing.
const tileNodes = new Map();   // tile key -> outer .tile element (persists across renders)
// Keys whose end-fade has already played. A re-render mid-fade renders the node
// already-.fading (opacity 0) instead of snapping back to 1 and replaying it.
const fadedKeys = new Set();

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

// Key by project dir, not the session's ephemeral jsonl UUID, so a session in
// the same dir reclaims its saved position/size/group across restarts/reboots
// (the scanner already enforces one session per project dir).
function tileKeyForSession(s) { return `proj:${s.project_dir}`; }
const BUS_KEY = "bus:bus";

export function resetLayout() {
  positions = {};
  savePositions(positions);
  // Hard rebuild: drop the reused nodes so every tile re-cascades from a clean
  // slate (in-place reuse would otherwise keep each node's old inline left/top).
  for (const node of tileNodes.values()) tileResizeObserver.unobserve(node);
  tileNodes.clear();
  const grid = document.getElementById("grid");
  if (grid) grid.innerHTML = "";
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

function viewportRows() {
  return Math.max(1, Math.floor((window.innerHeight - 2 * OFFSET_Y + GAP) / (TILE_H + GAP)));
}

// Keys with a tile actually on the board right now. Maintained by renderGrid so
// nextCascadeSlot() can collide against what's VISIBLE rather than what's merely
// remembered. Empty until the first render, which is fine — an empty occupied set
// just means the first tile goes to the origin.
let liveTileKeys = new Set();
let rescuedOffBoard = false;

// A position is provably AUTO-placed when it sits exactly on the cascade grid;
// anything dragged by hand lands on an arbitrary pixel. That lets us tell "the
// cascade put this here" from "Kyle put this here" and only ever touch the former.
function isCascadeGridPoint(p) {
  if (!p || typeof p.x !== "number" || typeof p.y !== "number") return false;
  const dx = p.x - OFFSET_X, dy = p.y - OFFSET_Y;
  return dx >= 0 && dy >= 0 && dx % (TILE_W + GAP) === 0 && dy % (TILE_H + GAP) === 0;
}

// One-time rescue for tiles the old runaway cascade parked off the bottom of the
// board. Those tiles were reachable only by scrolling ~2 screens down, which reads
// exactly like "my new session never showed up". We drop only positions that are
// BOTH off-screen AND on the cascade grid, so a layout that was actually arranged
// by hand — including tiles deliberately parked low on a tall board — is untouched.
function rescueOffBoardAutoPositions() {
  const maxY = OFFSET_Y + Math.max(0, viewportRows() - 1) * (TILE_H + GAP);
  let changed = false;
  for (const [k, p] of Object.entries(positions)) {
    if (p && p.y > maxY && isCascadeGridPoint(p)) { delete positions[k]; changed = true; }
  }
  if (changed) savePositions(positions);
}

// Find the next free slot in row-major order.
//
// This used to collide against `Object.values(positions)` — every position ever
// stored. But positions are deliberately never GC'd (see renderGrid) so a layout
// survives a session going away and coming back, which means the map grows with
// every project dir ever opened — 69 on this box. A new tile then had to clear ALL
// of them and got cascaded past the bottom of the board: present, positioned, and
// invisible. Colliding against only the tiles actually ON the board fixes that at
// the source, and the row bound guarantees it even if the map is stale.
function nextCascadeSlot() {
  const cols = viewportCols();
  const rows = viewportRows();
  const occupied = [];
  for (const [k, p] of Object.entries(positions)) if (liveTileKeys.has(k)) occupied.push(p);
  const minDx = (TILE_W + GAP) / 2;
  const minDy = (TILE_H + GAP) / 2;
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const x = OFFSET_X + col * (TILE_W + GAP);
      const y = OFFSET_Y + row * (TILE_H + GAP);
      const overlap = occupied.some(p => Math.abs(p.x - x) < minDx && Math.abs(p.y - y) < minDy);
      if (!overlap) return { x, y };
    }
  }
  // Board genuinely full: stack a small diagonal near the origin rather than
  // marching off-screen. Overlapping-and-visible beats tidy-and-unreachable — the
  // user can drag it, which they cannot do to a tile they can't find.
  const n = occupied.length;
  return { x: OFFSET_X + (n % 8) * 28, y: OFFSET_Y + (n % 8) * 28 };
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
  updateTokenTotal(state);   // global token line by the title
  updateWaitingTotal(state); // "N waiting" coordination indicator
  const grid = document.getElementById("grid");

  // Always render the Bus tile; session tiles go to the grid unless minimized
  // (ended ones optional). Minimized sessions render as dock chips instead.
  const showEnded = window.conductorPrefs ? window.conductorPrefs.showEnded : true;

  // Index live sessions by tile key (preserves state.sessions order; the scanner
  // already enforces one session per project dir, so keys are unique).
  const sessionByKey = {};
  const allSessionKeys = [];
  for (const s of state.sessions) {
    if (!showEnded && s.status === "ended") continue;
    const key = tileKeyForSession(s);
    if (!(key in sessionByKey)) allSessionKeys.push(key);
    sessionByKey[key] = s;
  }

  // Forget fade markers for keys that are gone or no longer ended, so a session
  // that restarts (or a tile that's GC'd then returns) animates its next end.
  for (const k of [...fadedKeys]) {
    const s = sessionByKey[k];
    if (!s || s.status !== "ended") fadedKeys.delete(k);
  }

  // No GC of offline tiles: positions/sizes/groups are keyed by project dir and
  // kept even when a session isn't running, so they restore when it returns
  // (across reboots, or if you open the board before starting sessions). Cleanup
  // is user-driven: "Reset layout", Ungroup, or Remove from group.
  // Exception: drop truly-empty groups (all members removed) so removing the
  // last member clears the group — offline members (members.length > 0) stay.
  let groupsMutated = false;
  for (const g of Object.values(groups)) {
    if (g.members.length === 0) { delete groups[g.id]; groupsMutated = true; }
  }
  if (groupsMutated) saveGroups();

  // Collapsed groups fold their members into a single group dock chip.
  const collapsedGroups = Object.values(groups).filter((g) => g.collapsed);
  const collapsedMembers = new Set(collapsedGroups.flatMap((g) => g.members));

  // Desired grid items in order: Bus tile first, then non-minimized,
  // non-collapsed session tiles. (Tiles are absolutely positioned, so DOM order
  // is cosmetic — new nodes just append.)
  const items = [{ key: BUS_KEY, kind: "bus" }];
  for (const res of (state.resources && state.resources.resources) || [])
    items.push({ key: "res:" + res.name, kind: "resource", res });
  for (const svc of (state.services && state.services.services) || [])
    items.push({ key: "svc:" + svc.name, kind: "service", svc });
  const dockSessions = [];
  for (const key of allSessionKeys) {
    if (collapsedMembers.has(key)) continue;
    const s = sessionByKey[key];
    if (minimized[key]) dockSessions.push({ key, s });
    else items.push({ key, kind: "session", s });
  }

  // Reconcile: keep nodes whose key still wants a grid tile, drop the rest,
  // create the new ones. No full teardown — reused nodes keep their identity.
  const wantKeys = new Set(items.map((it) => it.key));
  // Publish the on-board key set BEFORE any applyPosition() below, so a new tile
  // placed this pass collides against the live board rather than every remembered
  // project. Deferred to first render so the viewport is laid out when we measure.
  liveTileKeys = wantKeys;
  if (!rescuedOffBoard) {
    rescuedOffBoard = true;
    rescueOffBoardAutoPositions();
    retireStalePositions(wantKeys);   // once per load: bound the map (see RETIRE_DAYS)
  }
  stampSeen(wantKeys);                // keeps a project's slot alive while you use it
  for (const [k, node] of tileNodes) {
    if (!wantKeys.has(k)) {
      tileResizeObserver.unobserve(node);
      node.remove();
      tileNodes.delete(k);
    }
  }
  for (const it of items) {
    let node = tileNodes.get(it.key);
    const isNew = !node;
    if (isNew) {
      node = it.kind === "bus" ? createBusShell()
           : it.kind === "resource" ? createResShell()
           : it.kind === "service" ? createSvcShell()
           : createSessionShell();
      node.dataset.tileKey = it.key;
      tileNodes.set(it.key, node);
    }
    if (it.kind === "bus") fillBusTile(node, state);
    else if (it.kind === "resource") fillResourceTile(node, it.res);
    else if (it.kind === "service") fillServiceTile(node, it.svc);
    else fillSessionTile(node, it.s, state);
    if (isNew) {
      grid.appendChild(node);
      applyPosition(node, it.key);
      wirePointerDrag(node, it.key);
      tileResizeObserver.observe(node);
    }
  }

  // Parked (offline, relaunchable) sessions for the dormant dock. The backend
  // already excludes cwds with a live session; we also auto-clear a dismissal
  // once its folder is live again (so a session you return to reappears later),
  // then hide anything still dismissed.
  const liveDirs = new Set(state.sessions.map((s) => s.project_dir));
  let dismissChanged = false;
  for (const dir of Object.keys(dismissedParked)) {
    if (liveDirs.has(dir)) { delete dismissedParked[dir]; dismissChanged = true; }
  }
  if (dismissChanged) saveDismissed();
  const parked = (state.parked || []).filter(
    (p) => !dismissedParked[p.project_dir] && !liveDirs.has(p.project_dir),
  );

  // Bottom dock: collapsed groups (one chip each) + individually minimized tiles
  // + parked sessions (with a divider before them).
  const dock = document.getElementById("dock");
  if (dock) {
    dock.innerHTML = "";
    for (const g of collapsedGroups) dock.appendChild(groupChip(g, sessionByKey, state));
    for (const d of dockSessions) dock.appendChild(dockChip(d.s, d.key, state));
    if (parked.length) {
      if (collapsedGroups.length || dockSessions.length) {
        dock.appendChild(el("span", { class: "dock-divider" }));
      }
      dock.appendChild(el("span", { class: "dock-label", title: "Closed sessions with saved history — click to relaunch (claude --continue + /rc)" }, "💤 Dormant"));
      for (const p of parked) dock.appendChild(parkedChip(p));
    }
    document.body.classList.toggle(
      "has-dock",
      collapsedGroups.length > 0 || dockSessions.length > 0 || parked.length > 0,
    );
  }
  updateGridExtent();

  // fillSessionTile rewrites tile.className wholesale, which wipes the link-mode /
  // autonomy classes on every render (the board re-renders every few seconds, so a
  // green selection would silently fade). Let app.js re-apply them after each pass.
  if (window.applyLinkClasses) window.applyLinkClasses();
}

// A collapsed group as one dock chip: color swatch + name + rollup (member
// count, any active, total 📬). Click to expand the whole group.
function groupChip(g, sessionByKey) {
  const members = g.members.map((k) => sessionByKey[k]).filter(Boolean);
  const activeCount = members.filter((s) => s.status === "active" || s.status === "warm").length;
  const pending = members.reduce((n, s) => n + (s.pending_count || 0), 0);
  return el("div", {
    class: "dock-chip group-chip",
    style: `--group-color: ${g.color}`,
    title: `${g.name} · ${members.length} session(s)`
      + (activeCount ? ` · ${activeCount} active` : "")
      + (pending ? ` · 📬 ${pending}` : "") + "\nClick to expand",
    onclick: () => setGroupCollapsed(g.id, false),
  },
    el("span", { class: "group-swatch" }),
    el("span", { class: "dock-chip-name" }, g.name),
    el("span", { class: "group-count" }, `${members.length}`),
    activeCount ? el("span", { class: "status-dot active", title: `${activeCount} active` }) : null,
    pending ? el("span", { class: "dock-chip-badge" }, `📬${pending}`) : null,
  );
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

// A parked (offline) session as a dormant-dock chip: 💤 + name + tag + "last
// seen" age, click to relaunch (claude --continue in its folder, then /rc), with
// a trailing ✕ to dismiss. Once relaunched, the new live session removes it from
// the parked list on the next scan, so the chip disappears on its own.
function parkedChip(p) {
  const chip = el("div", {
    class: "dock-chip parked-chip",
    title: `${p.title || p.tag} · ${p.tag}\nlast active ${ago(p.last_activity_at)}`
      + `\n${p.project_dir}\nClick to relaunch (claude --continue + /rc)`,
    onclick: (ev) => {
      // Ignore clicks on the ✕ (handled by its own onclick + stopPropagation).
      if (chip.classList.contains("launching")) return;
      chip.classList.add("launching");
      chip.querySelector(".parked-name").textContent = "launching…";
      window.requestRelaunch(p.project, p.project_dir);
    },
  },
    el("span", { class: "parked-icon" }, "💤"),
    el("span", { class: "dock-chip-name parked-name" }, p.title || p.tag || "(untitled)"),
    el("span", { class: "parked-tag" }, p.tag || ""),
    el("button", {
      class: "parked-dismiss",
      title: "Dismiss (hide from dormant dock)",
      onclick: (ev) => { ev.stopPropagation(); dismissParked(p.project_dir); },
    }, "✕"),
  );
  return chip;
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

// Compact token count: 1_530_879 -> "1.5M", 482_000_000 -> "482M".
function humanTok(n) {
  n = n || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}
function tokenTooltip(t) {
  const c = (n) => (n || 0).toLocaleString();
  return `Tokens over ${c(t.turns)} turns:\n`
    + `  output generated: ${c(t.output)}\n`
    + `  new input: ${c(t.input)}\n`
    + `  cache creation: ${c(t.cache_creation)}\n`
    + `  cache reads: ${c(t.cache_read)}  (context re-read each turn — cheap)\n`
    + `  ── total processed: ${c(t.total)}`;
}
// "N waiting" — sessions with unread messages addressed to them (auto-delivered
// when idle). Lets Kyle see coordination backlog at a glance without hopping tiles.
function updateWaitingTotal(state) {
  const elm = document.getElementById("waiting-total");
  if (!elm) return;
  const waiting = (state.sessions || []).filter((s) => (s.pending_directed || 0) > 0);
  if (!waiting.length) { elm.textContent = ""; elm.title = ""; return; }
  elm.textContent = `📨 ${waiting.length} waiting`;
  elm.title = "Sessions with messages addressed to them (idle ones are auto-woken to read):\n"
    + waiting.map((s) => `  ${s.tag || s.name} ← ${(s.pending_directed_from || []).join(", ") || "?"}`).join("\n");
}

// Global token total across every session on the board, shown by the title.
function updateTokenTotal(state) {
  const elm = document.getElementById("token-total");
  if (!elm) return;
  let out = 0, total = 0, turns = 0, any = false;
  for (const s of state.sessions || []) {
    if (s.tokens && s.tokens.turns) {
      out += s.tokens.output || 0; total += s.tokens.total || 0; turns += s.tokens.turns; any = true;
    }
  }
  elm.textContent = any ? `tokens: ${humanTok(out)} out · ${humanTok(total)} total` : "";
  if (any) elm.title = `All ${(state.sessions || []).filter((s) => s.tokens && s.tokens.turns).length} sessions on the board, ${turns.toLocaleString()} turns\n`
    + `output generated: ${out.toLocaleString()}\ntotal processed: ${total.toLocaleString()} (mostly cheap cache re-reads)`;
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

// The outer .tile node is created once per key and reused across renders. Its
// dblclick handler reads the LIVE session from node.__sess (refreshed on every
// fill) rather than closing over one — so a restarted session (new ephemeral
// session_id, same project dir) still focuses the right terminal.
function createSessionShell() {
  const tile = el("div", { class: "tile" });
  tile.addEventListener("dblclick", () => {
    const s = tile.__sess;
    if (s && window.conductorState && window.conductorState.wmctrlAvailable) {
      window.requestFocus(s.session_id);
    }
  });
  return tile;
}

// Update a session tile in place: refresh class/style/dataset and rebuild its
// inner content on the existing node. The node identity is preserved so the
// end-fade transition, drag handlers and resize observer all survive.
// Member-role selector (v4 §3.4). A tiny <select> on the tile: Observer (read-only) / Service /
// Peer (default) / Trusted. Changing it POSTs to /api/members/<member>/role; the referee enforces on
// the session's next tool call. stopPropagation so picking a role never triggers the tile's
// drag/focus handlers. Rebuilt from state on every render (never painted-and-hoped) — the v2.24.3 rule.
const MEMBER_ROLES = ["observer", "service", "peer", "trusted"];
function roleSelect(s) {
  if (!s.member) return null;
  const cur = s.role || "peer";
  const sel = el("select", {
    class: "tile-role role-" + cur,
    title: "member role — observer: read-only · service · peer: default (=today) · trusted: self-approve window",
    onclick: (e) => e.stopPropagation(),
    onchange: (e) => { e.stopPropagation(); window.setMemberRole(s.member, e.target.value); },
  }, ...MEMBER_ROLES.map((r) =>
    el("option", r === cur ? { value: r, selected: "selected" } : { value: r }, r)));
  sel.value = cur;
  return sel;
}

function fillSessionTile(tile, s, state) {
  const key = tileKeyForSession(s);
  const group = groupForKey(key);
  tile.__sess = s;

  const focusBtn = el("button", {
    class: "icon-btn",
    title: state.wmctrlAvailable ? "Focus terminal" : "wmctrl not installed",
    disabled: state.wmctrlAvailable ? null : "true",
    onclick: (e) => {
      e.stopPropagation();
      if (state.wmctrlAvailable) window.requestFocus(s.session_id);
    },
  }, "▶");

  // ▦ opens the group menu (assign / move / remove / minimize group). Colored
  // when the tile is in a group.
  const groupBtn = el("button", {
    class: "icon-btn group-btn",
    style: group ? `color: ${group.color}` : null,
    title: group ? `Group “${group.name}” — manage / minimize` : "Add to a group",
    onclick: (e) => { e.stopPropagation(); openTileMenu(e.currentTarget, key); },
  }, "▦");

  const minimizeBtn = el("button", {
    class: "icon-btn",
    title: "Minimize to dock (keeps monitoring)",
    onclick: (e) => { e.stopPropagation(); setMinimized(key, true); },
  }, "–");

  const pending = s.pending_count || 0;
  const directed = s.pending_directed || 0;   // unread messages addressed to THIS session
  const directedFrom = s.pending_directed_from || [];
  const guard = (window.conductorPrefs && window.conductorPrefs.busClickGuard) || "confirm-busy";
  const busy = s.status === "active" || s.status === "warm";
  const blocked = guard === "block-busy" && busy;
  const cls = "pending-badge" + (blocked ? " busy-blocked" : "") + (directed > 0 ? " directed" : "");
  const dtitle = directed > 0
    ? `${directed} addressed TO this session${directedFrom.length ? " (from " + directedFrom.join(", ") + ")" : ""}`
      + (blocked ? " — Claude busy; injection off" : " — auto-delivered when idle, or click to nudge now")
    : (blocked
        ? `${pending} unread — Claude is busy; injection disabled (Settings → Bus bubble click)`
        : `${pending} unread bus message(s) — click to run /msg-check in this Claude (raises its window)`);
  const pendingBadge = pending > 0
    ? el("span", {
        class: cls, title: dtitle,
        onclick: (e) => { e.stopPropagation(); if (!blocked) window.requestCheck(s.session_id, s.status); },
      }, directed > 0 ? `📨 ${directed} for you · 📬 ${pending}` : `📬 ${pending}`)
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

  const ended = s.status === "ended";
  const alreadyFaded = ended && fadedKeys.has(key);
  // Carry .fading in the class string when the fade already played, so reusing
  // (or recreating) the node keeps it at opacity 0 instead of replaying 1→0.
  tile.className = `tile status-${s.status}`
    + (ended ? " fading-out" : "")
    + (alreadyFaded ? " fading" : "")
    + (group ? " grouped" : "");
  tile.style.setProperty("--group-color", group ? group.color : "");
  tile.dataset.sessionId = s.session_id;
  tile.dataset.projectDir = s.project_dir;
  tile.dataset.tag = s.tag || "";

  const children = [
    el("div", { class: "tile-header" },
      el("div", { class: "tile-title-wrap" },
        el("span", { class: `status-dot ${s.status}`, title: statusLabel(s.status) }),
        el("span", { class: "tile-title", title: s.title || "" }, s.title || "(untitled)"),
      ),
      el("div", { class: "tile-actions" }, groupBtn, pendingBadge, focusBtn, minimizeBtn),
    ),
    group ? el("div", { class: "tile-grouplabel" },
      el("span", {
        class: "group-label",
        style: `color: ${group.color}; border-color: ${group.color}`,
        title: `Group: ${group.name} — manage via ▦`,
      }, `▦ ${group.name}`),
    ) : null,
    el("div", { class: "tile-projectdir", title: s.project_dir },
      tagChip, tagChip ? " " : null, s.project_dir,
    ),
    s.retraction
      ? el("div", { class: "tile-retraction",
          title: `[${s.retraction.sender}] retracted an instruction — this session is being woken to see it` },
          `🛑 RETRACTION from ${RES_BARE(s.retraction.sender)}: ${s.retraction.text}`)
      : null,
    el("div", { class: "tile-preview" }, s.preview || ""),
    (s.tokens && s.tokens.turns)
      ? el("div", { class: "tile-tokens", title: tokenTooltip(s.tokens) },
          `tokens: ${humanTok(s.tokens.output)} out · ${humanTok(s.tokens.total)} total`)
      : null,
    el("div", { class: "tile-footer" },
      el("span", {}, `msgs: ${s.message_count}`),
      el("span", {}, `⏱ ${ago(s.last_activity_at)}`),
      roleSelect(s),
    ),
  ].filter(Boolean);
  tile.replaceChildren(...children);

  if (ended && !alreadyFaded) {
    // Play the fade exactly once. Mark first so any re-render that lands
    // mid-fade takes the alreadyFaded branch above and holds at opacity 0.
    fadedKeys.add(key);
    requestAnimationFrame(() => tile.classList.add("fading"));
  }
  return tile;
}

// Bus tile shell — created once, reused. The click handler reads tileWasDragged
// at call time, so it doesn't need rebinding per render.
function createBusShell() {
  const tile = el("div", { class: "tile bus-tile", dataset: { busTile: "1" } });
  tile.addEventListener("click", (e) => {
    // Only open modal on a plain click — not the end of a drag (handled in pointerup).
    if (e.target.closest("button, .pending-badge")) return;
    if (!tileWasDragged) window.openBusModal();
  });
  return tile;
}

function fillBusTile(tile, state) {
  const total = state.busTotal || 0;
  const pendingByTag = state.busPendingByTag || {};
  // Split pending into "active" (tags with a live tile right now) vs the full
  // backlog (includes dormant tags like a frontend session not launched in days).
  const activeTags = new Set(
    (state.sessions || []).filter((s) => s.status !== "ended" && s.tag).map((s) => s.tag),
  );
  // The footer used to read "<allPending> unread" — the sum of every tag's backlog.
  // MEASURED 2026-08-16 that was 9,208 over a bus holding 463 messages: ~20x the
  // traffic that exists, dominated ENTIRELY by dormant tags (441 apiece for docs,
  // frontend, imagegen, orb_slam, isa-lab — whose directory no longer exists).
  //
  // The number was arithmetically correct and communicated something false. A sum
  // of per-tag backlogs also answers no question anyone actually has: what you want
  // to know is whether a session that is RUNNING is behind. So the headline is now
  // live sessions only, and dormant backlog is reported separately and named as
  // backlog — nobody is running to read it.
  let activePending = 0;
  let allPending = 0;
  let liveBehind = 0;
  let dormantTags = 0;
  for (const [tag, n] of Object.entries(pendingByTag)) {
    const c = n || 0;
    allPending += c;
    if (activeTags.has(tag)) {
      activePending += c;
      if (c > 0) liveBehind += 1;
    } else if (c > 0) {
      dormantTags += 1;
    }
  }
  const dormantPending = allPending - activePending;
  const pendingTitle = `${activePending} unread across ${liveBehind} live session(s)`
    + (dormantPending > 0
        ? `\n${dormantPending} more sit in ${dormantTags} dormant tag(s) — no session is running `
          + `to read those, so it is backlog, not a queue.`
        : "");
  const recentItems = (state.busRecent || []).slice(-5).reverse().map((ev) => {
    const t = new Date(ev.timestamp * 1000).toLocaleTimeString();
    const body = ev.payload_summary || "";
    return `${t} ${ev.source_session}: ${body}`;
  });
  const previewText = recentItems.length ? recentItems.join("\n") : "no events yet";
  const adapter = state.busAdapter || "markdown";

  tile.replaceChildren(
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
      el("span", { title: pendingTitle },
        activePending > 0
          ? `${activePending} unread · ${liveBehind} behind`
          : "live sessions current"),
      dormantPending > 0
        ? el("span", { class: "bus-dormant", title: pendingTitle },
            `+${dormantPending} dormant`)
        : null,
      el("span", {}, `tags: ${Object.keys(state.busTopology?.subscribers || {}).length}`),
    ),
  );
  return tile;
}

// --- GPU tile (Phase 3: shared-GPU reservation + live nvidia-smi telemetry) --
const RES_BARE = (t) => String(t || "").replace(/^\[/, "").replace(/\]$/, "").replace(/^other:/, "");
function resHuman(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${s}s`;
}

function createSvcShell() {
  return el("div", { class: "tile svc-tile", dataset: { svcTile: "1" } });
}

// A SERVICE Claude (image_gen): a session that does work FOR other sessions. Same
// shape as a dev board — single holder, one job at a time, a queue — except the
// resource DOES the work, so the lease reads "now serving X" rather than "X took me".
//
// Kyle is never a queue entry (he talks to it directly), so his priority is a HOLD:
// finish the current job — no wasted GPU render — then wait for him.
function fillServiceTile(tile, svc) {
  const serving = svc.serving;
  const queue = svc.queue || [];
  const held = !!svc.held;
  tile.className = "tile svc-tile" + (held ? " svc-held" : serving ? " svc-busy" : " svc-idle");

  const kids = [];
  kids.push(el("div", { class: "tile-header" }, [
    el("div", { class: "tile-title-wrap" }, [
      el("span", { class: "status-dot " + (held ? "warm" : serving ? "active" : "idle") }),
      el("span", { class: "tile-title", title: `service Claude: ${svc.name}` }, `🛠 ${svc.name}`),
    ]),
    el("span", { class: "svc-badge" }, held ? "HELD FOR YOU" : serving ? "BUSY" : "FREE"),
  ]));

  if (held) {
    kids.push(el("div", { class: "svc-hold" },
      `🙋 Reserved for you — it stops after its current job. ${svc.hold_reason || ""}`));
  }

  kids.push(serving
    ? el("div", { class: "svc-serving" }, [
        el("span", { class: "svc-label" }, "now serving"),
        el("span", { class: "svc-who" }, bare(serving.requester)),
        el("div", { class: "svc-job", title: serving.text }, serving.text || ""),
      ])
    : el("div", { class: "svc-serving svc-quiet" }, "idle — no job in progress"));

  if (queue.length) {
    kids.push(el("div", { class: "svc-queue-head" }, `⏳ ${queue.length} queued`));
    const ul = el("ul", { class: "svc-queue" });
    for (const j of queue.slice(0, 4)) {
      ul.appendChild(el("li", {}, [
        el("span", { class: "svc-who" }, bare(j.requester)),
        el("span", { class: "svc-job", title: j.text }, j.text || ""),
      ]));
    }
    if (queue.length > 4) ul.appendChild(el("li", { class: "svc-more" }, `+${queue.length - 4} more`));
    kids.push(ul);
  } else {
    kids.push(el("div", { class: "svc-queue-head svc-quiet" }, "queue empty"));
  }

  const btn = el("button", {
    class: "svc-btn" + (held ? " on" : ""),
    onclick: (e) => {
      e.stopPropagation();
      window.serviceAction(svc.name, held ? "resume" : "hold", e.currentTarget);
    },
  }, held ? "Release it" : "Serve me next");
  kids.push(el("div", { class: "svc-actions" }, [btn]));

  tile.replaceChildren(...kids);
}

function bare(tag) {
  return String(tag || "").replace(/^\[|\]$/g, "").replace(/^other:/, "") || "?";
}

function createResShell() {
  return el("div", { class: "tile gpu-tile", dataset: { resTile: "1" } });
}
// One tile per shared resource. The GPU (smi present) gets a utilization bar +
// memory footer; other resources (a board, …) are a plain lease with a hardware icon.
function fillResourceTile(tile, res) {
  const smi = res.smi || null;
  const lease = res.lease || null;
  const isGpu = !!smi;
  const label = res.label || res.name;

  const held = !!lease;
  const offered = held && lease.offered;
  const mode = !held ? null : (offered ? "offer" : (lease.mode === "hard" ? "hard" : "soft"));
  const dotClass = !held ? "gpu-free" : (offered ? "res-offer" : (mode === "hard" ? "gpu-hard" : "gpu-soft"));
  const queue = (held && lease.queue) || [];

  let leaseEl;
  if (offered) {
    // Held-for-the-next-in-line, awaiting their claim.
    const children = [
      el("span", { class: "gpu-mode offer" }, "OFFER"),
      el("span", { class: "gpu-owner" }, RES_BARE(lease.owner)),
      el("span", { class: "gpu-remaining", dataset: { expires: String(lease.expires_epoch || 0) } },
        "~" + resHuman(lease.remaining ?? 0) + " to claim"),
    ];
    if (queue.length) children.push(el("span", { class: "gpu-req", title: `${queue.length} more waiting` }, `⏳ +${queue.length}`));
    leaseEl = el("div", { class: "gpu-lease gpu-lease-offer", title: `offered to ${RES_BARE(lease.owner)} — awaiting claim or auto-pass` }, ...children);
  } else if (held) {
    const idle = lease.idle || 0;
    const children = [
      el("span", { class: `gpu-mode ${mode}` }, mode.toUpperCase()),
      el("span", { class: "gpu-owner" }, RES_BARE(lease.owner)),
      el("span", { class: "gpu-remaining", dataset: { expires: String(lease.expires_epoch || 0) } },
        "~" + resHuman(lease.remaining ?? 0) + " left"),
    ];
    if (idle >= 300) children.push(el("span", { class: "gpu-idle", title: "idle — the watchdog may nudge/reclaim it" }, `⚠ idle ${resHuman(idle)}`));
    if (queue.length) children.push(el("span", { class: "gpu-req", title: `queue: ${queue.map(RES_BARE).join(", ")}` }, `⏳ ${queue.length} queued (${RES_BARE(queue[0])} next)`));
    // Owner's session is gone. Conductor never reclaims on its own — offer the click.
    if (lease.orphan_suspect) {
      const off = resHuman(lease.owner_offline_seconds || 0);
      children.push(el("span", { class: "res-orphan", title:
        `No live session holds this lease — [${RES_BARE(lease.owner)}] has been offline ${off}.\n`
        + `It will free itself at expiry; reclaim now to hand it to the next in queue (or free it).` },
        `⚠ owner offline ${off}`));
      children.push(el("button", { class: "res-reclaim",
        title: "hand this resource to the next in queue (or free it) — its owner's session is gone",
        onclick: (e) => { e.stopPropagation(); window.reclaimResource(res.name, e.currentTarget); } },
        "reclaim"));
    }
    leaseEl = el("div", { class: "gpu-lease" }, ...children);
  } else {
    const cmd = isGpu ? "/gpu-reserve" : `/reserve ${res.name}`;
    leaseEl = el("div", { class: "gpu-lease gpu-lease-free" }, `● FREE — reserve with ${cmd}`);
  }

  const titleKids = [label];
  if (isGpu) {
    const util = Math.max(0, Math.min(100, smi.util ?? 0));
    titleKids.push(el("span", { class: "gpu-util-badge", title: "live GPU utilization" }, `${util}%`));
  }

  const children = [
    el("div", { class: "tile-header" },
      el("div", { class: "tile-title-wrap" },
        el("span", { class: `status-dot ${dotClass}` }),
        el("span", { class: "tile-title" }, ...titleKids),
      ),
    ),
  ];

  if (isGpu) {
    const util = Math.max(0, Math.min(100, smi.util ?? 0));
    const utilClass = util >= 70 ? "hot" : util >= 25 ? "warm" : "cool";
    const memUsed = smi.mem_used ?? 0, memTotal = smi.mem_total ?? 0;
    const memPct = memTotal ? Math.round((memUsed / memTotal) * 100) : 0;
    children.push(
      el("div", { class: "tile-projectdir gpu-name" }, smi.name || "GPU"),
      el("div", { class: "gpu-bar", title: `utilization ${util}%` },
        el("div", { class: `gpu-bar-fill ${utilClass}`, style: `width:${util}%` })),
      leaseEl,
    );

    // WHO IS ACTUALLY ON THE CARD. The lease says who INTENDS to use the GPU; nvidia-smi
    // says who IS. When those disagree the lease reports the reassuring one — which is how
    // image_gen came within seconds of killing another session's live container, believing
    // it was a stale daemon. So show the truth next to the claim.
    const procs = res.processes || [];
    if (procs.length) {
      children.push(el("div", { class: "gpu-procs" },
        ...procs.slice(0, 4).map((pr) => el("div", { class: "gpu-proc", title: pr.cmd || "" },
          el("span", { class: "gpu-proc-mem" }, `${(pr.mem_mb / 1024).toFixed(1)}G`),
          el("span", { class: "gpu-proc-who" + (pr.container ? " is-container" : "") },
            pr.container ? `🐳 ${pr.container}` : pr.owner),
        )),
        procs.length > 4 ? el("div", { class: "gpu-proc" }, `+${procs.length - 4} more`) : null,
      ));
    }

    children.push(
      el("div", { class: "tile-footer" },
        el("span", { title: "GPU memory used / total" },
          `mem ${(memUsed / 1024).toFixed(1)}/${(memTotal / 1024).toFixed(0)} GB · ${memPct}%`),
        el("span", {}, held && lease.job ? `job: ${lease.job}` : ""),
      ),
    );
  } else {
    children.push(
      el("div", { class: "tile-projectdir gpu-name", title: "shared hardware resource" }, `🔧 ${res.name}`),
      leaseEl,
      el("div", { class: "tile-footer" },
        el("span", {}, held ? "reserved" : "available"),
        el("span", {}, held && lease.job ? `job: ${lease.job}` : ""),
      ),
    );
  }

  // The asset card — how to reach + set up this resource (access / setup / gotchas / …).
  if (res.card) {
    children.push(el("button", { class: "res-card-btn",
      title: "how to access + set up this resource (from its asset card)",
      onclick: (e) => { e.stopPropagation(); window.showResourceCard && window.showResourceCard(res); } },
      res.card.has_access ? "🔑 Access & setup" : "📇 Card"));
  }

  tile.replaceChildren(...children);
  return tile;
}

// Smoothly tick the "~Nm left" countdown between the ~3s server updates.
function updateResCountdowns() {
  const now = Date.now() / 1000;
  document.querySelectorAll(".gpu-remaining[data-expires]").forEach((elm) => {
    const exp = Number(elm.dataset.expires || 0);
    if (!exp) return;
    const rem = exp - now;
    elm.textContent = rem > 0 ? "~" + resHuman(rem) + " left" : "expiring…";
  });
}
setInterval(updateResCountdowns, 1000);

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
    // 🔗 Link mode: a click SELECTS the session for an autonomy window instead of
    // dragging it. Handled here (not on "click") so it beats the drag handler.
    if (window.conductorLinkMode) {
      const tag = tile.dataset.tag;
      if (tag && window.toggleLinkSelect) {
        e.preventDefault();
        e.stopPropagation();
        window.toggleLinkSelect(tag);
      }
      return;
    }
    // Tidy (packed) mode flow-lays the tiles, so there's nothing to drag — bail
    // before we set the dragging state, or we'd freeze grid rebuilds for a drag
    // that can never move anything.
    if (window.conductorPrefs && window.conductorPrefs.packed) return;
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
