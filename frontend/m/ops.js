/* Conductor Ops — the phone console.
 *
 * One job: show what is blocked on Kyle, and let him unblock it in a tap. Everything
 * else is secondary and lives behind a tab.
 *
 * Deliberately NOT a port of app.js. It shares no code with the desktop board, because
 * the moment it did, the board's assumptions (tiles have positions, lines have layers,
 * a session is a thing you arrange) would come with it.
 */

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- auth
// The token rides in the URL hash on the native app and is remembered here otherwise.
// Same scheme as the desktop shell so one token unlocks both.
const LS_TOKEN = "conductor.authToken";
let TOKEN = "";
(function initToken() {
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (m) {
    TOKEN = decodeURIComponent(m[1]);
    try { localStorage.setItem(LS_TOKEN, TOKEN); } catch { /* private mode */ }
    history.replaceState(null, "", location.pathname + location.search);
  } else {
    try { TOKEN = localStorage.getItem(LS_TOKEN) || ""; } catch { TOKEN = ""; }
  }
})();

// The backend reads X-Conductor-Token (or ?token= for the WS handshake, which cannot
// carry headers). NOT an Authorization header — matching what the middleware actually
// checks, rather than what a REST API "should" use.
const headers = () => (TOKEN ? { "X-Conductor-Token": TOKEN } : {});

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...headers(), ...(opts.headers || {}) },
  });
  if (res.status === 401) { showGate(); throw new Error("unauthorized"); }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    const e = new Error(detail);
    e.status = res.status;
    throw e;
  }
  return res.status === 204 ? null : res.json();
}

function showGate() {
  $("gate").hidden = false;
  $("app").hidden = true;
}

$("gate-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  TOKEN = $("gate-token").value.trim();
  try {
    await api("/api/ops");
    try { localStorage.setItem(LS_TOKEN, TOKEN); } catch { /* private mode */ }
    $("gate").hidden = true;
    $("app").hidden = false;
    start();
  } catch {
    $("gate-err").textContent = "That token didn't work.";
    $("gate-err").hidden = false;
  }
});

// ---------------------------------------------------------------- state
let ops = null;
const selected = new Map();  // session_id -> array of Sets, one per question
const answering = new Set(); // session_ids whose answer POST is in flight — same reason
                            // as `sending`: a refresh mid-POST would rebuild the card
                            // with a live Send button and invite a second answer.

