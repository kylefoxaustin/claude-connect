// launcher.js — the session launcher: one search-first panel for every dormant session
// (relaunch) and every live one (focus). Opened from the dock's "💤 N dormant" button, the
// header's ⟳ Relaunch, or Ctrl+K / "/" anywhere that isn't a text field.
//
// It replaces two surfaces that did the same job badly: the dormant strip of 11px chips along
// the bottom (39 of them on 2026-10-13, names cut at 140px, reachable only by a sideways scroll
// the cursor kept missing) and the ⟳ Relaunch modal (sortable and multi-select, but no search).
// You almost always know the NAME of the session you want, so the box takes focus on open and
// Enter acts on the top match.

import { isParkedDismissed, setParkedDismissed } from "/static/tiles.js";

const PINS_KEY = "conductor.launcherPins.v1";      // project_dir -> true
const SORT_KEY = "conductor.relaunchSort.v1";      // shared with the old modal: keeps his choice
const OLDER_OPEN_KEY = "conductor.launcherOlderOpen.v1";

const DAY = 86400;

let root = null;          // the overlay, present only while open
let query = "";
let sort = "recent";
let cursor = 0;           // index into `rows` (the visible, actionable rows)
let rows = [];            // [{kind:"parked"|"live", item, el}]
let checked = new Set();  // project (encoded dir) of ticked dormant rows
let launching = new Map(); // project_dir -> started (ms); "launching…" until it leaves the parked list
const LAUNCH_GIVEUP_MS = 3 * 60 * 1000;  // a launch that never arrived stops claiming it's coming
let open = { older: false, hidden: false, live: false };
let lastSig = "";

function loadJSON(key, dflt) {
  try { return JSON.parse(localStorage.getItem(key) || "null") ?? dflt; } catch { return dflt; }
}
function saveJSON(key, v) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch {}
}
let pins = loadJSON(PINS_KEY, {});

const st = () => window.conductorState || { sessions: [], parked: [] };
// A bus tag reads "[backend]" or "[other:week]"; show the bare word.
const tagOf = (p) => String(p.tag || "").replace(/^\[(?:other:)?(.*)\]$/, "$1");
const nameOf = (p) => String(p.title || tagOf(p) || "(untitled)");
const tokTotal = (p) => (p.tokens && p.tokens.total) || 0;

