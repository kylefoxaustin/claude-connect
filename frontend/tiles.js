// tiles.js — render Claude session tiles + Bus tile + Skippy tiles.

const PIN_KEY = "conductor.pinnedOrder.v1";

function loadPinnedOrder() {
  try {
    return JSON.parse(localStorage.getItem(PIN_KEY) || "[]");
  } catch {
    return [];
  }
}
function savePinnedOrder(order) {
  try { localStorage.setItem(PIN_KEY, JSON.stringify(order)); } catch {}
}

let pinnedOrder = loadPinnedOrder();
let dragSrcKey = null;

function tileKeyForSession(s)  { return `session:${s.session_id}`; }
function tileKeyForSkippy(t)   { return `skippy:${t.component_id}`; }
const BUS_KEY = "bus:bus";

export function renderGrid(state) {
  const grid = document.getElementById("grid");

  // Build [{key, html-builder}] in a stable order: pinned first (in pinned order),
  // then unpinned by activity recency.
  const items = [];
  items.push({ key: BUS_KEY, render: () => busTile(state) });
  for (const s of state.sessions) {
    items.push({ key: tileKeyForSession(s), render: () => sessionTile(s, state) });
  }
  for (const t of state.skippy) {
    items.push({ key: tileKeyForSkippy(t), render: () => skippyTile(t) });
  }

  // Sort: pinned (in pinnedOrder), then unpinned (by last_activity desc, bus pinned-ish to top).
  const pinnedSet = new Set(pinnedOrder);
  const pinnedItems = pinnedOrder
    .map((k) => items.find((it) => it.key === k))
    .filter(Boolean);
  const unpinnedItems = items.filter((it) => !pinnedSet.has(it.key));
  unpinnedItems.sort((a, b) => sortKey(b, state) - sortKey(a, state));

  grid.innerHTML = "";
  for (const it of [...pinnedItems, ...unpinnedItems]) {
    const node = it.render();
    node.dataset.tileKey = it.key;
    if (pinnedSet.has(it.key)) {
      const pinBtn = node.querySelector(".pin-btn");
      if (pinBtn) pinBtn.classList.add("pinned");
    }
    wireDragHandlers(node);
    grid.appendChild(node);
  }
}

function sortKey(item, state) {
  if (item.key === BUS_KEY) return Number.POSITIVE_INFINITY; // bus tile first among unpinned
  if (item.key.startsWith("session:")) {
    const id = item.key.slice("session:".length);
    const s = state.sessions.find((x) => x.session_id === id);
    return s ? s.last_activity_at : 0;
  }
  return -1; // skippy tiles last
}

function statusLabel(status) {
  return {
    active: "active",
    warm: "warm",
    idle: "idle",
    dormant: "dormant",
    waiting: "waiting",
    ended: "ended",
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

function pinButton(key) {
  const isPinned = pinnedOrder.includes(key);
  return el("button", {
    class: "icon-btn pin-btn" + (isPinned ? " pinned" : ""),
    title: isPinned ? "Unpin" : "Pin",
    onclick: (e) => {
      e.stopPropagation();
      togglePin(key);
    },
  }, isPinned ? "★" : "☆");
}

function togglePin(key) {
  if (pinnedOrder.includes(key)) {
    pinnedOrder = pinnedOrder.filter((k) => k !== key);
  } else {
    pinnedOrder.push(key);
  }
  savePinnedOrder(pinnedOrder);
  renderGrid(window.conductorState);
}

function sessionTile(s, state) {
  const key = tileKeyForSession(s);
  const focusBtn = el("button", {
    class: "icon-btn",
    title: state.wmctrlAvailable ? "Focus terminal" : "wmctrl not installed",
    disabled: state.wmctrlAvailable ? null : "true",
    onclick: (e) => {
      e.stopPropagation();
      if (state.wmctrlAvailable) window.requestFocus(s.session_id);
    },
  }, "⏵");

  const pending = s.pending_count || 0;
  const pendingBadge = pending > 0
    ? el("span", {
        class: "pending-badge",
        title: `${pending} unread bus message(s) — click to /msg-check`,
        onclick: (e) => { e.stopPropagation(); window.requestCheck(s.session_id); },
      }, `📬 ${pending}`)
    : null;

  const tagChip = s.tag
    ? el("span", { class: "tag-chip", title: "claude-bus tag (auto-derived from CWD)" }, s.tag)
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
        el("span", { class: "tile-title" }, s.title || "(untitled)"),
      ),
      el("div", { class: "tile-actions" }, pendingBadge, pinButton(key), focusBtn),
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
    // Trigger CSS fade by toggling .fading on next frame.
    requestAnimationFrame(() => tile.classList.add("fading"));
  }
  return tile;
}