// ---------------------------------------------------------------- helpers
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function ago(sec) {
  if (sec == null) return "";
  const s = Math.max(0, Math.round(sec));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

const bare = (t) => String(t || "").replace(/^\[|\]$/g, "").replace(/^other:/, "");
const nameOf = (cwd) => String(cwd || "").split("/").filter(Boolean).pop() || "?";

// ---------------------------------------------------------------- render
function render() {
  if (!ops) return;
  const c = ops.counts;

  $("counts").innerHTML = [
    c.needs_you ? `<span class="hot"><b>${c.needs_you}</b> need you</span>` : "",
    c.blocked ? `<span class="hot"><b>${c.blocked}</b> stuck</span>` : "",
    `<span><b>${c.working}</b> working</span>`,
    `<span><b>${c.idle}</b> idle</span>`,
  ].filter(Boolean).join("");

  renderInbox();
  renderFleet();
  renderAutonomy();
  renderBlocked();

  setBadge("inbox", c.needs_you, "badge");
  setBadge("blocked", c.blocked, "badge badge-warn");
  setBadge("auto", ops.autonomy.length, "badge badge-ok");
  $("inbox-n").textContent = c.needs_you ? `· ${c.needs_you}` : "";
}

function setBadge(pane, n, cls) {
  const el = $(`tab-badge-${pane}`);
  if (!el) return;
  el.hidden = !n;
  el.className = cls;
  el.textContent = n > 99 ? "99+" : String(n);
}

/* ---- NEEDS YOU: decisions first, then push approvals ------------------- */
function renderInbox() {
  const host = $("inbox");
  const items = [];

  for (const d of ops.decisions) items.push(decisionCard(d));
  // A proposal outranks a bare gate request: it's the same repo asking the SAME question
  // with the context attached, and answering it arms the grant.
  for (const p of ops.proposals || []) items.push(proposalCard(p));
  for (const p of ops.push) items.push(pushCard(p));
  // Approvals you already gave that the session hasn't used yet. Shown BELOW the things
  // that still need you — it's reassurance, not a task. Its whole job is to answer
  // "did my tap land?", which used to have no answer at all.
  for (const g of ops.grants || []) items.push(grantRow(g));

  if (!items.length) {
    host.innerHTML =
      `<div class="empty"><div class="empty-big">✅</div>Nothing is waiting on you.</div>`;
    return;
  }
  host.replaceChildren(...items);
}

function decisionCard(d) {
  const el = document.createElement("div");
  el.className = "card card-hot";
  const who = bare(d.tag) || nameOf(d.cwd);

  // One Set of chosen labels per question. Kept across re-renders so a 3s poll can't
  // wipe a selection out from under a thumb mid-tap.
  if (!selected.has(d.session_id)) {
    selected.set(d.session_id, d.questions.map(() => new Set()));
  }
  const sel = selected.get(d.session_id);

  const head = document.createElement("div");
  head.className = "card-head";
  head.innerHTML =
    `<span class="card-who">❓ ${esc(who)}</span>` +
    `<span class="row-age">${ago(d.age)}</span>`;
  el.appendChild(head);

  d.questions.forEach((q, qi) => {
    const qEl = document.createElement("div");
    qEl.className = "card-q";
    qEl.textContent = q.question;
    el.appendChild(qEl);

    q.options.forEach((o) => {
      const b = document.createElement("button");
      const on = () => sel[qi].has(o.label);
      const paint = () => {
        b.className = "opt" + (on() ? " opt-on" : "");
        b.querySelector(".opt-box").textContent = on() ? "✓" : "";
      };
      b.innerHTML =
        `<span class="opt-box${q.multiSelect ? "" : " opt-radio"}"></span>` +
        `<span class="opt-text"><span class="opt-l">${esc(o.label)}</span>` +
        (o.description ? `<span class="opt-d">${esc(o.description)}</span>` : "") +
        `</span>`;
      b.addEventListener("click", () => {
        if (q.multiSelect) {
          on() ? sel[qi].delete(o.label) : sel[qi].add(o.label);
        } else {
          // Single-select: choosing replaces. The picker on the other end can only
          // hold one, so the UI must not let him believe otherwise.
          sel[qi].clear();
          sel[qi].add(o.label);
        }
        el.querySelectorAll(".opt").forEach((x) => x.dispatchEvent(new Event("repaint")));
        submit.disabled = answering.has(d.session_id) || sel.some((s) => s.size === 0);
      });
      b.addEventListener("repaint", paint);
      paint();
      el.appendChild(b);
    });
  });

  const submit = document.createElement("button");
  submit.className = "btn btn-primary";
  submit.style.width = "100%";
  submit.style.marginTop = "6px";
  const busy = answering.has(d.session_id);
  submit.innerHTML = busy
    ? '<span class="spin"></span> Sending…'
    : "Send answer";
  submit.disabled = busy || sel.some((s) => s.size === 0);
  submit.addEventListener("click", async () => {
    if (answering.has(d.session_id)) return;
    answering.add(d.session_id);
    renderInbox();                     // repaint FROM state, so a refresh can't undo it
    try {
      await api(`/api/decisions/${encodeURIComponent(d.session_id)}`, {
        method: "POST",
        body: JSON.stringify({ answers: sel.map((s) => [...s]) }),
      });
      selected.delete(d.session_id);
      // No Undo here on purpose: the answer IS the keystroke, it has already landed in the
      // Claude, and there is nothing to take back. An Undo button would be a lie.
      answering.delete(d.session_id);
      await refresh();
    } catch (e) {
      answering.delete(d.session_id);
      // The common case is benign — he answered it at the keyboard a moment ago.
      const b = el.querySelector(".btn-primary");
      if (b) b.textContent = e.status === 409 ? "Already answered" : `Failed: ${e.message}`;
      setTimeout(refresh, 1500);
    }
  });
  el.appendChild(submit);
  return el;
}

/* "Should I push NOW, or keep digging?" — the question the GATE cannot ask.
 *
 * The gate protects the repo: nothing lands without Kyle's tap. But it could only ever show
 * him `claude-connect — git push origin main`, which says nothing about what is in the
 * commits, whether the session thinks the work is done, or what it would do instead. Tapping
 * Approve on that is a rubber stamp on a decision he never made — and a session that "just
 * pushes and lets the gate sort it out" has quietly appointed ITSELF the judge of whether the
 * work was ready.
 *
 * So the session says its piece, and Kyle answers ONE question with the information in front
 * of him. Choosing "Push it" ARMS the grant — there is no second content-free tap afterwards.
 */
function proposalCard(p) {
  const el = document.createElement("div");
  el.className = "card card-propose";
  const age = p.epoch ? Date.now() / 1000 - p.epoch : null;

  el.innerHTML =
    `<div class="card-head">` +
    `<span class="card-who">📤 ${esc(p.repo_name)} wants to push</span>` +
    `<span class="row-age">${ago(age)}</span></div>` +
    `<div class="card-q">${esc(p.why)}</div>` +
    (p.commits.length
      ? `<div class="commits">${p.commits.map((c) => `<div>${esc(c)}</div>`).join("")}</div>`
      : "");

  const answer = async (choice, btn, label) => {
    [...el.querySelectorAll("button")].forEach((b) => (b.disabled = true));
    btn.innerHTML = '<span class="spin"></span> ' + label;
    try {
      await api(`/api/proposals/${encodeURIComponent(p.key)}`, {
        method: "POST",
        body: JSON.stringify({ choice }),
      });
      await refresh();
    } catch (e) {
      btn.textContent = e.status === 409 ? "No longer open" : `Failed: ${e.message}`;
      setTimeout(refresh, 1500);
    }
  };

  const go = document.createElement("button");
  go.className = "btn btn-primary";
  go.style.width = "100%";
  go.style.marginTop = "4px";
  go.textContent = "✅ Push it";
  go.addEventListener("click", () => answer("", go, "Arming…"));
  el.appendChild(go);

  // The alternatives the session is actually weighing. This is the part the gate could never
  // offer, and it's the whole reason Kyle keeps getting asked in the terminal.
  for (const alt of p.alts) {
    const b = document.createElement("button");
    b.className = "btn";
    b.style.width = "100%";
    b.style.marginTop = "7px";
    b.textContent = `Not yet — ${alt}`;
    b.addEventListener("click", () => answer(alt, b, "Telling it…"));
    el.appendChild(b);
  }
  return el;
}

/* A push approval is REVERSIBLE for five seconds rather than gated behind a confirm
 * dialog: a dialog you see twenty times a day is habituated within a week and protects
 * nobody, while an undo window covers the only moment a mistake is actually noticed.
 *
 * THE STATE LIVES HERE, NOT IN THE DOM. renderInbox() calls replaceChildren() on every
 * refresh — and a refresh fires every few seconds — so anything stashed on the element
 * (a dimmed card, a disabled button) is wiped within one scan tick. That is exactly what
 * happened to Kyle: he tapped Approve, the card briefly dimmed, the next broadcast rebuilt
 * it looking untouched, so he tapped again. And each tap restarted the 5s timer, so the
 * approval never fired AT ALL while he kept pressing. A button that punishes you for
 * pressing it twice, and gives you no reason not to.
 *
 * Same class of bug as the desktop's link-selection fade (fillSessionTile rewriting
 * className wholesale). Optimistic UI must be rebuilt FROM state on every render, never
 * painted onto an element and hoped for. */
const approving = new Map();   // push key -> { repo, commitAt (ms), timer }
const sending = new Set();     // push keys whose POST is in flight

function armApprove(p) {
  if (approving.has(p.key) || sending.has(p.key)) return;   // idempotent: a 2nd tap is a no-op
  const timer = setTimeout(() => commitApprove(p.key), 5000);
  approving.set(p.key, { repo: p.repo_name || nameOf(p.cwd), commitAt: Date.now() + 5000, timer });
  renderInbox();
}

function cancelApprove(key) {
  const a = approving.get(key);
  if (!a) return;
  clearTimeout(a.timer);
  approving.delete(key);
  renderInbox();                 // nothing was ever sent
}

async function commitApprove(key) {
  approving.delete(key);
  sending.add(key);
  renderInbox();                 // -> "Sending…", so the tap is never ambiguous
  try {
    await api(`/api/push/${encodeURIComponent(key)}/approve`, { method: "POST" });
  } catch { /* the refresh below shows the truth */ }
  sending.delete(key);
  await refresh();
}

function pushCard(p) {
  const el = document.createElement("div");
  el.className = "card";
  const repo = p.repo_name || nameOf(p.cwd);
  const age = p.epoch ? Date.now() / 1000 - p.epoch : null;

  // --- in flight: the POST is out, there is nothing to undo -----------------
  if (sending.has(p.key)) {
    el.innerHTML =
      `<div class="card-head"><span class="card-who">🔐 ${esc(repo)}</span></div>` +
      `<div class="row-sub"><span class="spin"></span> Sending your approval…</div>`;
    return el;
  }

  // --- armed, counting down: undo is still possible -------------------------
  if (approving.has(p.key)) {
    el.classList.add("card-arming");
    el.innerHTML =
      `<div class="card-head"><span class="card-who">✅ ${esc(repo)}</span></div>` +
      `<div class="row-sub">Approving in <b class="cd" data-key="${esc(p.key)}">5</b>s…</div>`;
    const undo = document.createElement("button");
    undo.className = "btn";
    undo.style.width = "100%";
    undo.style.marginTop = "12px";
    undo.textContent = "Undo";
    undo.addEventListener("click", () => cancelApprove(p.key));
    el.appendChild(undo);
    return el;
  }

  // --- idle: waiting for a decision -----------------------------------------
  el.innerHTML =
    `<div class="card-head">` +
    `<span class="card-who">🔐 ${esc(repo)}</span>` +
    `<span class="row-age">${ago(age)}</span></div>` +
    `<div class="row-sub">wants to push · <code>${esc(p.cmd || "git push")}</code></div>`;

  const row = document.createElement("div");
  row.className = "btn-row";
  row.style.marginTop = "12px";

  const approve = document.createElement("button");
  approve.className = "btn btn-primary";
  approve.textContent = "Approve";
  approve.addEventListener("click", () => armApprove(p));

  const deny = document.createElement("button");
  deny.className = "btn btn-danger";
  deny.textContent = "Deny";
  // Deny needs no undo: it's recoverable by construction — the agent just asks again.
  deny.addEventListener("click", async () => {
    if (sending.has(p.key)) return;
    sending.add(p.key);
    renderInbox();
    await api(`/api/push/${encodeURIComponent(p.key)}/deny`, { method: "POST" }).catch(() => {});
    sending.delete(p.key);
    refresh();
  });

  row.append(approve, deny);
  el.appendChild(row);
  return el;
}

// Tick the countdown text in place. Rebuilding the whole card every 250ms would risk
// swapping the Undo button out from under a thumb mid-tap.
setInterval(() => {
  if (!approving.size) return;
  for (const el of document.querySelectorAll(".cd")) {
    const a = approving.get(el.dataset.key);
    if (a) el.textContent = String(Math.max(0, Math.ceil((a.commitAt - Date.now()) / 1000)));
  }
}, 200);



function grantRow(g) {
  const el = document.createElement("div");
  el.className = "row";
  const hrs = Math.max(0, Math.round(g.expires_in / 3600));
  el.innerHTML =
    `<div class="row-body">` +
    `<div class="row-title">✅ ${esc(g.repo_name)} <span class="pill">APPROVED</span></div>` +
    `<div class="row-sub">Waiting for the session to push · expires in ${hrs}h</div>` +
    `</div>`;
  const rev = document.createElement("button");
  rev.className = "btn btn-danger";
  rev.textContent = "Revoke";
  rev.addEventListener("click", async () => {
    rev.disabled = true;
    try {
      await api(`/api/push/${encodeURIComponent(g.key)}/revoke`, { method: "POST" });
    } catch { /* refresh shows the truth */ }
    refresh();
  });
  el.appendChild(rev);
  return el;
}

/* ---- FLEET: a sorted list, never a grid of 30 tiles. ------------------- */
// Status order for "working first". WAITING is the resting state of nearly every quiet
// session, so it sits with idle rather than reading as a distinct thing you should look at.
const STATUS_RANK = { active: 0, warm: 1, waiting: 2, idle: 3, dormant: 4, ended: 5 };

const LS_FLEET_SORT = "conductor.ops.fleetSort";

const FLEET_SORTS = {
  // The default, because it answers the question you actually opened this tab to ask.
  // A session with a question open outranks one with unread mail, which outranks a quiet one.
  attention: (a, b) =>
    (b.asking - a.asking) ||
    (b.pending - a.pending) ||
    (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9) ||
    (a.name || "").localeCompare(b.name || ""),
  recent: (a, b) => a.idle_seconds - b.idle_seconds,
  oldest: (a, b) => b.idle_seconds - a.idle_seconds,
  mail:   (a, b) => (b.pending - a.pending) || a.idle_seconds - b.idle_seconds,
  status: (a, b) =>
    ((STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9)) ||
    a.idle_seconds - b.idle_seconds,
  az: (a, b) => (a.name || "").localeCompare(b.name || ""),
  za: (a, b) => (b.name || "").localeCompare(a.name || ""),
};

let fleetSort = "attention";
try { fleetSort = localStorage.getItem(LS_FLEET_SORT) || "attention"; } catch { /* private */ }
if (!FLEET_SORTS[fleetSort]) fleetSort = "attention";

const sortSel = $("fleet-sort");
if (sortSel) {
  sortSel.value = fleetSort;
  sortSel.addEventListener("change", () => {
    fleetSort = sortSel.value;
    try { localStorage.setItem(LS_FLEET_SORT, fleetSort); } catch { /* private */ }
    renderFleet();
  });
}

function renderFleet() {
  const host = $("fleet");
  if (!ops || !ops.sessions.length) {
    host.innerHTML = `<div class="empty">No live sessions.</div>`;
    return;
  }
  // Copy before sorting: `ops.sessions` is the payload other panes read, and sorting in
  // place would quietly reorder it under them.
  const rows = [...ops.sessions].sort(FLEET_SORTS[fleetSort] || FLEET_SORTS.attention);
  host.replaceChildren(...rows.map((s) => {
    const el = document.createElement("div");
    el.className = "row";
    const badges = [
      s.asking ? `<span class="pill pill-ask">ASKING</span>` : "",
      s.pending ? `<span class="pill">📬 ${s.pending}</span>` : "",
    ].join("");
    el.innerHTML =
      `<span class="st st-${esc(s.status)}"></span>` +
      `<div class="row-body">` +
      `<div class="row-title">${esc(s.name)} ${badges}</div>` +
      `<div class="row-sub">${esc(s.preview || s.status)}</div>` +
      `</div>` +
      `<span class="row-age">${ago(s.idle_seconds)}</span>`;
    return el;
  }));
}

/* ---- UNATTENDED ------------------------------------------------------- */
function renderAutonomy() {
  const host = $("autonomy");
  if (!ops.autonomy.length) {
    host.innerHTML =
      `<div class="empty">Nobody is talking unattended.<br>` +
      `Sessions only wake each other when you allow it.</div>`;
    return;
  }
  const now = Date.now() / 1000;
  host.replaceChildren(...ops.autonomy.map((w) => {
    const el = document.createElement("div");
    el.className = "row";
    const left = Math.max(0, w.expires - now);   // the store's field is `expires`
    el.innerHTML =
      `<div class="row-body">` +
      `<div class="row-title">🔗 ${w.members.length} sessions</div>` +
      `<div class="row-sub">${esc(w.members.map(bare).join(", "))}</div>` +
      `</div>` +
      `<span class="row-age">${ago(left)} left</span>`;
    const rev = document.createElement("button");
    rev.className = "btn btn-danger";
    rev.textContent = "Revoke";
    rev.addEventListener("click", async () => {
      rev.disabled = true;
      await api(`/api/autonomy/${encodeURIComponent(w.id)}`, { method: "DELETE" }).catch(() => {});
      refresh();
    });
    el.appendChild(rev);
    return el;
  }));
}

$("grant-go").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    await api("/api/autonomy", {
      method: "POST",
      body: JSON.stringify({
        members: ops.sessions.map((s) => s.tag).filter(Boolean),
        hours: Number($("grant-hours").value),
      }),
    });
    await refresh();
  } finally {
    e.target.disabled = false;
  }
});

