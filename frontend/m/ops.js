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
    // detail may be a plain string or a structured {code, message, ...} — keep both so
    // callers can branch on a code (e.g. "session_not_running" → offer relaunch).
    const e = new Error(typeof detail === "string" ? detail : (detail.message || res.statusText));
    e.status = res.status;
    e.detail = detail;
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
const told = new Set();     // cycle-keys we've already told. Survives re-render — the
                            // card is rebuilt every refresh, so `btn.disabled = true`
                            // is wiped within seconds and the tap looks like it did
                            // nothing. That is exactly how Kyle sent the same stall
                            // message three times.
const answering = new Set(); // session_ids whose answer POST is in flight — same reason
const declining = new Set(); // decline POST in flight
// Free text per (session, question): "none of the above". Kept OUT of the DOM so a
// scan-tick rebuild cannot wipe what he typed — the v2.24.3 lesson.
const freeText = new Map(); // session_id -> Map(qIndex -> string)
                            // as `sending`: a refresh mid-POST would rebuild the card
                            // with a live Send button and invite a second answer.
const answerErr = new Map(); // session_id -> a persistent, actionable error message. When the
                            // answer POST fails in a way that ISN'T terminal (502 = Conductor
                            // couldn't aim the keystrokes because the tab is backgrounded), the
                            // guidance must SURVIVE the next refresh — so it lives in state and is
                            // rebuilt on every render, never painted onto the button then wiped by
                            // a background poll (the v2.24.3 lesson, and exactly why this read as
                            // "nothing takes": the actionable message flashed for 1.5s then vanished).

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

// Free text lives in a Map, never in the DOM: renderInbox() rebuilds these cards on
// every scan tick, and state painted onto an element is wiped by the next repaint.
function ftGet(sid, qi) { return (freeText.get(sid) || new Map()).get(qi) || ""; }
function ftSet(sid, qi, v) {
  if (!freeText.has(sid)) freeText.set(sid, new Map());
  freeText.get(sid).set(qi, v);
}
// A question counts as answered if it has a pick OR free text — the two are
// alternatives, because the picker's Other field replaces the selection.
function answeredAll(d, sel) {
  return d.questions.every((q, qi) =>
    sel[qi].size > 0 || ftGet(d.session_id, qi).trim().length > 0);
}
const bare = (t) => String(t || "").replace(/^\[|\]$/g, "").replace(/^other:/, "");
const nameOf = (cwd) => String(cwd || "").split("/").filter(Boolean).pop() || "?";

// ---------------------------------------------------------------- render
function render() {
  if (!ops) return;
  const c = ops.counts;

  const health = (c.collisions || 0) + (c.dead || 0) + (c.lost_rc || 0);   // holobench + rt1180 alerts land in Blocked
  $("counts").innerHTML = [
    // The one chip that's reassuring when EMPTY — say so, rather than just vanishing. Singular
    // "needs" for one, plural "need" for many.
    c.needs_you
      ? `<span class="hot"><b>${c.needs_you}</b> need${c.needs_you === 1 ? "s" : ""} you</span>`
      : `<span class="calm">nothing needs you</span>`,
    (c.blocked + health) ? `<span class="hot"><b>${c.blocked + health}</b> stuck</span>` : "",
    `<span><b>${c.working}</b> working</span>`,
    `<span><b>${c.idle}</b> idle</span>`,
  ].filter(Boolean).join("");

  renderWpBanner();
  renderInbox();
  renderFleet();
  renderAutonomy();
  renderPicker();
  renderBlocked();
  renderResources();
  renderProjects();
  const _wdo = $("winddown-overlay"); if (_wdo && !_wdo.hidden) renderWinddownM();  // live-update overlay as sessions ack

  // A resource whose owner is offline needs Kyle to reclaim it — the one resource state
  // that a human has to resolve, so it earns the tab badge.
  const resAlert = (ops.resources || []).filter(
    (r) => r.lease && r.lease.orphan_suspect).length;

  setBadge("inbox", c.needs_you, "badge");
  setBadge("blocked", c.blocked + health, "badge badge-warn");
  setBadge("auto", ops.autonomy.length, "badge badge-ok");
  setBadge("resources", resAlert, "badge badge-warn");
  // Projects tab badge: projects that want you (a plan to approve, an open escalation, a dead lead).
  // ⚠️ ANY project that renders a card in NEEDS YOU must also be counted here, or the header
  // says "nothing needs you" directly above a card that needs you — which is what Kyle's phone
  // showed for ieee-paper. The summary and the list must never disagree; a green header is a
  // stronger signal than a card, so the disagreement resolves the wrong way.
  const projAlert = (ops.all_projects || []).filter(
    (p) => p.needs || p.open_kyle > 0 || p.lead_offline).length;
  setBadge("projects", projAlert, "badge badge-warn");
  $("inbox-n").textContent = c.needs_you ? `· ${c.needs_you}` : "";
}

