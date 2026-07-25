// projects.js — 🗂 Project Layer view (slice 4: the desktop project/members dashboard).
//
// Self-contained, lazily imported (mirrors heatmap.js): a throw in here can never touch the board.
// Pure DOM + SVG, no deps. Reads /api/projects (full records: jobs annotated with readiness, the
// escalations, and the fleet admission meter) and live-updates from the "projects" WS message via
// the window.__projectsOnUpdate hook app.js calls.
//
// The phone (/m) is the needs-you CONSOLE — it raises only what's blocked on Kyle. THIS is the
// workbench: the whole job DAG flowing (blocked → ready → dispatched → done), who's on the project,
// the escalations, and the concurrency the fleet is spending — the view you keep open to WATCH a
// project execute. Actions (approve a plan, dispatch a ready job, answer an escalation) are here too,
// driving the same tested endpoints the phone uses.

const svgEl = (n) => document.createElementNS("http://www.w3.org/2000/svg", n);
const bare = (t) => String(t || "").replace(/^\[/, "").replace(/\]$/, "").replace(/^other:/, "");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// readiness → colour + label. Matches bus.sh's own readiness rule.
const READY = {
  done:       { c: "#3fb950", ic: "✅", label: "done" },
  dispatched: { c: "#58a6ff", ic: "📤", label: "dispatched" },
  ready:      { c: "#d29922", ic: "▶",  label: "ready" },
  blocked:    { c: "#6e7681", ic: "⛔", label: "blocked" },
};
const STATE_BADGE = {
  draft: "#6e7681", nominating: "#8957e5", planning: "#8957e5",
  plan_review: "#d29922", active: "#3fb950",
};

let root = null;
let data = null;          // { projects, escalations, admission }
let selectedId = null;
let onKey = null;

async function fetchProjects() {
  try {
    const r = await fetch("/api/projects");
    if (!r.ok) return { projects: [], escalations: [], admission: {} };
    return await r.json();
  } catch {
    return { projects: [], escalations: [], admission: {} };
  }
}

async function reload() {
  data = await fetchProjects();
  ensureSelection();
  rerender();
}

// POST an action, then re-read so the DAG/escalations reflect it. Surfaces a refusal inline.
async function action(url, body, onErr) {
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await r.json().catch(() => ({}));
    if (j && j.ok === false) onErr?.(j.result || "refused");
  } catch (e) {
    onErr?.(String(e.message || e));
  }
  await reload();
}

function ensureSelection() {
  const ids = (data.projects || []).map((p) => p.id);
  if (selectedId && ids.includes(selectedId)) return;
  // Prefer a project that needs attention (plan awaiting, open Kyle escalation), else the newest.
  const needy = (data.projects || []).find(
    (p) => p.needs === "approve-plan" || p.open_kyle_escalations > 0);
  selectedId = (needy || data.projects?.[0] || {}).id || null;
}

export async function activate() {
  if (root) return;
  root = document.createElement("div");
  root.className = "proj-overlay";
  root.innerHTML = `
    <div class="proj-header">
      <span class="proj-title">🗂 Projects</span>
      <span class="proj-admission" id="proj-admission"></span>
      <button class="proj-close" title="Close (Esc)">×</button>
    </div>
    <div class="proj-body">
      <aside class="proj-sidebar" id="proj-sidebar"></aside>
      <section class="proj-detail" id="proj-detail"></section>
    </div>`;
  document.body.appendChild(root);
  root.querySelector(".proj-close").addEventListener("click", close);
  onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  // Live: app.js calls this on every "projects" WS frame while we're open.
  window.__projectsOnUpdate = (projects) => {
    if (!data) data = { projects: [], escalations: [], admission: {} };
    data.projects = projects || [];
    // escalations/admission aren't on the WS frame; re-derive escalations from the records so the
    // panel stays live, and leave the admission meter to the next reload/interaction.
    data.escalations = deriveEscalations(data.projects);
    ensureSelection();
    rerender();
  };
  await reload();
}

function close() {
  root?.remove();
  root = null;
  window.__projectsOnUpdate = null;
  if (onKey) document.removeEventListener("keydown", onKey);
  onKey = null;
}

// The WS "projects" frame carries the full records but not the separately-computed open-escalations
// list; re-derive it the same way the server does so a live update keeps the panel honest.
function deriveEscalations(projects) {
  const out = [];
  for (const p of projects || []) {
    for (const e of p.escalations || []) {
      if (e.state === "open") out.push({ ...e, project: p.id, project_goal: p.goal });
    }
  }
  return out;
}