/* ---- BLOCKED ---------------------------------------------------------- */
function renderBlocked() {
  const host = $("blocked");
  const w = ops.waiting || {};
  const hard = (w.edges || []).filter((e) => e.hard);
  const bits = [];

  for (const c of w.cycles || []) {
    const el = document.createElement("div");
    el.className = "card" + (c.deadlock ? " card-hot" : "");
    el.innerHTML =
      `<div class="card-who">${c.deadlock ? "🛑 DEADLOCK" : "🔁 Mutual stall"}</div>` +
      `<div class="row-sub" style="white-space:normal">${esc(c.nodes.join(" → "))} → ${esc(c.nodes[0])}</div>` +
      `<div class="row-sub" style="white-space:normal;margin-top:6px">${esc(c.label)}</div>`;

    // Tell them. A stall is invisible from the INSIDE — each side thinks it's politely
    // awaiting a reply, and both are right about that, which is exactly why neither speaks.
    // The only actor who can see the loop is the one standing outside it.
    const btn = document.createElement("button");
    btn.className = "btn btn-primary";
    btn.style.width = "100%";
    btn.style.marginTop = "12px";
    btn.textContent = c.deadlock ? "Tell them it's a deadlock" : "Tell them they're both waiting";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.innerHTML = '<span class="spin"></span> Telling them…';
      try {
        const r = await api("/api/unstall", {
          method: "POST",
          body: JSON.stringify({ nodes: c.nodes }),
        });
        btn.textContent = r.pinged.length
          ? `✅ Told them · woke ${r.pinged.join(", ")}`
          : "✅ Told them — they'll see it when they surface";
        setTimeout(refresh, 4000);
      } catch (e) {
        btn.textContent = e.status === 409 ? "Already resolved" : `Failed: ${e.message}`;
        btn.disabled = false;
      }
    });
    el.appendChild(btn);
    bits.push(el);
  }

  for (const e of hard) {
    const el = document.createElement("div");
    el.className = "row";
    el.innerHTML =
      `<div class="row-body">` +
      `<div class="row-title">${esc(e.src)} → ${esc(e.dst)}</div>` +
      `<div class="row-sub">${esc(e.why)}</div>` +
      `</div><span class="row-age">${ago(e.age)}</span>`;
    bits.push(el);
  }

  if (!bits.length) {
    // Deliberately does NOT count the soft "awaiting a reply" edges as trouble. A
    // dashboard that shouts on a healthy fleet is one you learn to ignore — and then it
    // won't be believed the night something genuinely deadlocks.
    const awaiting = w.awaiting_count || 0;
    host.innerHTML =
      `<div class="empty"><div class="empty-big">👍</div>Nobody is stuck.` +
      (awaiting ? `<br><span style="font-size:13px">${awaiting} awaiting a reply — that's a conversation, not a problem.</span>` : "") +
      `</div>`;
    return;
  }
  host.replaceChildren(...bits);
}