// Paging-health banner. The 2026-07-22 incident: notifications were dead for 6h and
// nothing said so, so a Claude sat blocked on a decision the whole time. If we can't
// page this phone, the phone should say so — the inbox is still the door, but silence
// must never read as "nothing needs you".
function renderWpBanner() {
  const el = $("wp-banner");
  if (!el) return;
  const wp = ops.webpush;
  if (!wp || wp.healthy !== false) { el.hidden = true; el.textContent = ""; return; }
  const fix = wp.reason === "no_subscription"
    ? "Turn on notifications below, or watch Needs You."
    : "Server-side notifications are down — watch Needs You in the meantime.";
  el.hidden = false;
  el.innerHTML = `<b>🔕 Notifications aren't reaching this phone.</b> ${esc(wp.detail || "")} ${esc(fix)}`;
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
  // Project escalations that are Kyle's to decide (the shield's denylist/severity hatch, or a
  // lead-timeout). Same shape as a decision — question · why · options — so it sits up here.
  for (const e of ops.escalations || []) items.push(escalationCard(e));
  // A proposal outranks a bare gate request: it's the same repo asking the SAME question
  // with the context attached, and answering it arms the grant.
  for (const p of ops.proposals || []) items.push(proposalCard(p));
  for (const p of ops.push) items.push(pushCard(p));
  // Acts that would outlive the session. These outrank a push: a push touches a repo;
  // a hook in settings.json is arbitrary code on every tool call in every session.
  for (const p of ops.persist || []) items.push(persistCard(p));
  // Project Layer Gate #1: a lead's plan awaiting Kyle's approval before work fans out.
  // The advisory states (an empty lead seat) render as a quiet info row, not a task.
  for (const p of ops.projects || []) {
    items.push(p.needs === "approve-plan" ? projectPlanCard(p) : projectInfoRow(p));
  }
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
        submit.disabled = answering.has(d.session_id) || !answeredAll(d, sel);
      });
      b.addEventListener("repaint", paint);
      paint();
      el.appendChild(b);
    });
  });

  // ── free text: the picker's own "Other" field, reachable from the phone ──────
  d.questions.forEach((q, qi) => {
    const wrap = document.createElement("div");
    wrap.className = "ft-wrap";
    const inp = document.createElement("input");
    inp.type = "text";
    inp.className = "ft";
    inp.placeholder = "…or answer in your own words";
    inp.value = ftGet(d.session_id, qi);
    inp.maxLength = 300;
    // Same privacy stance as the compose textareas (v2.39.0): Chrome's enhanced
    // spellcheck ships field contents to Google, and this field carries an answer
    // to a Claude about Kyle's work.
    inp.spellcheck = false;
    inp.setAttribute("autocorrect", "off");
    inp.setAttribute("autocapitalize", "sentences");
    inp.addEventListener("input", () => {
      ftSet(d.session_id, qi, inp.value);
      // Typing here REPLACES the selection, exactly as the picker's Other field does —
      // so the UI must not let him believe both are being sent.
      if (inp.value.trim()) sel[qi].clear();
      el.querySelectorAll(".opt").forEach((x) => x.dispatchEvent(new Event("repaint")));
      submit.disabled = answering.has(d.session_id) || !answeredAll(d, sel);
    });
    wrap.appendChild(inp);
    el.appendChild(wrap);
  });

  const decline = document.createElement("button");
  decline.className = "btn";
  decline.style.width = "100%";
  decline.style.marginTop = "6px";
  decline.textContent = declining.has(d.session_id) ? "Declining…" : "Decline to answer";
  decline.disabled = declining.has(d.session_id) || answering.has(d.session_id);
  decline.addEventListener("click", async () => {
    if (declining.has(d.session_id)) return;
    declining.add(d.session_id);
    renderInbox();
    try {
      await api(`/api/decisions/${encodeURIComponent(d.session_id)}/decline`, { method: "POST" });
      selected.delete(d.session_id); freeText.delete(d.session_id);
      declining.delete(d.session_id);
      await refresh();
    } catch (e) {
      declining.delete(d.session_id);
      answerErr.set(d.session_id, "Couldn't decline — try at the keyboard");
      renderInbox();
    }
  });
  el.appendChild(decline);

  const submit = document.createElement("button");
  submit.className = "btn btn-primary";
  submit.style.width = "100%";
  submit.style.marginTop = "6px";
  const busy = answering.has(d.session_id);
  const err = answerErr.get(d.session_id);          // persistent, rebuilt-from-state (not painted)
  submit.innerHTML = busy
    ? '<span class="spin"></span> Sending…'
    : (err ? err : "Send answer");
  if (err) submit.classList.add("btn-warn");        // visually distinct + still tappable to retry
  // Stays enabled on an error so a retry (after focusing the terminal) lands — the failure is
  // recoverable, not a dead end.
  submit.disabled = busy || declining.has(d.session_id) || !answeredAll(d, sel);
  submit.addEventListener("click", async () => {
    if (answering.has(d.session_id)) return;
    answerErr.delete(d.session_id);    // fresh attempt — drop any prior error message
    answering.add(d.session_id);
    renderInbox();                     // repaint FROM state, so a refresh can't undo it
    try {
      await api(`/api/decisions/${encodeURIComponent(d.session_id)}`, {
        method: "POST",
        body: JSON.stringify({
          answers: sel.map((s) => [...s]),
          free_text: d.questions.map((_, qi) => ftGet(d.session_id, qi) || null),
        }),
      });
      selected.delete(d.session_id);
      answerErr.delete(d.session_id);    // it landed — drop any lingering error state
      // No Undo here on purpose: the answer IS the keystroke, it has already landed in the
      // Claude, and there is nothing to take back. An Undo button would be a lie.
      answering.delete(d.session_id);
      await refresh();
    } catch (e) {
      answering.delete(d.session_id);
      const b = el.querySelector(".btn-primary");
      const code = e.detail && e.detail.code;
      if (code === "session_not_running") {
        // #4: the asking session died — don't pretend it was answered. Offer a relaunch
        // (once it's back and re-asks, it can be answered) instead of a dead end.
        if (b) {
          b.textContent = "Not running — Relaunch";
          b.disabled = false;
          const proj = e.detail.project;
          b.onclick = proj
            ? () => relaunchParked({ project: proj }, b)
            : () => showPane("fleet");
        }
      } else if (e.status === 409) {
        // Benign: answered at the keyboard a moment ago. The card SHOULD disappear — refresh.
        if (b) b.textContent = "Already answered";
        setTimeout(refresh, 1500);
      } else {
        // Non-terminal, RECOVERABLE failure — most commonly 502: Conductor couldn't aim the
        // keystrokes because the session's terminal tab is backgrounded (no TILIX_ID → it's only
        // locatable when it's the foreground tile). Persist an ACTIONABLE message IN STATE so it
        // survives the next poll (never a paint-then-wipe), and leave the button live so a retry
        // after focusing the window lands. This is the fix for "I keep hitting send and nothing takes".
        // A 502 means Conductor could NOT safely aim the keystrokes and fail-closed — one of three
        // ways, all with the SAME reliable remedy: (1) it can't locate the window; (2) the tilix
        // tile-activate didn't move focus (session shares a Tilix process / minimized); (3) a human
        // is active at the desktop and it won't race for focus. Advising "focus the window then
        // retry" was WRONG — focusing can trip (3), and retrying can't fix (2). The guaranteed path
        // is always: answer at the terminal keyboard. Say that.
        answerErr.set(d.session_id,
          e.status === 502
            ? "Can't type it safely from here — answer it at that terminal's keyboard"
            : `Failed: ${e.message || "try again"}`);
        renderInbox();
      }
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

/* 🔒 THE SECOND HARD CONTROL — an act whose consequences OUTLIVE the session.
 *
 * "The push gate is not about git. It is about ONE property: an act whose consequences outlive
 * the session that committed it." (image_gen). A push outlives you. So does a systemd unit, a
 * cron job, and — the dangerous one — a hook in settings.json, which is arbitrary code executed
 * on every tool call in every session. Fleet-wide RCE that looks like editing a config file.
 *
 * No Undo here, unlike a push approval. The act happens in a session we don't control, at a
 * time we don't choose. There is no window to take it back in — so the decision is made once,
 * deliberately, with what it touches spelled out.
 */
function persistCard(p) {
  const el = document.createElement("div");
  el.className = "card card-hot";
  const age = p.epoch ? Date.now() / 1000 - p.epoch : null;
  const KIND = { edit: "wants to edit", write: "wants to write to",
                 systemd: "wants to install a service", cron: "wants a cron job" };
  el.innerHTML =
    `<div class="card-head">` +
    `<span class="card-who">🔒 ${esc(KIND[p.kind] || "wants to persist")}</span>` +
    `<span class="row-age">${ago(age)}</span></div>` +
    `<div class="card-q">${esc(p.target_name)}</div>` +
    `<div class="commits"><div>${esc(p.detail || p.target)}</div></div>` +
    `<div class="row-sub" style="white-space:normal;margin-bottom:10px">` +
    `This outlives the session that runs it.</div>`;

  const row = document.createElement("div");
  row.className = "btn-row";
  const go = document.createElement("button");
  go.className = "btn btn-primary";
  go.textContent = "Allow once";
  const no = document.createElement("button");
  no.className = "btn btn-danger";
  no.textContent = "Deny";
  for (const [btn, act] of [[go, "approve"], [no, "deny"]]) {
    btn.addEventListener("click", async () => {
      [go, no].forEach((b) => (b.disabled = true));
      btn.innerHTML = '<span class="spin"></span> …';
      // Do NOT swallow the failure. A dead button that silently does nothing is exactly the
      // failure this whole project is about: the card sat with a malformed key the backend
      // 400'd, and the empty catch turned that into "Deny does nothing." Surface it instead.
      try {
        const r = await api(`/api/persist/${encodeURIComponent(p.key)}/${act}`, { method: "POST" });
        if (r && r.ok === false) throw new Error(r.result || "gate refused");
      } catch (e) {
        [go, no].forEach((b) => (b.disabled = false));
        btn.textContent = act === "deny" ? "Deny" : "Allow once";
        el.querySelector(".card-q")?.insertAdjacentHTML(
          "afterend", `<div class="row-sub" style="color:var(--bad,#ff6b6b)">couldn't ${act}: ${esc(String(e.message || e))} — tap again or clear from a terminal</div>`);
        return;
      }
      refresh();
    });
  }
  row.append(go, no);
  el.appendChild(row);
  return el;
}

/* A project ESCALATION Kyle must decide (slice 3 shield). Reached his queue because it hit the
 * denylist (scope/budget/goal/risk/irreversible), a severity hatch (safety/security/data-loss/
 * premise), or the lead didn't answer in time. Shows the decision, its project impact, the options,
 * and the raiser's recommendation — Kyle taps an option and it's recorded on the project (the lead +
 * worker read it). If there are no options, a free-text prompt. */
function escalationCard(e) {
  const el = document.createElement("div");
  el.className = "card card-hot";
  const mark = e.severity || e.deny || (e.timed_out ? "lead timed out" : "");
  const age = e.created ? Date.now() / 1000 - e.created : null;
  el.innerHTML =
    `<div class="card-head">` +
    `<span class="card-who">🚩 ${esc(e.project)} · ${esc(bare(e.raised_by) || "?")}` +
    (mark ? ` <span class="pill">${esc(mark)}</span>` : "") + `</span>` +
    `<span class="row-age">${ago(age)}</span></div>` +
    `<div class="card-q">${esc(e.question)}</div>` +
    (e.why ? `<div class="row-sub" style="white-space:normal">why: ${esc(e.why)}</div>` : "") +
    (e.recommendation ? `<div class="row-sub" style="white-space:normal">rec: ${esc(e.recommendation)}</div>` : "");

  const send = async (answer, btns) => {
    btns.forEach((b) => (b.disabled = true));
    try {
      const r = await api(`/api/projects/${encodeURIComponent(e.project)}/escalations/${encodeURIComponent(e.id)}/answer`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) });
      if (r && r.ok === false) throw new Error(r.result || "refused");
    } catch (err) {
      btns.forEach((b) => (b.disabled = false));
      el.querySelector(".card-q")?.insertAdjacentHTML(
        "afterend", `<div class="row-sub" style="color:var(--bad,#ff6b6b)">couldn't answer: ${esc(String(err.message || err))} — tap again or use a terminal</div>`);
      return;
    }
    refresh();
  };

  const opts = e.options || [];
  if (opts.length) {
    const btns = opts.map((o) => {
      const b = document.createElement("button");
      b.className = "opt";
      b.innerHTML = `<span class="opt-box opt-radio"></span><span class="opt-text"><span class="opt-l">${esc(o)}</span></span>`;
      b.addEventListener("click", () => send(o, btns));
      el.appendChild(b);
      return b;
    });
  } else {
    const row = document.createElement("div");
    row.className = "btn-row";
    const b = document.createElement("button");
    b.className = "btn btn-primary";
    b.textContent = "Answer…";
    b.addEventListener("click", () => {
      const a = prompt(`Your decision for "${e.question}":`);
      if (a === null || !a.trim()) return;
      send(a.trim(), [b]);
    });
    row.appendChild(b);
    el.appendChild(row);
  }
  return el;
}

/* Project Layer, Gate #1: a lead ([tag]) has submitted a PLAN and the project is blocked on Kyle
 * approving it before any work fans out. He decides where the information is — the goal + the plan
 * are both on the card — instead of walking to a terminal. Approve → ACTIVE; Send back → the plan
 * returns to the lead with a note. Both shell to the same `bus.sh project` one-writer. */
function projectPlanCard(p) {
  const el = document.createElement("div");
  el.className = "card card-hot";
  const age = p.created_epoch ? Date.now() / 1000 - p.created_epoch : null;
  el.innerHTML =
    `<div class="card-head">` +
    `<span class="card-who">📋 ${esc(bare(p.lead) || "?")} → plan for ${esc(p.id)}</span>` +
    `<span class="row-age">${ago(age)}</span></div>` +
    `<div class="card-q">${esc(p.goal || "(no goal)")}</div>` +
    `<div class="commits"><pre style="white-space:pre-wrap;margin:0">${esc(p.plan || "(empty plan)")}</pre></div>` +
    (p.plan_notes ? `<div class="row-sub" style="white-space:normal">last note: ${esc(p.plan_notes)}</div>` : "");

  const row = document.createElement("div");
  row.className = "btn-row";
  const go = document.createElement("button");
  go.className = "btn btn-primary";
  go.textContent = "Approve plan";
  const back = document.createElement("button");
  back.className = "btn btn-danger";
  back.textContent = "Send back";
  const act = async (action, notes) => {
    [go, back].forEach((b) => (b.disabled = true));
    (action === "approve" ? go : back).innerHTML = '<span class="spin"></span> …';
    try {
      const r = await api(`/api/projects/${encodeURIComponent(p.id)}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(notes ? { notes } : {}),
      });
      if (r && r.ok === false) throw new Error(r.result || "refused");
    } catch (e) {
      [go, back].forEach((b) => (b.disabled = false));
      go.textContent = "Approve plan"; back.textContent = "Send back";
      el.querySelector(".card-q")?.insertAdjacentHTML(
        "afterend", `<div class="row-sub" style="color:var(--bad,#ff6b6b)">couldn't ${action}: ${esc(String(e.message || e))} — tap again or use a terminal</div>`);
      return;
    }
    refresh();
  };
  go.addEventListener("click", () => act("approve"));
  back.addEventListener("click", () => {
    const notes = prompt("What should the lead change? (sent back with the plan)");
    if (notes === null) return;                 // cancelled — leave the plan pending
    act("revise", notes.trim());
  });
  row.append(go, back);
  el.appendChild(row);
  return el;
}

/* A project that lost its lead (nominee declined / suggested another) — advisory, not a task the
 * phone can complete: re-nominating needs a session picker (slice 4 / the desktop). Show it so Kyle
 * KNOWS the seat is empty; don't pretend there's a button here that isn't. */
function projectInfoRow(p) {
  const el = document.createElement("div");
  el.className = "card";
  const nom = p.last_nomination;
  // ⚠️ THE LAST BRANCH USED TO BE THE FALLBACK FOR EVERYTHING, and it asserted a fact.
  // ieee-paper sat on Kyle's phone for days reading "lead seat is empty — re-nominate"
  // while its state was `active`, its lead was `claude-connect`, and the actual problem was
  // three orders nobody had claimed in 29 days. A card that names the wrong reason is worse
  // than one that says nothing: it sends you to fix something that was never broken, and it
  // hides the thing that is. Every `needs` value now has its own line, and an unknown one
  // says so rather than borrowing the nearest sentence.
  let why;
  if (p.needs === "awaiting-nominee") {
    why = `nominee ${esc(bare(p.lead) || "?")} hasn't answered yet`;
  } else if (p.needs === "renominate") {
    why = nom && nom.response === "suggested"
      ? `${esc(nom.session)} suggested ${esc(nom.suggested)} — re-nominate`
      : `lead seat is empty — re-nominate`;
  } else if (p.needs === "stalled") {
    const st = p.stalls || [];
    const worst = st[0];
    const days = worst && worst.order_age_hours ? Math.floor(worst.order_age_hours / 24) : null;
    const who = [...new Set(st.map((x) => bare(x.to)).filter(Boolean))].slice(0, 3).join(", ");
    why = `${st.length} job${st.length === 1 ? "" : "s"} stalled`
      + (days != null ? `, oldest ${days}d` : "")
      + (who ? ` — ${esc(who)}` : "")
      + `. Lead: ${esc(bare(p.lead) || "nobody")}.`;
  } else {
    why = `needs attention (${esc(p.needs || "unspecified")})`;
  }
  el.innerHTML =
    `<div class="card-head"><span class="card-who">📋 ${esc(p.id)}</span></div>` +
    `<div class="row-sub" style="white-space:normal">${why}</div>`;
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
  const live = (ops && ops.sessions) || [];
  const parked = (ops && ops.parked) || [];
  if (!live.length && !parked.length) {
    host.innerHTML = `<div class="empty">No sessions.</div>`;
    return;
  }
  // Copy before sorting: `ops.sessions` is the payload other panes read, and sorting in
  // place would quietly reorder it under them.
  const rows = [...live].sort(FLEET_SORTS[fleetSort] || FLEET_SORTS.attention);
  const nodes = rows.map(fleetRow);
  if (parked.length) {
    const sep = document.createElement("div");
    sep.className = "fleet-sep";
    sep.textContent = `💤 Dormant · ${parked.length}`;
    nodes.push(sep, ...parked.map(parkedRow));
  }
  host.replaceChildren(...nodes);
}

function fleetRow(s) {
  const el = document.createElement("div");
  el.className = "row";
  const busy = s.status === "active" || s.status === "warm";
  const badges = [
    s.asking ? `<span class="pill pill-ask">ASKING</span>` : "",
    s.pending ? `<span class="pill">📬 ${s.pending}</span>` : "",
    s.bridged ? `<span class="pill pill-rc" title="remote-controlled — shows on your phone">📱</span>` : "",
  ].join("");
  el.innerHTML =
    `<span class="st st-${esc(s.status)}"></span>` +
    `<div class="row-body">` +
    `<div class="row-title">${esc(s.name)} ${badges}</div>` +
    `<div class="row-sub">${esc(s.preview || s.status)}</div>` +
    `</div>` +
    roleSelectHTML(s) +
    `<span class="row-age">${ago(s.idle_seconds)}</span>`;
  // Wake (nudge an idle session to check the bus) + Reconnect (re-bridge remote control).
  // State-driven, never painted-and-hoped (v2.24.3): the button label reflects s.rc_pending /
  // s.bridged, so the next refresh rebuilds the true state rather than a stale optimism.
  const acts = document.createElement("div");
  acts.className = "row-acts";
  if (!busy) acts.appendChild(mkBtn("Wake", "btn btn-sm", (b) => sessionAction(s, "check", b)));
  if (!s.bridged) {
    const rc = mkBtn(s.rc_pending ? "Reconnecting…" : "Reconnect", "btn btn-sm btn-rc",
                     (b) => sessionAction(s, "reconnect", b));
    rc.disabled = !!s.rc_pending;
    acts.appendChild(rc);
  }
  if (acts.children.length) el.appendChild(acts);
  const sel = el.querySelector(".mrole");
  if (sel) sel.addEventListener("change", (e) => { e.stopPropagation(); setMemberRole(s.member, e.target.value); });
  return el;
}

function parkedRow(p) {
  const el = document.createElement("div");
  el.className = "row row-parked";
  const age = (Date.now() / 1000) - (p.last_activity_at || 0);
  el.innerHTML =
    `<span class="st st-ended"></span>` +
    `<div class="row-body">` +
    `<div class="row-title">💤 ${esc(p.name)}</div>` +
    `<div class="row-sub">closed · ${esc(p.title || p.tag || "")}</div>` +
    `</div>` +
    `<span class="row-age">${ago(age)}</span>`;
  el.appendChild(mkBtn("Relaunch", "btn btn-sm", (b) => relaunchParked(p, b)));
  return el;
}

function mkBtn(text, cls, onClick) {
  const b = document.createElement("button");
  b.className = cls;
  b.textContent = text;
  b.addEventListener("click", (e) => { e.stopPropagation(); onClick(b); });
  return b;
}

// Wake (/check) or Reconnect (/reconnect) a LIVE session. Reports what the server actually did
// (sent / queued-for-idle / already-connected), then a refresh rebuilds from the true state.
async function sessionAction(s, verb, btn) {
  if (!s.session_id) return;
  btn.disabled = true;
  btn.textContent = verb === "reconnect" ? "Reconnecting…" : "Waking…";
  try {
    const r = await api(`/api/sessions/${encodeURIComponent(s.session_id)}/${verb}`, { method: "POST" });
    if (verb === "reconnect") {
      btn.textContent = r.state === "connected" ? "On your phone ✓"
        : r.state === "queued" ? "Waits for idle…" : "Sent — connecting…";
    } else if (r.injected) {
      btn.textContent = "Woken ✓";
    } else if (r.reason === "asking") {
      // Don't say "Sent" when nothing was — this session is asking YOU. Route to the answer.
      btn.textContent = "Asking you →";
      showPane("inbox");
    } else if (r.reason === "busy") {
      btn.textContent = "Busy — soon";   // it'll read mail when it pauses; we didn't interrupt
    } else {
      btn.textContent = "Couldn't reach it";
    }
  } catch (e) {
    btn.textContent = "Failed";
    btn.disabled = false;
    return;
  }
  setTimeout(refresh, 1800);   // the bridged badge flips / rc_pending clears on the next scan
}

// Relaunch a dead/closed session, and re-bridge it (rc:true) so it comes back on your phone.
async function relaunchParked(p, btn) {
  btn.disabled = true;
  btn.textContent = "Relaunching…";
  try {
    await api(`/api/relaunch`, { method: "POST", body: JSON.stringify({ project: p.project, rc: true }) });
    btn.textContent = "Launching…";
  } catch (e) {
    btn.textContent = "Failed";
    btn.disabled = false;
    return;
  }
  setTimeout(refresh, 3000);   // the revived session appears live on a later scan
}

// --- Reconstitute (DR) from the phone ----------------------------------------
// Drive the fleet rebuild remotely once Conductor is up on the new box: read the plan,
// tap the sessions to bring back, execute clone + --continue one at a time.
const RECON_LABEL = {
  live: "live", present: "relaunch", clone: "clone repo",
  "transcript-only": "resume (no repo)", blocked: "can't recover",
};
let reconSel = new Set();

function updateReconGo() {
  const b = $("recon-go");
  if (!b) return;
  b.disabled = reconSel.size === 0;
  b.textContent = reconSel.size ? `Reconstitute ${reconSel.size}` : "Reconstitute";
}

async function openReconM() {
  reconSel = new Set();
  const cards = $("recon-cards");
  $("recon-status").textContent = "Loading the recovery plan…";
  $("recon-note").textContent = "";
  cards.innerHTML = "";
  updateReconGo();
  $("recon-overlay").hidden = false;
  let plan;
  try { plan = await api("/api/reconstitute"); }
  catch (e) { $("recon-status").textContent = `Couldn't load: ${e.message}`; return; }
  const c = plan.counts || {};
  $("recon-status").textContent = "";
  $("recon-note").textContent =
    `${plan.session_count} sessions · ${c.live || 0} live · `
    + `${(c.present || 0) + (c.clone || 0) + (c["transcript-only"] || 0)} recoverable`
    + (c.blocked ? ` · ${c.blocked} blocked` : "");
  for (const s of (plan.sessions || [])) {
    const selectable = s.recoverable && s.status !== "live";
    const el = document.createElement("div");
    el.className = "card recon-card" + (selectable ? " recon-tap" : " recon-off");
    const blk = (s.blockers || []).map((b) => `<div class="recon-blk">⚠ ${esc(b)}</div>`).join("");
    const badgeCls = "rb-" + s.status.replace("-", "");
    el.innerHTML =
      `<div class="recon-cardhead"><span class="recon-badge ${badgeCls}">`
      + `${RECON_LABEL[s.status] || s.status}</span> <b>${esc(s.tag || s.cwd)}</b></div>`
      + `<div class="row-sub" style="white-space:normal">${esc(s.cwd)}</div>`
      + `<div class="row-sub">${s.git_remote ? esc(s.git_remote) : (s.is_repo ? "(local repo)" : "(no repo)")}`
      + `${s.git_dirty ? " · ⚠ dirty" : ""}${s.transcripts_present ? "" : " · ⚠ no transcript"}</div>`
      + blk;
    if (selectable) {
      el.onclick = () => {
        if (reconSel.has(s.cwd)) { reconSel.delete(s.cwd); el.classList.remove("recon-sel"); }
        else { reconSel.add(s.cwd); el.classList.add("recon-sel"); }
        updateReconGo();
      };
    }
    cards.appendChild(el);
  }
}

$("recon-open")?.addEventListener("click", openReconM);
$("recon-close")?.addEventListener("click", () => { $("recon-overlay").hidden = true; });
$("recon-go")?.addEventListener("click", async () => {
  const cwds = [...reconSel];
  if (!cwds.length) return;
  const b = $("recon-go"); b.disabled = true;
  let done = 0, failed = 0;
  for (const cwd of cwds) {          // one at a time so clones/spawns don't stampede
    $("recon-status").textContent = `Reconstituting ${done + failed + 1}/${cwds.length}…`;
    try { await api("/api/reconstitute/execute", { method: "POST", body: JSON.stringify({ cwd }) }); done++; }
    catch (e) { failed++; }
  }
  $("recon-status").textContent = `Launched ${done}${failed ? `, ${failed} failed` : ""}. They come up shortly.`;
  setTimeout(openReconM, 2500);      // refresh the plan (statuses change)
});

// Resource asset card overlay (how to access + set up a resource, from the phone). Bodies
// render via textContent (raw ssh commands / key paths preserved, no HTML injection).
async function showResourceCardM(r) {
  const stub = r && r.card;
  if (!stub) return;
  $("card-ov-title").textContent = (r.label || r.name) + (stub.kind ? " · " + stub.kind : "");
  const body = $("card-ov-body");
  body.replaceChildren();
  $("card-overlay").hidden = false;

  // The card body is fetched on demand — it is ~99% of the resources payload and
  // is read only here, which matters most on the phone over Tailscale.
  let card = stub;
  if (stub.deferred) {
    const loading = document.createElement("div");
    loading.className = "card-ov-summary"; loading.textContent = "Loading card…";
    body.appendChild(loading);
    try {
      // api() — NOT bare fetch: the phone injects X-Conductor-Token explicitly
      // rather than wrapping window.fetch the way the desktop does, so a raw
      // fetch here would 401 behind the tailnet auth.
      card = await api(`/api/resources/${encodeURIComponent(r.name)}/card`);
    } catch (err) {
      body.replaceChildren();
      const e = document.createElement("div");
      e.className = "card-ov-summary";
      // Report the FETCH failure, never an empty card — an empty card here would
      // be a confident lie about the resource you are about to go and touch.
      e.textContent = "Couldn't load this card (" + (err && err.message ? err.message : err)
        + "). The card exists — the fetch failed.";
      body.appendChild(e);
      return;
    }
    body.replaceChildren();
  }

  if (card.summary) {
    const s = document.createElement("div");
    s.className = "card-ov-summary"; s.textContent = card.summary;
    body.appendChild(s);
  }
  for (const sec of card.sections || []) {
    const wrap = document.createElement("section");
    wrap.className = "card-ov-section" + (sec.key === "access" ? " card-ov-access" : "");
    const h = document.createElement("div");
    h.className = "card-ov-h"; h.textContent = (sec.key === "access" ? "🔑 " : "") + sec.title;
    const pre = document.createElement("pre");
    pre.className = "card-ov-pre"; pre.textContent = sec.body;
    wrap.append(h, pre);
    body.appendChild(wrap);
  }
  $("card-overlay").hidden = false;
}
$("card-ov-close")?.addEventListener("click", () => { $("card-overlay").hidden = true; });

// @mention → deliver YOUR words to a session as a live prompt (Kyle's "@claude-connect …").
// Parse a leading @tag, POST /api/prompt-route; the backend queues + injects once it's quiet.
const atForm = $("atbar"), atIn = $("atbar-in"), atStatus = $("atbar-status");
atForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const raw = (atIn.value || "").trim();
  const mm = raw.match(/^@([A-Za-z0-9_.:-]+)\s+([\s\S]+)$/);
  if (!mm) { atStatus.textContent = "Start with @session — e.g. @claude-connect check the bus"; return; }
  const tag = mm[1], message = mm[2].trim();
  atStatus.textContent = `Sending to @${tag}…`;
  try {
    const r = await api("/api/prompt-route", { method: "POST", body: JSON.stringify({ tag, message }) });
    atStatus.textContent = `✓ Sent to @${bare(r.tag)} — it lands ${r.delivery}.`;
    atIn.value = "";
  } catch (err) {
    atStatus.textContent = err.status === 404
      ? `No live session called @${tag} (it must be running).`
      : `Failed: ${err.message}`;
  }
});