function busTile(state) {
  const total = state.busTotal || 0;
  // Aggregate pending across all known tags (per-session tiles also show their own).
  const pendingByTag = state.busPendingByTag || {};
  const totalPending = Object.values(pendingByTag).reduce((a, b) => a + (b || 0), 0);
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
    onclick: () => window.openBusModal(),
  },
    el("div", { class: "tile-header" },
      el("div", { class: "tile-title-wrap" },
        el("span", { class: "status-dot active" }),
        el("span", { class: "tile-title" }, "Bus",
          totalPending > 0 ? el("span", { class: "bus-badge" }, String(totalPending)) : null,
        ),
      ),
      el("div", { class: "tile-actions" }, pinButton(BUS_KEY)),
    ),
    el("div", { class: "tile-projectdir" }, `claude-bus · ${adapter}`),
    el("div", { class: "tile-preview" }, previewText),
    el("div", { class: "tile-footer" },
      el("span", {}, `total: ${total}`),
      el("span", {}, `tags: ${Object.keys(state.busTopology?.subscribers || {}).length}`),
    ),
  );
}

function skippyTile(t) {
  const key = tileKeyForSkippy(t);
  return el("div", {
    class: `tile skippy-tile status-${t.status}`,
    dataset: { skippyId: t.component_id },
  },
    el("div", { class: "tile-header" },
      el("div", { class: "tile-title-wrap" },
        el("span", { class: `status-dot ${t.status}` }),
        el("span", { class: "tile-title" }, t.label),
      ),
      el("div", { class: "tile-actions" }, pinButton(key)),
    ),
    el("div", { class: "tile-projectdir" }, "skippy framework"),
    el("div", { class: "tile-preview" }, t.detail),
    el("div", { class: "tile-footer" },
      el("span", {}, statusLabel(t.status)),
      el("span", {}, "stub"),
    ),
  );
}

// --- Drag & pin reorder -----------------------------------------------------

function wireDragHandlers(tile) {
  tile.draggable = true;
  tile.addEventListener("dragstart", (e) => {
    dragSrcKey = tile.dataset.tileKey;
    tile.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", dragSrcKey); } catch {}
  });
  tile.addEventListener("dragend", () => {
    tile.classList.remove("dragging");
    document.querySelectorAll(".drop-target").forEach((n) => n.classList.remove("drop-target"));
    dragSrcKey = null;
  });
  tile.addEventListener("dragover", (e) => {
    if (!dragSrcKey || dragSrcKey === tile.dataset.tileKey) return;
    e.preventDefault();
    tile.classList.add("drop-target");
  });
  tile.addEventListener("dragleave", () => tile.classList.remove("drop-target"));
  tile.addEventListener("drop", (e) => {
    e.preventDefault();
    tile.classList.remove("drop-target");
    const srcKey = dragSrcKey;
    const dstKey = tile.dataset.tileKey;
    if (!srcKey || srcKey === dstKey) return;

    // Pinning the dragged tile (and the target if not already pinned) gives us
    // a stable manual order. Insertion before the target.
    pinnedOrder = pinnedOrder.filter((k) => k !== srcKey);
    if (!pinnedOrder.includes(dstKey)) pinnedOrder.push(dstKey);
    const dstIdx = pinnedOrder.indexOf(dstKey);
    pinnedOrder.splice(dstIdx, 0, srcKey);
    savePinnedOrder(pinnedOrder);
    renderGrid(window.conductorState);
  });
}

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