function selected() {
  return (data.projects || []).find((p) => p.id === selectedId) || null;
}

function rerender() {
  if (!root) return;
  renderAdmission();
  renderSidebar();
  renderDetail();
}

function renderAdmission() {
  const a = data.admission || {};
  const el = root.querySelector("#proj-admission");
  if (a.cap == null) { el.textContent = ""; return; }
  const hot = a.in_flight >= a.cap || a.fleet_busy >= a.fleet_ceiling;
  el.innerHTML =
    `<span class="proj-meter ${hot ? "hot" : ""}" title="Fleet-global admission throttle — how many project jobs may run at once (§5b)">`
    + `jobs in flight <b>${a.in_flight}/${a.cap}</b> · fleet busy ${a.fleet_busy}/${a.fleet_ceiling}</span>`;
}

function renderSidebar() {
  const host = root.querySelector("#proj-sidebar");
  const ps = data.projects || [];
  if (!ps.length) {
    host.innerHTML = `<div class="proj-empty-side">No projects yet.<br><span>Start one with <code>bus.sh project new</code>.</span></div>`;
    return;
  }
  host.replaceChildren(...ps.map((p) => {
    const el = document.createElement("button");
    el.className = "proj-row" + (p.id === selectedId ? " sel" : "");
    const jc = p.job_counts || { done: 0, total: 0 };
    const attn = p.needs === "approve-plan" ? "📋" : (p.open_kyle_escalations > 0 ? "🚩" : "");
    el.innerHTML =
      `<span class="proj-row-top"><span class="proj-dot" style="background:${STATE_BADGE[p.state] || "#6e7681"}"></span>`
      + `<span class="proj-row-id">${esc(p.id)}</span>${attn ? `<span class="proj-row-attn">${attn}</span>` : ""}</span>`
      + `<span class="proj-row-goal">${esc((p.goal || "").slice(0, 60))}</span>`
      + `<span class="proj-row-meta">${esc(p.state)} · ${jc.done}/${jc.total} jobs</span>`;
    el.addEventListener("click", () => { selectedId = p.id; rerender(); });
    return el;
  }));
}

function membersOf(p) {
  const m = new Map();
  if (p.lead) m.set(bare(p.lead), "lead");
  for (const j of p.jobs || []) {
    const w = bare(j.to);
    if (w && !m.has(w)) m.set(w, "worker");
  }
  return [...m.entries()];
}

function renderDetail() {
  const host = root.querySelector("#proj-detail");
  const p = selected();
  if (!p) { host.innerHTML = `<div class="proj-empty">Select a project.</div>`; return; }

  host.replaceChildren();

  // --- meta bar: goal, state, members ---
  const meta = document.createElement("div");
  meta.className = "proj-meta";
  const members = membersOf(p).map(([who, role]) =>
    `<span class="proj-chip ${role}" title="${role}">${role === "lead" ? "★ " : ""}${esc(who)}</span>`).join("");
  meta.innerHTML =
    `<div class="proj-meta-goal"><span class="proj-state" style="background:${STATE_BADGE[p.state] || "#6e7681"}">${esc(p.state)}</span>`
    + `<h2>${esc(p.id)}</h2></div>`
    + `<div class="proj-goal-text">${esc(p.goal || "(no goal)")}</div>`
    + `<div class="proj-members">${members || '<span class="proj-chip">no members yet</span>'}</div>`;
  host.appendChild(meta);

  // --- plan gate (only when a plan awaits review) ---
  if (p.state === "plan_review" && p.plan_status === "submitted") {
    host.appendChild(planGate(p));
  } else if (p.plan) {
    const pl = document.createElement("details");
    pl.className = "proj-plan-collapsed";
    pl.innerHTML = `<summary>plan (${p.plan_status})</summary><pre>${esc(p.plan)}</pre>`;
    host.appendChild(pl);
  }

  // --- the DAG ---
  const jobs = p.jobs || [];
  const dag = document.createElement("div");
  dag.className = "proj-dag-wrap";
  if (!jobs.length) {
    dag.innerHTML = `<div class="proj-empty">No jobs yet. The lead adds them with <code>bus.sh project job add</code>.</div>`;
  } else {
    dag.appendChild(dagLegend());
    dag.appendChild(renderDag(p, jobs));
  }
  host.appendChild(dag);

  // --- escalations ---
  const es = p.escalations || [];
  if (es.length) host.appendChild(escalationsPanel(p, es));
}