// Member-role control (v4 §3.4): observer=read-only · service · peer=default · trusted.
const MROLES = ["observer", "service", "peer", "trusted"];
function roleSelectHTML(s) {
  if (!s.member) return "";
  const cur = s.role || "peer";
  const opts = MROLES.map((r) => `<option value="${r}"${r === cur ? " selected" : ""}>${r}</option>`).join("");
  return `<select class="mrole role-${esc(cur)}" title="role — observer:read-only  peer:default">${opts}</select>`;
}
async function setMemberRole(member, role) {
  if (!member) return;
  try {
    await api(`/api/members/${encodeURIComponent(member)}/role`, { method: "POST", body: JSON.stringify({ role }) });
  } catch (e) { /* refresh shows the truth */ }
  refresh();
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

// Who may talk. The desktop has always had this (click tiles to select); the phone only
// ever offered "the whole fleet" — a blunter permission than you want to be granting at 2am.
// `picked === null` means "everyone", so the default behaviour is unchanged and you never
// have to tick 15 boxes to do the common thing.
let picked = null;   // null = all; otherwise a Set of tags

function renderPicker() {
  const list = $("pick-list");
  if (!list || !ops) return;
  const tags = ops.sessions.map((s) => s.tag).filter(Boolean);
  const on = (t) => (picked === null ? true : picked.has(t));

  list.replaceChildren(...ops.sessions.filter((s) => s.tag).map((s) => {
    const li = document.createElement("li");
    const lab = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = on(s.tag);
    cb.addEventListener("change", () => {
      if (picked === null) picked = new Set(tags);      // materialise before removing one
      cb.checked ? picked.add(s.tag) : picked.delete(s.tag);
      paintCount();
    });
    lab.append(cb);
    const dot = document.createElement("span");
    dot.className = `pick-st st-${s.status}`;
    lab.append(dot, document.createTextNode(s.name));
    li.appendChild(lab);
    return li;
  }));
  paintCount();
}

function paintCount() {
  const el = $("pick-count");
  if (!el || !ops) return;
  const n = picked === null ? ops.sessions.filter((s) => s.tag).length : picked.size;
  el.textContent = picked === null ? "all sessions" : `${n} selected`;
  const go = $("grant-go");
  if (go) {
    // Two is the floor: a "window" of one session cannot let anyone wake anyone.
    go.disabled = n < 2;
    go.textContent = picked === null ? "Let the whole fleet talk" : `Let these ${n} talk`;
  }
}

$("pick-all")?.addEventListener("click", () => { picked = null; renderPicker(); });
$("pick-none")?.addEventListener("click", () => { picked = new Set(); renderPicker(); });

$("grant-go").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    const members = picked === null
      ? ops.sessions.map((s) => s.tag).filter(Boolean)
      : [...picked];
    await api("/api/autonomy", {
      method: "POST",
      body: JSON.stringify({ members, hours: Number($("grant-hours").value) }),
    });
    picked = null;                 // back to the safe default for next time
    await refresh();
  } finally {
    e.target.disabled = false;
  }
});