// ---------------------------------------------------------------- tabs
const PANES = ["inbox", "fleet", "auto", "blocked"];

function showPane(name) {
  if (!PANES.includes(name)) name = "inbox";
  document.querySelectorAll(".tab").forEach(
    (x) => x.classList.toggle("tab-on", x.dataset.pane === name));
  for (const p of PANES) $(`pane-${p}`).hidden = p !== name;
  window.scrollTo(0, 0);
}

document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => showPane(t.dataset.pane));
});

// Deep-link a pane: /m?pane=blocked. A notification needs to open the SCREEN it is about,
// not the app's front door — landing on the inbox and making him hunt is how GitHub
// Mobile's approval flow ends up unusable.
showPane(new URLSearchParams(location.search).get("pane") || "inbox");

// ---------------------------------------------------------------- notifications
/* Web Push. Every failure mode here is silent — permission denied, a service worker that
 * never activated, a stale VAPID key — and all of them look identical to "nothing needs
 * you". So the UI always states which of those it is, and there is a Test button. */
const notifBtn = $("notif-btn");
const notifState = $("notif-state");

function urlB64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function notifStatus() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return { state: "unsupported", text: "This browser can't do notifications." };
  }
  if (!window.isSecureContext) {
    // The classic trap: over plain http everything "works" and simply never rings.
    return { state: "insecure", text: "Needs HTTPS. Open the https:// address." };
  }
  if (Notification.permission === "denied") {
    return { state: "denied", text: "Blocked. Re-allow in your browser's site settings." };
  }
  const reg = await navigator.serviceWorker.getRegistration("/m");
  const sub = reg && (await reg.pushManager.getSubscription());
  if (sub) return { state: "on", text: "On for this device." };
  return { state: "off", text: "Off. You'll only see things when you open the app." };
}