function fmtTok(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "K";
  return String(n);
}
function fmtAge(ts) {
  const s = Math.max(0, Date.now() / 1000 - (Number(ts) || 0));
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / DAY)}d ago`;
}
function shortPath(p) {
  const home = "/home/" + (String(p).split("/")[2] || "");
  return String(p || "").replace(home, "~");
}

// Match score: lower is better, null = no match. A substring of the NAME beats one in the
// title, which beats one in the path; a scattered-letters match on the name ("hbn" →
// holobench) ranks last but still counts — typing three letters should be enough.
function score(item, q) {
  if (!q) return 0;
  const name = nameOf(item).toLowerCase();
  const title = tagOf(item).toLowerCase();
  const path = String(item.project_dir || "").toLowerCase();
  let i = name.indexOf(q);
  if (i === 0) return 0;
  if (i > 0) return 1 + i / 100;
  if (title.includes(q)) return 2;
  if (path.includes(q)) return 3;
  let j = 0;
  for (const c of name) if (c === q[j]) j++;
  return j === q.length ? 4 : null;
}

function sortParked(list) {
  const by = {
    recent: (a, b) => b.last_activity_at - a.last_activity_at,
    oldest: (a, b) => a.last_activity_at - b.last_activity_at,
    az: (a, b) => nameOf(a).localeCompare(nameOf(b)),
    za: (a, b) => nameOf(b).localeCompare(nameOf(a)),
    tokens: (a, b) => tokTotal(b) - tokTotal(a),
    "tokens-asc": (a, b) => tokTotal(a) - tokTotal(b),
  }[sort] || ((a, b) => b.last_activity_at - a.last_activity_at);
  return [...list].sort(by);
}

function liveSessions() {
  return (st().sessions || []).filter((s) => s.status !== "ended");
}
function parkedList() {
  const liveDirs = new Set(liveSessions().map((s) => s.project_dir));
  return (st().parked || []).filter((p) => !liveDirs.has(p.project_dir));
}

// The dock button's count: what the launcher would offer, minus the ones you've hidden.
export function dormantCount() {
  return parkedList().filter((p) => !isParkedDismissed(p.project_dir)).length;
}

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids) if (c != null) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return e;
}

// --- actions ---------------------------------------------------------------------------------

function relaunchOne(p) {
  if (launching.has(p.project_dir)) return;
  launching.set(p.project_dir, Date.now());
  window.requestRelaunch(p.project, p.project_dir);
  close();
}

function focusLive(s) {
  if (st().wmctrlAvailable === false) return;
  window.requestFocus(s.session_id);
  close();
}

async function relaunchChecked() {
  const projects = [...checked];
  if (!projects.length) return;
  const n = projects.length;
  if (!window.confirm(
    `Relaunch ${n} session${n > 1 ? "s" : ""}?\n\n`
    + "Each resumes with --continue in its own terminal window. They launch one at a "
    + "time (staggered), so a big batch takes a few minutes to fully come back.")) return;
  const status = root?.querySelector(".ln-status");
  if (status) status.textContent = "Launching…";
  try {
    const r = await fetch("/api/relaunch-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projects }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    for (const p of st().parked || []) if (checked.has(p.project)) launching.set(p.project_dir, Date.now());
    checked.clear();
    const skipped = (body.skipped || []).length;
    if (status) {
      status.textContent = `Launching ${body.launching}`
        + (skipped ? ` · ${skipped} skipped` : "") + " — they'll appear as they come up.";
    }
    render();
  } catch (err) {
    if (status) status.textContent = `Failed: ${err.message}`;
  }
}

function togglePin(p) {
  if (pins[p.project_dir]) delete pins[p.project_dir]; else pins[p.project_dir] = true;
  saveJSON(PINS_KEY, pins);
  render();
}

function setHidden(p, on) {
  setParkedDismissed(p.project_dir, on);
  render();
}

// --- rendering -------------------------------------------------------------------------------

function parkedRow(p) {
  const isLaunching = launching.has(p.project_dir);
  const hidden = isParkedDismissed(p.project_dir);
  const name = nameOf(p);
  const tag = tagOf(p) !== name ? tagOf(p) : "";
  const row = el("li", {
    class: "ln-row" + (isLaunching ? " launching" : "") + (hidden ? " is-hidden" : ""),
    title: `${p.project_dir}\nlast active ${fmtAge(p.last_activity_at)}`
      + `\n${(tokTotal(p)).toLocaleString()} tokens\nClick or Enter to relaunch (claude --continue + /rc)`,
    onclick: () => relaunchOne(p),
  },
    el("input", {
      type: "checkbox", class: "ln-check", checked: checked.has(p.project),
      title: "Tick several, then Relaunch selected",
      onclick: (e) => {
        e.stopPropagation();
        if (e.target.checked) checked.add(p.project); else checked.delete(p.project);
        syncFooter();
      },
    }),
    el("button", {
      class: "ln-pin" + (pins[p.project_dir] ? " on" : ""),
      title: pins[p.project_dir] ? "Unpin" : "Pin to the top",
      onclick: (e) => { e.stopPropagation(); togglePin(p); },
    }, pins[p.project_dir] ? "★" : "☆"),
    el("span", { class: "ln-main" },
      el("span", { class: "ln-name" }, isLaunching ? `${name} — launching…` : name),
      tag ? el("span", { class: "ln-title" }, tag) : null,
      el("span", { class: "ln-path" }, shortPath(p.project_dir)),
    ),
    el("span", { class: "ln-age" }, fmtAge(p.last_activity_at)),
    el("span", { class: "ln-tok", title: "tokens used — heavy sessions may auto-compact on resume" },
      fmtTok(tokTotal(p))),
    el("button", {
      class: "ln-hide",
      title: hidden ? "Unhide" : "Hide (moves it to Hidden at the bottom)",
      onclick: (e) => { e.stopPropagation(); setHidden(p, !hidden); },
    }, hidden ? "↩" : "✕"),
  );
  return row;
}

function liveRow(s) {
  const name = nameOf(s);
  return el("li", {
    class: "ln-row ln-live",
    title: `${s.project_dir}\nrunning (${s.status}) — click or Enter to bring its window forward`,
    onclick: () => focusLive(s),
  },
    el("span", { class: `status-dot ${s.status}` }),
    el("span", { class: "ln-main" },
      el("span", { class: "ln-name" }, name),
      el("span", { class: "ln-path" }, shortPath(s.project_dir)),
    ),
    el("span", { class: "ln-age" }, s.status),
    el("span", { class: "ln-tok" }, "focus ↗"),
  );
}

function section(label, items, rowFn, key) {
  if (!items.length) return null;
  const collapsible = key !== undefined;
  const isOpen = !collapsible || open[key] || !!query;
  const head = el("li", {
    class: "ln-section" + (collapsible ? " collapsible" : ""),
    onclick: collapsible && !query ? () => {
      open[key] = !open[key];
      if (key === "older") saveJSON(OLDER_OPEN_KEY, open.older);
      render();
    } : null,
  }, (collapsible && !query ? (isOpen ? "▾ " : "▸ ") : "") + `${label} · ${items.length}`);
  const out = [head];
  if (isOpen) for (const it of items) out.push({ it, rowFn });
  return out;
}

function render() {
  if (!root) return;
  const list = root.querySelector(".ln-list");
  const prevScroll = list.scrollTop;
  list.innerHTML = "";
  rows = [];
  const q = query.trim().toLowerCase();
  const parked = parkedList();
  const live = liveSessions();
  const now = Date.now() / 1000;

  // Prune state that refers to sessions which have since come back.
  const parkedDirs = new Set(parked.map((p) => p.project_dir));
  for (const [d, t] of [...launching]) {
    if (!parkedDirs.has(d) || Date.now() - t > LAUNCH_GIVEUP_MS) launching.delete(d);
  }
  const parkedProjects = new Set(parked.map((p) => p.project));
  for (const pr of [...checked]) if (!parkedProjects.has(pr)) checked.delete(pr);

  const blocks = [];
  if (q) {
    // Searching: one ranked list, dormant and live together, hidden ones included (a search
    // is you asking for it by name — hiding it from the browse view shouldn't hide it here).
    const hits = [
      ...parked.map((p) => ({ kind: "parked", item: p, s: score(p, q) })),
      ...live.map((s) => ({ kind: "live", item: s, s: score(s, q) })),
    ].filter((h) => h.s !== null)
      .sort((a, b) => a.s - b.s || (b.item.last_activity_at || 0) - (a.item.last_activity_at || 0));
    if (!hits.length) {
      list.appendChild(el("li", { class: "ln-empty" }, `Nothing matches “${query.trim()}”.`));
    }
    for (const h of hits) blocks.push({ it: h.item, rowFn: h.kind === "live" ? liveRow : parkedRow });
  } else {
    const visible = sortParked(parked.filter((p) => !isParkedDismissed(p.project_dir)));
    const hidden = sortParked(parked.filter((p) => isParkedDismissed(p.project_dir)));
    const pinned = visible.filter((p) => pins[p.project_dir]);
    const rest = visible.filter((p) => !pins[p.project_dir]);
    const groups = [section("★ Pinned", pinned, parkedRow)];
    if (sort === "recent" || sort === "oldest") {
      const age = (p) => now - p.last_activity_at;
      groups.push(
        section("Today", rest.filter((p) => age(p) < DAY), parkedRow),
        section("This week", rest.filter((p) => age(p) >= DAY && age(p) < 7 * DAY), parkedRow),
        section("Older", rest.filter((p) => age(p) >= 7 * DAY), parkedRow, "older"),
      );
      if (sort === "oldest") groups.splice(1, 3, ...groups.slice(1).reverse());
    } else {
      groups.push(section("Dormant", rest, parkedRow));
    }
    groups.push(
      section("Hidden", hidden, parkedRow, "hidden"),
      section("Running — click to focus", live, liveRow, "live"),
    );
    if (!parked.length) {
      list.appendChild(el("li", { class: "ln-empty" },
        "No dormant sessions — the whole fleet is already running. 🎉"));
    }
    for (const g of groups) if (g) for (const b of g) blocks.push(b);
  }

  for (const b of blocks) {
    if (b instanceof Node) { list.appendChild(b); continue; }
    const node = b.rowFn(b.it);
    rows.push({ kind: b.rowFn === liveRow ? "live" : "parked", item: b.it, el: node });
    list.appendChild(node);
  }
  cursor = Math.max(0, Math.min(cursor, rows.length - 1));
  paintCursor(false);
  list.scrollTop = prevScroll;
  syncFooter();
}

function paintCursor(scroll = true) {
  rows.forEach((r, i) => r.el.classList.toggle("cursor", i === cursor));
  if (scroll) rows[cursor]?.el.scrollIntoView({ block: "nearest" });
}

function syncFooter() {
  if (!root) return;
  const btn = root.querySelector(".ln-go");
  const n = checked.size;
  btn.disabled = n === 0;
  btn.textContent = n ? `Relaunch ${n} selected` : "Relaunch selected";
}

// Re-render on fleet updates, but only when the SET of sessions changed — the board
// broadcasts every few seconds and a rebuild under the cursor would make hovering jumpy.
function signature() {
  const s = st();
  return JSON.stringify([
    (s.parked || []).map((p) => p.project_dir),
    (s.sessions || []).map((x) => x.session_id + x.status),
  ]);
}
export function launcherOnUpdate() {
  if (!root) return;
  const sig = signature();
  if (sig === lastSig) return;
  lastSig = sig;
  render();
}

// --- open / close ----------------------------------------------------------------------------

function onKey(e) {
  if (e.key === "Escape") { e.preventDefault(); close(); return; }
  if (e.key === "ArrowDown") { e.preventDefault(); cursor = Math.min(rows.length - 1, cursor + 1); paintCursor(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); cursor = Math.max(0, cursor - 1); paintCursor(); }
  else if (e.key === "Enter") {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) { relaunchChecked(); return; }
    const r = rows[cursor];
    if (!r) return;
    if (r.kind === "live") focusLive(r.item); else relaunchOne(r.item);
  }
}

export function openLauncher() {
  if (root) { root.querySelector(".ln-search").focus(); return; }
  query = "";
  cursor = 0;
  try { sort = localStorage.getItem(SORT_KEY) || "recent"; } catch { sort = "recent"; }
  open = { older: !!loadJSON(OLDER_OPEN_KEY, false), hidden: false, live: false };

  const search = el("input", {
    class: "ln-search", type: "search", placeholder: "Search sessions by name, title or folder…",
    autocomplete: "off", spellcheck: "false",
    oninput: (e) => { query = e.target.value; cursor = 0; render(); },
  });
  const sortSel = el("select", {
    class: "ln-sort", title: "Sort the dormant list",
    onchange: (e) => { sort = e.target.value; try { localStorage.setItem(SORT_KEY, sort); } catch {} render(); },
  }, ...[
    ["recent", "Most recent"], ["oldest", "Least recent"], ["az", "Name A → Z"],
    ["za", "Name Z → A"], ["tokens", "Tokens — most"], ["tokens-asc", "Tokens — least"],
  ].map(([v, t]) => el("option", { value: v, selected: v === sort }, t)));

  root = el("div", {
    class: "modal ln-overlay",
    onclick: (e) => { if (e.target === root) close(); },
  },
    el("div", { class: "modal-card ln-card", role: "dialog", "aria-label": "Session launcher" },
      el("div", { class: "ln-top" },
        search,
        sortSel,
        el("button", { class: "ln-close", title: "Close (Esc)", onclick: close }, "×"),
      ),
      el("ul", { class: "ln-list" }),
      el("div", { class: "ln-foot" },
        el("span", { class: "ln-hint" },
          "↑↓ move · Enter relaunch / focus · Ctrl+Enter relaunch ticked · Esc close"),
        el("span", { class: "ln-status" }),
        el("button", { class: "relaunch-go ln-go", onclick: relaunchChecked }, "Relaunch selected"),
      ),
    ),
  );
  document.body.appendChild(root);
  document.addEventListener("keydown", onKey, true);
  lastSig = signature();
  render();
  search.focus();
}

function close() {
  if (!root) return;
  root.remove();
  root = null;
  document.removeEventListener("keydown", onKey, true);
}

// Ctrl+K anywhere; "/" anywhere you aren't typing (the compose box, a rename field…).
document.addEventListener("keydown", (e) => {
  if (root) return;
  const typing = e.target.closest?.("input, textarea, select, [contenteditable=true]");
  if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
    e.preventDefault();
    openLauncher();
  } else if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    openLauncher();
  }
});