/* ---- BLOCKED ---------------------------------------------------------- */
function silenceLabel(sec) {
  if (sec == null) return "has never posted";
  const h = sec / 3600;
  if (h >= 24) return `silent ${Math.floor(h / 24)}d`;
  if (h >= 1) return `silent ${Math.floor(h)}h`;
  return `silent ${Math.max(1, Math.floor(sec / 60))}m`;
}

// The SOFT edges — "awaiting", not "stuck". Deliberately subordinate (a tap-to-expand
// disclosure, muted), because a healthy fleet always has some of these and a pane that shouts
// about them trains you to ignore it. But it must be HONEST and INSPECTABLE, which it wasn't:
// it showed only a count, and lumped service jobs under "awaiting a REPLY" — wrong. An open
// question awaits a reply; a service job awaits a RENDER and is already in flight (fire-and-forget,
// the requester isn't blocked). Different things; different words; and now you can see WHO.
function softAwaitingNode(w) {
  const soft = (w.edges || []).filter((e) => !e.hard);
  if (!soft.length) return null;
  const askers = new Set(soft.filter((e) => e.kind === "mail").map((e) => e.src)).size;
  const jobs = soft.filter((e) => e.kind === "service").length;
  const parts = [];
  if (askers) parts.push(`${askers} awaiting a reply`);
  if (jobs) parts.push(`${jobs} job${jobs === 1 ? "" : "s"} in flight`);

  const wrap = document.createElement("details");
  wrap.className = "soft-await";
  const sum = document.createElement("summary");
  sum.textContent = `${parts.join(" · ")} — not a problem · tap for detail`;
  wrap.appendChild(sum);

  for (const e of soft) {
    const row = document.createElement("div");
    row.className = "row";
    const isSvc = e.kind === "service";
    // For a service edge the why is "queued job (being served): <text>" — keep only the text.
    const jobText = isSvc ? (e.why || "").replace(/^[^:]*:\s*/, "") : "";
    const sub = isSvc
      ? "⚙️ job in flight — being served" + (jobText ? `: ${esc(jobText)}` : "")
      : "💬 open question — awaiting a reply";
    row.innerHTML =
      `<div class="row-body">` +
      `<div class="row-title">${esc(e.src)} → ${esc(e.dst)}</div>` +
      `<div class="row-sub" style="white-space:normal">${sub}</div>` +
      `</div><span class="row-age">${ago(e.age)}</span>`;
    wrap.appendChild(row);
  }
  return wrap;
}