async function paintNotif() {
  if (!notifBtn) return;
  const st = await notifStatus();
  notifState.textContent = st.text;
  notifBtn.hidden = ["unsupported", "insecure", "denied"].includes(st.state);
  notifBtn.textContent = st.state === "on" ? "Send a test" : "Turn on notifications";
  notifBtn.dataset.mode = st.state === "on" ? "test" : "enable";
}

async function enableNotifications() {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return paintNotif();
  const reg = await navigator.serviceWorker.register("/m/sw.js", { scope: "/m" });
  await navigator.serviceWorker.ready;
  const { key } = await api("/api/webpush/key");
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlB64ToUint8Array(key),
  });
  await api("/api/webpush/subscribe", { method: "POST", body: JSON.stringify(sub.toJSON()) });
  await paintNotif();
}

if (notifBtn) {
  notifBtn.addEventListener("click", async () => {
    notifBtn.disabled = true;
    try {
      if (notifBtn.dataset.mode === "test") {
        const r = await api("/api/webpush/test", { method: "POST" });
        notifState.textContent = r.sent
          ? `Sent to ${r.sent} device(s) — it should appear now.`
          : "Couldn't deliver. Try turning them on again.";
      } else {
        await enableNotifications();
      }
    } catch (e) {
      notifState.textContent = `Failed: ${e.message}`;
    } finally {
      notifBtn.disabled = false;
    }
  });
}