function planGate(p) {
  const el = document.createElement("div");
  el.className = "proj-plan-gate";
  el.innerHTML =
    `<div class="proj-gate-head">📋 Plan awaiting your approval (Gate #1)`
    + `${p.plan_notes ? `<span class="proj-gate-note">last note: ${esc(p.plan_notes)}</span>` : ""}</div>`
    + `<pre class="proj-gate-plan">${esc(p.plan)}</pre>`
    + `<div class="proj-gate-actions"><button class="proj-btn go">Approve plan</button>`
    + `<button class="proj-btn back">Send back…</button><span class="proj-err"></span></div>`;
  const errEl = el.querySelector(".proj-err");
  el.querySelector(".go").addEventListener("click", () =>
    action(`/api/projects/${encodeURIComponent(p.id)}/approve`, {}, (m) => (errEl.textContent = m)));
  el.querySelector(".back").addEventListener("click", () => {
    const notes = prompt("What should the lead change? (sent back with the plan)");
    if (notes === null) return;
    action(`/api/projects/${encodeURIComponent(p.id)}/revise`, { notes: notes.trim() },
      (m) => (errEl.textContent = m));
  });
  return el;
}

function dagLegend() {
  const el = document.createElement("div");
  el.className = "proj-legend";
  el.innerHTML = Object.entries(READY).map(([k, v]) =>
    `<span><i style="background:${v.c}"></i>${v.label}</span>`).join("")
    + `<span class="proj-legend-hint">click a ready job to dispatch it</span>`;
  return el;
}

// Longest-path layering → columns. A dep must reference an EARLIER job (cycles impossible), so a
// simple memoized longest-path is well-defined.
function levelsOf(jobs) {
  const byId = new Map(jobs.map((j) => [j.id, j]));
  const lvl = new Map();
  const visit = (id, seen) => {
    if (lvl.has(id)) return lvl.get(id);
    const j = byId.get(id);
    const deps = (j && j.deps) || [];
    let L = 0;
    for (const d of deps) {
      if (seen.has(d)) continue;              // guard (shouldn't happen — no cycles)
      if (byId.has(d)) L = Math.max(L, 1 + visit(d, new Set(seen).add(id)));
    }
    lvl.set(id, L);
    return L;
  };
  for (const j of jobs) visit(j.id, new Set());
  return lvl;
}

function renderDag(p, jobs) {
  const lvl = levelsOf(jobs);
  const cols = new Map();                      // level -> [jobs]
  for (const j of jobs) {
    const L = lvl.get(j.id) || 0;
    (cols.get(L) || cols.set(L, []).get(L)).push(j);
  }
  const COLW = 190, ROWH = 74, NW = 150, NH = 50, PADX = 24, PADY = 20;
  const maxRows = Math.max(...[...cols.values()].map((a) => a.length));
  const width = PADX * 2 + (cols.size) * COLW;
  const height = PADY * 2 + maxRows * ROWH;
  const pos = new Map();                       // id -> {x,y}
  for (const [L, arr] of cols) {
    arr.forEach((j, i) => {
      pos.set(j.id, { x: PADX + L * COLW, y: PADY + i * ROWH });
    });
  }
  const svg = svgEl("svg");
  svg.setAttribute("class", "proj-dag");
  svg.setAttribute("viewBox", `0 0 ${Math.max(width, 320)} ${Math.max(height, 120)}`);
  svg.setAttribute("width", Math.max(width, 320));
  svg.setAttribute("height", Math.max(height, 120));

  // edges first (behind nodes)
  for (const j of jobs) {
    for (const d of j.deps || []) {
      const a = pos.get(d), b = pos.get(j.id);
      if (!a || !b) continue;
      const x1 = a.x + NW, y1 = a.y + NH / 2, x2 = b.x, y2 = b.y + NH / 2;
      const mx = (x1 + x2) / 2;
      const path = svgEl("path");
      path.setAttribute("d", `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`);
      const depDone = (jobs.find((x) => x.id === d) || {}).state === "done";
      path.setAttribute("class", "proj-edge" + (depDone ? " done" : ""));
      svg.appendChild(path);
    }
  }
  // nodes
  for (const j of jobs) {
    const { x, y } = pos.get(j.id);
    const r = READY[j.readiness] || READY.blocked;
    const g = svgEl("g");
    g.setAttribute("class", "proj-node" + (j.readiness === "ready" ? " ready" : ""));
    g.setAttribute("transform", `translate(${x},${y})`);
    const rect = svgEl("rect");
    rect.setAttribute("width", NW); rect.setAttribute("height", NH);
    rect.setAttribute("rx", 8);
    rect.setAttribute("class", "proj-node-box");
    rect.setAttribute("style", `--nc:${r.c}`);
    g.appendChild(rect);
    const t1 = svgEl("text");
    t1.setAttribute("x", 10); t1.setAttribute("y", 20); t1.setAttribute("class", "proj-node-id");
    t1.textContent = `${r.ic} ${j.id}`;
    g.appendChild(t1);
    const t2 = svgEl("text");
    t2.setAttribute("x", 10); t2.setAttribute("y", 38); t2.setAttribute("class", "proj-node-sub");
    t2.textContent = `→ ${bare(j.to)}${j.size ? " · " + j.size : ""}`;
    g.appendChild(t2);
    const title = svgEl("title");
    title.textContent = `${j.id} → ${bare(j.to)}\n${j.desc || ""}\n[${r.label}]`
      + (j.readiness === "blocked" ? `\nwaiting on: ${(j.blocking_deps || []).join(", ")}` : "")
      + (j.order_id ? `\norder: ${j.order_id}` : "");
    g.appendChild(title);
    if (j.readiness === "ready") {
      g.style.cursor = "pointer";
      g.addEventListener("click", () => {
        const err = (m) => alertNode(g, m);
        action(`/api/projects/${encodeURIComponent(p.id)}/jobs/${encodeURIComponent(j.id)}/dispatch`,
          null, err);
      });
    }
    svg.appendChild(g);
  }
  return svg;
}