function renderBlocked() {
  const host = $("blocked");
  const w = ops.waiting || {};
  const hard = (w.edges || []).filter((e) => e.hard);
  const bits = [];

  // Fleet health FIRST (holobench): an identity collision or a dead reader is a "a human must
  // act" condition, more urgent than a soft stall. Both were invisible for hours until now.
  for (const c of ops.collisions || []) {
    const el = document.createElement("div");
    el.className = "card card-hot";
    // Show what each session is doing (last-active + preview) so Kyle can tell which to keep.
    const recent = (c.recent || []).map((t, i) =>
      `<div class="row-sub" style="white-space:normal;margin-top:6px">` +
      `<b style="color:#e5c07b">#${i + 1} · active ${ago(t.age)} ago</b> — ${esc((t.preview || t.title || "(no preview)").slice(0, 110))}</div>`
    ).join("");
    el.innerHTML =
      `<div class="card-who">⚠️ Identity collision</div>` +
      `<div class="row-sub" style="white-space:normal">${c.count} live sessions post as [${esc(c.member)}] — a reply can reach the wrong one.</div>` +
      recent +
      `<div class="row-sub" style="white-space:normal;margin-top:6px">Both are live. Keep the one doing the work you want, close the other — or coordinate explicitly if deliberate. In a shared repo a git add -A can also sweep the other's work into your commit.</div>`;
    bits.push(el);
  }
  for (const r of ops.lost_rc || []) {
    const el = document.createElement("div");
    el.className = "card card-hot";
    // §3.4.1 (rt1180): alive but gone from the phone app -> looks crashed -> relaunched into a
    // duplicate. Tell Kyle to RECONNECT, not relaunch — the whole point of the alarm.
    el.innerHTML =
      `<div class="card-who">📵 ${esc(r.member)} — alive but lost /RC</div>` +
      `<div class="row-sub" style="white-space:normal">Gone from the phone's Claude app ${r.lost_rc_minutes}m ago, but the process is running.</div>` +
      (r.preview ? `<div class="row-sub" style="white-space:normal;margin-top:6px">Last: ${esc((r.preview || "").slice(0, 110))}</div>` : "") +
      `<div class="row-sub" style="white-space:normal;margin-top:6px">Reconnect it (/rc) — do NOT relaunch, or you'll put a second session in the same repo.</div>`;
    bits.push(el);
  }
  for (const s of (ops.silent || []).filter((x) => x.dead)) {
    const el = document.createElement("div");
    el.className = "card card-hot";
    const who = (s.open_ask_from || s.addressed_by || []).join(", ") || "someone";
    el.innerHTML =
      `<div class="card-who">💀 ${esc(s.tag)} isn't running</div>` +
      `<div class="row-sub" style="white-space:normal">${esc(who)} has ${s.open_ask_count} open question${s.open_ask_count === 1 ? "" : "s"} waiting on it (${silenceLabel(s.silent_for)}).</div>` +
      `<div class="row-sub" style="white-space:normal;margin-top:6px">Relaunch it or it stays stuck.</div>`;
    bits.push(el);
  }

  // STALE READER (image_gen): a LIVE session sitting on mail addressed to it. The backend does
  // not trigger on cursor age — raw age fires on every running session — so anything here is
  // already the harm case: someone is talking to a session that is up and not listening.
  for (const c of ops.stale_cursors || []) {
    const el = document.createElement("div");
    el.className = "card";
    const who = (c.senders || []).join(", ") || "someone";
    const n = c.directed_unread;
    el.innerHTML =
      `<div class="card-who">📪 ${esc(c.tag)} isn't reading its mail</div>` +
      `<div class="row-sub" style="white-space:normal">${n} message${n === 1 ? "" : "s"} addressed ` +
      `to it, oldest ${esc(ago(c.unread_age))}, from ${esc(who)}.</div>` +
      `<div class="row-sub" style="white-space:normal;margin-top:6px">Running; cursor at ` +
      `${esc(c.cursor_ts)}. Nudge it, or run /msg-check.</div>`;
    bits.push(el);
  }

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
    const ck = [...c.nodes].sort().join("|");
    const btn = document.createElement("button");
    btn.className = "btn btn-primary";
    btn.style.width = "100%";
    btn.style.marginTop = "12px";
    btn.disabled = told.has(ck);
    btn.textContent = told.has(ck)
      ? "✅ Told them — give them a minute"
      : (c.deadlock ? "Tell them it's a deadlock" : "Tell them they're both waiting");
    btn.addEventListener("click", async () => {
      if (told.has(ck)) return;
      told.add(ck);                       // state, not DOM — survives the next render
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
        told.delete(ck);                  // it never landed — let him try again
        btn.textContent = e.status === 409 ? "Already resolved"
          : e.status === 429 ? "Already told them"
          : `Failed: ${e.message}`;
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

  // The soft "awaiting" edges are never trouble (a healthy fleet always has some), so they stay
  // subordinate — but they're now visible and honestly labeled, whether or not something is stuck.
  const soft = softAwaitingNode(w);

  if (!bits.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.innerHTML = `<div class="empty-big">👍</div>Nobody is stuck.`;
    host.replaceChildren(...(soft ? [empty, soft] : [empty]));
    return;
  }
  if (soft) bits.push(soft);
  host.replaceChildren(...bits);
}

/* ---- RESOURCES -------------------------------------------------------
   Shared fleet resources at a glance: EVKs/boards, the GPU, and services
   (image_gen …). For each: who holds it, in what mode, how long it has left,
   and its reservation queue. Read-only — reserving is a session's job on the
   bus; this is the "who has what" view Kyle asked for. */
function renderResources() {
  const host = $("resources");
  if (!host) return;
  const res = (ops && ops.resources) || [];
  const svcs = (ops && ops.services) || [];
  if (!res.length && !svcs.length) {
    host.innerHTML = `<div class="empty">No shared resources defined yet.<br>` +
      `Sessions register boards, GPUs and services on the bus.</div>`;
    return;
  }
  const nodes = res.map(resourceRow);
  if (svcs.length) {
    const sep = document.createElement("div");
    sep.className = "fleet-sep";
    sep.textContent = "🛠 Services";
    nodes.push(sep, ...svcs.map(serviceRow));
  }
  host.replaceChildren(...nodes);
}

function resourceRow(r) {
  const el = document.createElement("div");
  el.className = "row res-row";
  const lease = r.lease;
  let pill, detail = "";
  if (!lease) {
    pill = `<span class="pill pill-ok">FREE</span>`;
  } else if (lease.offered) {
    pill = `<span class="pill pill-offer">OFFERED</span>`;
    detail = `→ ${esc(bare(lease.owner))} · ~${ago(lease.remaining)} to claim`;
  } else {
    const cls = lease.mode === "hard" ? "pill-hard" : "pill-soft";
    pill = `<span class="pill ${cls}">${esc(String(lease.mode || "").toUpperCase())}</span>`;
    detail = `${esc(bare(lease.owner))} · ${ago(lease.remaining)} left`;
    if (lease.orphan_suspect) {
      detail += ` · <span class="res-warn">⚠ owner offline ${ago(lease.owner_offline_seconds)}</span>`;
    }
  }
  const q = (lease && lease.queue) || [];
  const queueLine = q.length
    ? `<div class="res-queue">⏳ ${q.length} queued: ${esc(q.map(bare).join(", "))}</div>` : "";
  const jobLine = lease && lease.job ? `<div class="row-sub res-job">${esc(lease.job)}</div>` : "";
  el.innerHTML =
    `<div class="row-body">` +
    `<div class="row-title">🎛 ${esc(r.label || r.name)} ${pill}</div>` +
    (detail ? `<div class="row-sub">${detail}</div>` : "") +
    jobLine + (r.smi ? gpuMeta(r.smi) : "") + queueLine +
    `</div>`;
  // The asset card — how to reach + set up this resource (access / setup / gotchas).
  if (r.card) {
    const b = document.createElement("button");
    b.className = "btn btn-sm res-card-btn";
    b.textContent = r.card.has_access ? "🔑 Access & setup" : "📇 Card";
    b.onclick = () => showResourceCardM(r);
    el.querySelector(".row-body").appendChild(b);
  }
  // An orphan lease (owner's session offline) is the one resource state a HUMAN must clear —
  // the desktop had a reclaim button, the phone didn't (you saw the warning, couldn't act).
  if (lease && lease.orphan_suspect) {
    const b = document.createElement("button");
    b.className = "btn btn-sm res-reclaim";
    b.textContent = "Reclaim";
    b.onclick = () => reclaimResource(r.name, b);
    el.querySelector(".row-body").appendChild(b);
  }
  return el;
}

// Hand an orphaned lease to the next in queue (or free it). Two-tap confirm (mobile-friendly,
// no jarring dialog). The backend refuses (409) unless IT flagged the lease as an orphan —
// and if it refuses, we show WHY (owner may be live) rather than a bare "Failed".
async function reclaimResource(name, btn) {
  if (btn.dataset.armed !== "1") {
    btn.dataset.armed = "1";
    btn.textContent = "Tap again to reclaim";
    setTimeout(() => {
      if (btn.dataset.armed === "1") { btn.dataset.armed = ""; btn.textContent = "Reclaim"; }
    }, 3000);
    return;
  }
  btn.dataset.armed = "";
  btn.disabled = true;
  btn.textContent = "Reclaiming…";
  try {
    const d = await api(`/api/resources/${encodeURIComponent(name)}/reclaim`, { method: "POST" });
    const res = String(d.result || "");
    btn.textContent = res.startsWith("offered:") ? `Handed to ${bare(res.slice(8))}` : "Freed";
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Reclaim";
    const row = btn.closest(".res-row");
    if (row) {
      let note = row.querySelector(".reclaim-note");
      if (!note) {
        note = document.createElement("div");
        note.className = "row-sub res-warn reclaim-note";
        row.querySelector(".row-body").appendChild(note);
      }
      // The 409 reason ("owner's session is live / not offline long enough") is the point.
      note.textContent = e.status === 409 ? e.message : `Couldn't reclaim: ${e.message}`;
    }
  }
  setTimeout(refresh, 1500);
}

function gpuMeta(smi) {
  const util = Math.max(0, Math.min(100, Math.round(smi.util || 0)));
  const gb = (mb) => (mb / 1024).toFixed(mb >= 10240 ? 0 : 1);
  return `<div class="gpu-meta">${esc(smi.name || "GPU")} · ${util}% · ` +
    `${gb(smi.mem_used || 0)}/${gb(smi.mem_total || 0)} GB` +
    `<div class="gpu-bar"><span style="width:${util}%"></span></div></div>`;
}

function serviceRow(s) {
  const el = document.createElement("div");
  el.className = "row res-row";
  let pill, detail = "";
  const job = (j) => (typeof j === "string" ? j : (j && (j.job || j.desc || j.tag)) || "a job");
  if (s.held) {
    pill = `<span class="pill pill-hard">HELD</span>`;
    detail = esc(s.hold_reason || "held for you — will resume after the current job");
  } else if (s.serving) {
    pill = `<span class="pill pill-soft">SERVING</span>`;
    detail = esc(job(s.serving));
  } else {
    pill = `<span class="pill pill-ok">IDLE</span>`;
  }
  const q = s.queue || [];
  const queueLine = q.length
    ? `<div class="res-queue">⏳ ${q.length} job${q.length > 1 ? "s" : ""} queued</div>` : "";
  el.innerHTML =
    `<div class="row-body">` +
    `<div class="row-title">🛠 ${esc(s.name)} ${pill}</div>` +
    (detail ? `<div class="row-sub">${detail}</div>` : "") +
    queueLine +
    `</div>`;
  // The control Kyle didn't have: a service sitting IDLE on a queued job (its serve-wake was
  // lost — Conductor down when the job landed, or it was busy and never came back). Conductor
  // now auto-re-wakes a stale head, but this is the manual override for the fresh case and for
  // "start it NOW". Only shown when there's work AND it's idle — nothing to kick otherwise.
  if (q.length && !s.held && !s.serving) {
    const row = document.createElement("div");
    row.className = "btn-row";
    const go = document.createElement("button");
    go.className = "btn btn-primary";
    go.textContent = "▶ Serve next";
    go.addEventListener("click", async () => {
      go.disabled = true;                 // the row rebuilds on refresh; this only covers the in-flight
      go.innerHTML = '<span class="spin"></span> Nudging…';
      try {
        const r = await api(`/api/services/${encodeURIComponent(s.name)}/nudge`, { method: "POST" });
        go.textContent = r && r.ok ? "Nudged ✓" : (r && r.result) || "No live session";
      } catch (e) {
        go.textContent = `Failed: ${e.message}`;
      }
    });
    row.appendChild(go);
    el.appendChild(row);
  }
  return el;
}

/* The Projects tab (slice 4b): a READ-ONLY glance at every project — state, job progress, spend.
 * NOT the interactive DAG (that's the desktop workbench, by the /m needs-you-console philosophy);
 * just enough to check in. Everything that needs a tap (approve a plan, answer an escalation) still
 * lives in the Inbox. */
const _humanTok = (n) => {
  n = n || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "K";
  return String(n);
};
const _PSTATE = { draft: "#6e7681", nominating: "#8957e5", planning: "#8957e5",
                  plan_review: "#d29922", active: "#3fb950" };

function renderProjects() {
  const host = $("projects-list");
  if (!host) return;
  const ps = ops.all_projects || [];
  if (!ps.length) {
    host.innerHTML = `<div class="empty"><div class="empty-big">🗂</div>No projects yet.</div>`;
    return;
  }
  host.replaceChildren(...ps.map((p) => {
    const el = document.createElement("div");
    el.className = "card";
    const jc = p.job_counts || {};
    const done = jc.done || 0, total = jc.total || 0;
    const jobpct = total ? Math.round(100 * done / total) : 0;
    const attn = p.needs === "approve-plan" ? '<span class="pill">📋 approve</span>'
      : (p.open_kyle > 0 ? `<span class="pill">🚩 ${p.open_kyle}</span>` : "");

    let budget = "";
    if (p.ceiling) {
      const pct = Math.min(100, p.spend_pct || 0);
      const cls = p.over_budget ? "over" : (p.budget_warn ? "warn" : "");
      budget = `<div class="mp-bar ${cls}"><div class="mp-fill" style="width:${pct}%"></div></div>`
        + `<div class="row-sub">💰 ${_humanTok(p.spend)} / ${_humanTok(p.ceiling)} (${p.spend_pct}%)`
        + `${p.over_budget ? " · at cap — dispatch held" : (p.budget_warn ? " · warn" : "")}</div>`;
    } else if (p.spend) {
      budget = `<div class="row-sub">💰 ${_humanTok(p.spend)} tokens · no cap</div>`;
    }

    const leadTxt = `lead ${esc(bare(p.lead) || "—")}`
      + (p.lead_offline ? ' · <b class="mp-bad">lead offline</b>' : "");
    el.innerHTML =
      `<div class="card-head"><span class="card-who">`
      + `<span class="mp-dot" style="background:${_PSTATE[p.state] || "#6e7681"}"></span>${esc(p.id)}</span>`
      + `<span class="row-age">${esc(p.state)}</span></div>`
      + `<div class="row-sub" style="white-space:normal">${esc((p.goal || "").slice(0, 90))}</div>`
      + (total
          ? `<div class="mp-bar"><div class="mp-fill ok" style="width:${jobpct}%"></div></div>`
            + `<div class="row-sub">${done}/${total} jobs done · ${leadTxt}</div>`
          : `<div class="row-sub">no jobs yet · ${leadTxt}</div>`)
      + budget
      + (attn ? `<div class="mp-attn">${attn}</div>` : "");
    return el;
  }));
}

// ---------------------------------------------------------------- tabs
const PANES = ["inbox", "fleet", "auto", "blocked", "resources", "projects"];

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
  const on = st.state === "on";

  // When it's ON, the explainer has done its job and becomes permanent clutter. Collapse to
  // one line — but Test stays reachable, because you need it exactly when something has gone
  // wrong and you're trying to tell "the pipe is dead" from "the fleet is just quiet".
  $("notif-setup").hidden = on;
  $("notif-on").hidden = !on;

  notifState.textContent = st.text;
  notifBtn.hidden = on || ["unsupported", "insecure", "denied"].includes(st.state);
  notifBtn.textContent = "Turn on notifications";
  notifBtn.dataset.mode = "enable";
}

function notifMsg(text) {
  const el = $("notif-msg");
  if (!el) return;
  el.textContent = text || "";
  el.hidden = !text;
}

async function disableNotifications() {
  const reg = await navigator.serviceWorker.getRegistration("/m");
  const sub = reg && (await reg.pushManager.getSubscription());
  if (sub) {
    // Tell the server FIRST. If we only unsubscribed locally, the backend would keep a dead
    // endpoint and keep pushing into it — every send failing silently, forever.
    await api("/api/webpush/unsubscribe", {
      method: "POST",
      body: JSON.stringify({ endpoint: sub.endpoint }),
    }).catch(() => {});
    await sub.unsubscribe();
  }
  await paintNotif();
  notifMsg("Notifications off. Nothing will reach this device until you turn them back on.");
}

$("notif-test")?.addEventListener("click", async (e) => {
  e.target.disabled = true;
  notifMsg("Sending…");
  try {
    const r = await api("/api/webpush/test", { method: "POST" });
    notifMsg(r.sent
      ? `Sent to ${r.sent} device(s) — it should appear now. If it doesn't, your phone is
         blocking it, not Conductor.`.replace(/\s+/g, " ")
      : "Couldn't deliver. Turn them off and on again.");
  } catch (err) {
    notifMsg(`Failed: ${err.message}`);
  } finally {
    e.target.disabled = false;
  }
});

$("notif-off")?.addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    await disableNotifications();
  } catch (err) {
    notifMsg(`Failed: ${err.message}`);
  } finally {
    e.target.disabled = false;
  }
});

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
      await enableNotifications();
      notifMsg("On. Try Test to make sure it actually reaches you.");
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