// A notification click steers an ALREADY-OPEN console to the right pane.
navigator.serviceWorker?.addEventListener("message", (e) => {
  if (e.data?.kind === "navigate") {
    const pane = new URL(e.data.url, location.origin).searchParams.get("pane");
    showPane(pane || "inbox");
    refresh();
  }
});

// ---------------------------------------------------------------- live
async function refresh() {
  try {
    ops = await api("/api/ops");
    $("conn-dot").classList.add("up");
    render();
  } catch {
    $("conn-dot").classList.remove("up");
  }
}

let ws = null;
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const q = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : "";
  ws = new WebSocket(`${proto}://${location.host}/ws${q}`);
  // The socket only says "something changed" — we re-fetch /api/ops rather than trying to
  // patch state from six different message kinds. One source of truth, and a missed frame
  // can never leave the console showing a decision that is already answered.
  ws.onmessage = () => refresh();
  ws.onopen = () => { $("conn-dot").classList.add("up"); refresh(); };
  ws.onclose = () => {
    $("conn-dot").classList.remove("up");
    setTimeout(connect, 2000);
  };
}

// A backgrounded mobile tab can have its socket killed WITHOUT `close` firing — so the
// console can sit there looking connected while showing a stale, empty inbox. On the one
// screen that exists to tell you what needs you, that fails silent. Re-sync whenever the
// phone comes back to us, and poll slowly as a floor.
for (const ev of ["visibilitychange", "focus", "online"]) {
  window.addEventListener(ev, () => {
    if (document.visibilityState === "hidden") return;
    refresh();
    if (!ws || ws.readyState > 1) connect();
  });
}
setInterval(refresh, 15000);

async function start() {
  await refresh();
  connect();
  paintNotif();
}

// Is auth even on? If not, go straight in.
(async function boot() {
  try {
    await api("/api/ops");
    $("app").hidden = false;
    start();
  } catch {
    showGate();
  }
})();