function alertNode(g, msg) {
  // a transient inline note under a node when a dispatch is throttled/refused
  const t = svgEl("text");
  t.setAttribute("x", 10); t.setAttribute("y", 66);
  t.setAttribute("class", "proj-node-err");
  t.textContent = (msg || "").slice(0, 40);
  g.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function escalationsPanel(p, es) {
  const el = document.createElement("div");
  el.className = "proj-esc-panel";
  el.innerHTML = `<div class="proj-esc-head">🚩 Escalations</div>`;
  for (const e of es) {
    const row = document.createElement("div");
    const kyle = e.target === "kyle";
    row.className = "proj-esc" + (e.state === "answered" ? " done" : (kyle ? " kyle" : " lead"));
    const mark = e.severity || e.deny || (e.timed_out ? "timed out" : "");
    row.innerHTML =
      `<div class="proj-esc-top"><span class="proj-esc-route">${e.state === "answered" ? "🟢" : (kyle ? "🔴 you" : "🟡 lead")}</span>`
      + `${mark ? `<span class="proj-esc-mark">${esc(mark)}</span>` : ""}`
      + `<span class="proj-esc-by">${esc(bare(e.raised_by))}${e.job ? " · " + esc(e.job) : ""}</span></div>`
      + `<div class="proj-esc-q">${esc(e.question)}</div>`
      + (e.why ? `<div class="proj-esc-why">why: ${esc(e.why)}</div>` : "")
      + (e.recommendation ? `<div class="proj-esc-why">rec: ${esc(e.recommendation)}</div>` : "")
      + (e.state === "answered" ? `<div class="proj-esc-ans">✅ ${esc(e.answered_by)}: ${esc(e.answer)}</div>` : "");
    if (e.state === "open" && kyle) {
      const acts = document.createElement("div");
      acts.className = "proj-esc-acts";
      const errEl = document.createElement("span");
      errEl.className = "proj-err";
      const answer = (a) => action(
        `/api/projects/${encodeURIComponent(p.id)}/escalations/${encodeURIComponent(e.id)}/answer`,
        { answer: a }, (m) => (errEl.textContent = m));
      for (const o of e.options || []) {
        const b = document.createElement("button");
        b.className = "proj-btn opt";
        b.textContent = o;
        b.addEventListener("click", () => answer(o));
        acts.appendChild(b);
      }
      if (!(e.options || []).length) {
        const b = document.createElement("button");
        b.className = "proj-btn"; b.textContent = "Answer…";
        b.addEventListener("click", () => {
          const a = prompt(`Your decision for "${e.question}":`);
          if (a && a.trim()) answer(a.trim());
        });
        acts.appendChild(b);
      }
      acts.appendChild(errEl);
      row.appendChild(acts);
    }
    el.appendChild(row);
  }
  return el;
}