// --- Wind down (ordered fleet shutdown; the phone overlay) -------------------
// A session is NEVER closed until it posts a VERIFIED ack; asking/busy are surfaced,
// never closed. Close is a two-tap arm (never one-tap-destructive on a phone).
const WD_M = {
  "wound-down": { i: "✅", t: "wound down — safe to close", c: "rb-live" },
  "asking":     { i: "❓", t: "asking YOU — answer it (never closed)", c: "rb-blocked" },
  "busy":       { i: "⏳", t: "busy — waited for, not interrupted", c: "rb-present" },
  // Split in two (Kyle, 2026-08-05): "flushing" meant both "actively persisting" and "woken and
  // did nothing", and the sweep button counted the combined total — so it offered to close
  // sessions that were mid-flush.
  "flushing":     { i: "…", t: "flushing — persisting its state (active since the call)", c: "rb-clone" },
  "idle-unacked": { i: "🔸", t: "idle — nothing since the call, not yet acked", c: "rb-blocked" },
  "restarted":    { i: "🔄", t: "restarted since this wind-down — not part of it", c: "rb-present" },
};
let wdCloseArmed = false;
let wdIdleArmed = false;

function renderWinddownM() {
  const wd = (ops && ops.winddown) || { active: false };
  const cards = $("winddown-cards");
  if (!cards) return;
  const beginB = $("winddown-begin"), closeB = $("winddown-closebtn"), cancelB = $("winddown-cancel");
  if (!wd.active) {
    $("winddown-note").textContent =
      "Broadcasts the ordered protocol to every session; each persists itself (findings, memory, commits, leases) and posts a VERIFIED ack — the bus checks git + leases on disk, it does not take the session's word. Nothing closes without that ack plus your tap.";
    cards.innerHTML = "";
    $("winddown-status").textContent = "No wind-down in progress.";
    beginB.hidden = false; beginB.disabled = false;
    closeB.hidden = true; cancelB.hidden = true; wdCloseArmed = false;
    return;
  }
  const c = wd.counts || {};
  $("winddown-note").innerHTML =
    `Called by <b>${esc(wd.initiator || "?")}</b>. A session asking you or busy is <b>never</b> closed — only verified-acked ones are.`;
  $("winddown-status").textContent =
    `✅ ${c["wound-down"] || 0} · … ${c["flushing"] || 0} flushing · 🔸 ${c["idle-unacked"] || 0} idle · `
    + `⏳ ${c["busy"] || 0} busy · ❓ ${c["asking"] || 0} asking`;
  cards.innerHTML = "";
  for (const s of (wd.sessions || [])) {
    const l = WD_M[s.state] || { i: "?", t: s.state, c: "" };
    const el = document.createElement("div");
    el.className = "card wd-card";
    el.innerHTML =
      `<div class="recon-cardhead"><span class="recon-badge ${l.c}">${l.i}</span> <b>${esc(s.tag)}</b></div>`
      + `<div class="row-sub" style="white-space:normal">${l.t}`
      + (s.manager ? ` · <b>running this wind-down — never closed</b>` : "")
      + (s.nudges ? ` · nudged ${s.nudges}×` : "")
      + (s.summary ? ` — “${esc(s.summary)}”` : "")
      + (s.unpushed ? ` · ${s.unpushed} unpushed` : "") + `</div>`;
    cards.appendChild(el);
  }
  const closable = wd.closable || 0;
  beginB.hidden = true; cancelB.hidden = false; closeB.hidden = false;
  closeB.disabled = closable === 0;
  if (!wdCloseArmed) closeB.textContent = closable ? `Close wound-down (${closable})` : "Close wound-down";
  // Was counts["flushing"], which after the split would offer to close sessions that are
  // mid-flush AND would include the wind-down's own driver. The backend computes exactly what
  // the sweep will touch; the button must show that number and no other.
  const idle = wd.idle_closable || 0;
  const idleB = $("winddown-closeidle");
  if (idleB) {
    idleB.hidden = idle === 0;
    if (!wdIdleArmed) idleB.textContent = idle ? `Close idle (${idle})` : "Close idle";
  }
}

function openWinddownM() { $("winddown-overlay").hidden = false; wdCloseArmed = false; renderWinddownM(); }
$("winddown-open")?.addEventListener("click", openWinddownM);
$("winddown-close-x")?.addEventListener("click", () => { $("winddown-overlay").hidden = true; wdCloseArmed = false; });

$("winddown-begin")?.addEventListener("click", async () => {
  const b = $("winddown-begin"); b.disabled = true;
  $("winddown-status").textContent = "Broadcasting wind-down…";
  try {
    const r = await api("/api/shutdown", { method: "POST" });
    $("winddown-status").textContent =
      `Sent. Woke ${r.woke?.length || 0}; ${r.skipped?.length || 0} busy/asking get it when they pause.`;
  } catch (e) { $("winddown-status").textContent = `Failed: ${e.message}`; b.disabled = false; }
  setTimeout(refresh, 1200);
});

$("winddown-cancel")?.addEventListener("click", async () => {
  try { await api("/api/shutdown/clear", { method: "POST" }); $("winddown-status").textContent = "Cancelled; fleet resumes."; }
  catch (e) { $("winddown-status").textContent = `Failed: ${e.message}`; }
  wdCloseArmed = false; setTimeout(refresh, 1000);
});

$("winddown-closebtn")?.addEventListener("click", async () => {
  const n = (ops && ops.winddown && ops.winddown.closable) || 0;
  if (!n) return;
  const b = $("winddown-closebtn");
  if (!wdCloseArmed) {                       // two-tap arm
    wdCloseArmed = true;
    b.textContent = `Tap again to close ${n} with /exit`;
    setTimeout(() => { if (wdCloseArmed) { wdCloseArmed = false; renderWinddownM(); } }, 4000);
    return;
  }
  wdCloseArmed = false; b.disabled = true;
  $("winddown-status").textContent = "Closing wound-down sessions…";
  try {
    const r = await api("/api/shutdown/close", { method: "POST" });
    const snap = r.snapshot?.ok ? " DR roster refreshed." : "";
    $("winddown-status").textContent =
      `Closed ${r.closed?.length || 0}${r.refused?.length ? `, refused ${r.refused.length}` : ""}.` + snap;
  } catch (e) { $("winddown-status").textContent = `Failed: ${e.message}`; }
  setTimeout(refresh, 1200);
});

$("winddown-closeidle")?.addEventListener("click", async () => {
  const n = (ops && ops.winddown && ops.winddown.idle_closable) || 0;
  if (!n) return;
  const b = $("winddown-closeidle");
  if (!wdIdleArmed) {                          // two-tap arm — this one is NOT verified-clean
    wdIdleArmed = true;
    b.textContent = `⚠ ${n} are UNVERIFIED — tap again to /exit them`;
    setTimeout(() => { if (wdIdleArmed) { wdIdleArmed = false; renderWinddownM(); } }, 4500);
    return;
  }
  wdIdleArmed = false; b.disabled = true;
  $("winddown-status").textContent = "Closing idle stragglers (unverified)…";
  try {
    const r = await api("/api/shutdown/close-idle", { method: "POST" });
    const snap = r.snapshot?.ok ? " DR roster refreshed." : "";
    $("winddown-status").textContent =
      `Closed ${r.closed?.length || 0} idle (unverified)${r.skipped?.length ? `, skipped ${r.skipped.length} busy/asking` : ""}.` + snap;
  } catch (e) { $("winddown-status").textContent = `Failed: ${e.message}`; b.disabled = false; }
  setTimeout(refresh, 1200);
});

// --- Broadcast: message the whole fleet as operator (the phone's Compose) ----
const bcastText = $("bcast-text");
function bcastRefresh() { const b = $("bcast-go"); if (b) b.disabled = !(bcastText && bcastText.value.trim()); }
$("bcast-open")?.addEventListener("click", () => {
  $("bcast-overlay").hidden = false;
  $("bcast-status").textContent = "";
  bcastRefresh();
  setTimeout(() => bcastText?.focus(), 50);
});
$("bcast-x")?.addEventListener("click", () => { $("bcast-overlay").hidden = true; });
bcastText?.addEventListener("input", bcastRefresh);
$("bcast-go")?.addEventListener("click", async () => {
  const text = (bcastText.value || "").trim();
  if (!text) return;
  const b = $("bcast-go"); b.disabled = true;
  $("bcast-status").textContent = "Sending to all…";
  try {
    // recipients:[] => a to-all broadcast, sent as the operator sender tag (server side).
    await api("/api/bus/send", { method: "POST", body: JSON.stringify({ text, recipients: [], ping: false }) });
    $("bcast-status").textContent = "✅ Sent to the whole fleet as [operator].";
    bcastText.value = "";
    setTimeout(() => { $("bcast-overlay").hidden = true; }, 900);
  } catch (e) {
    $("bcast-status").textContent = `Failed: ${e.message}`;
    b.disabled = false;
  }
});
