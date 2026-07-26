#!/usr/bin/env bash
# project.sh — the Project Layer, slice 1: project object + nomination handshake + plan gate.
# (docs/PROJECT_LAYER.md). Sourced by bus.sh alongside order.sh.
#
# A PROJECT is lead-owned multi-session work: the operator names a goal + nominates a lead; the
# nominee accepts/declines/suggests-another (§3a, with the goal+scope visible before committing);
# the lead drafts a PLAN; the operator approves it (Gate #1, §4) before any work fans out. Jobs
# (as orders), the decision-shield, and token governance are later slices — the record reserves
# room for them. Projects live in $COORD_ROOT/projects/<id>.json; every mutation is atomic under
# one flock, same as orders.
#
#   project new <id> <goal…>          create a project (operator)
#   project nominate <id> <session>   nominate a lead — goal+scope go with it (operator)
#   project accept <id>               nominee takes the lead (must BE the nominee)
#   project decline <id> <reason…>    nominee declines → back to operator
#   project suggest <id> <who> <why…> nominee suggests another (advisory) → back to operator
#   project plan <id>                 lead submits a plan on STDIN (the job decomposition)
#   project approve <id>              operator approves the plan → project goes active (Gate #1)
#   project revise <id> <notes…>      operator sends the plan back with notes
#   project status <id> | project list
#
# Slice 2 — jobs, the dependency DAG, and dispatch-as-orders (§6):
#   project job add <id> <job> to:<who> path:<dir> files:<a,b> [deps:<x,y>] [size:S|M|L] \
#                              [accept:<test>] -- <desc…>    lead adds a job to the DAG
#   project jobs <id>                 show the DAG: per-job state + readiness (blocked/ready/…)
#   project dispatch <id> <job>       lead dispatches a READY job → places a directed order to:who
#   project sync <id>                 advance the DAG: a job whose order reached CLOSED becomes done
#
# THE DAG (the genuinely new primitive, 93/95/image_gen): a job may depend on earlier jobs and can't
# be dispatched until they're CONFIRMED. Because a job's deps must reference jobs that ALREADY EXIST,
# a cycle is impossible by construction (you cannot add a back-edge to a job created later). Jobs are
# DIRECTED (addressed to one session, §6) — never broadcast, which would reintroduce diffusion. A
# dispatched job IS an order.sh order, so delivery is verified (files land) and the worker can't
# self-grade. Conductor honors the edges AND admits by fleet-global concurrency (§5b) — the bus
# enforces the DAG here; the fleet-load throttle lives in Conductor.
#
# Slice 3 — decision routing, the shield (§4a):
#   project decide <id> [job:<j>] <text…>     LOG a technical decision made on Kyle's behalf (audit)
#   project escalate <id> <eid> [job:<j>] [sev:<safety|security|data-loss|premise>] \
#            [deny:<scope|budget|goal|risk|irreversible>]   + STDIN body → raise a decision
#   project answer <id> <eid> <answer…>       resolve an escalation (lead→lead-bound, Kyle→Kyle-bound)
#   project forward <id> <eid> [deny:<d>]     + STDIN why → the lead pushes a lead-bound one to Kyle
#   project escalations <id> [--open]         list escalations
#
# THE ROUTING AXIS (§4a): TECHNICAL/DOMAIN calls the WORKER decides+logs (`decide`) — pushing them up
# inverts expertise. PROJECT/COORDINATION calls go to the LEAD. The ESCALATE-ALWAYS denylist (scope/
# budget/goal/risk/irreversible) and the severity HATCH (safety/security/data-loss/premise) route
# DIRECTLY to Kyle and the lead is STRUCTURALLY BARRED from answering them (target=kyle → the lead's
# `answer` is refused). The escalation SHAPE is Kyle's: question · why(impact) · options · recommendation
# — an AskUserQuestion that lands in the phone decision queue. A lead-timeout auto-forward (Conductor)
# gives latency relief without a self-declared "I'm urgent" category (the hole that would swallow it).

_project_me() { _coord_plain "$TAG" 2>/dev/null || printf '%s' "$TAG"; }

project_dispatch() {
  local verb="${1:-list}"; shift 2>/dev/null || true
  local PROJECT_ROOT="${PROJECT_STATE_DIR:-$COORD_ROOT/projects}"   # lazy: COORD_ROOT set by call time
  local ORDER_ROOT="${ORDER_STATE_DIR:-$COORD_ROOT/orders}"         # jobs are orders (slice 2)
  mkdir -p "$PROJECT_ROOT" 2>/dev/null || true
  # Canonicalize the session-name argument (nominate <id> <session>, suggest <id> <who> …) the same
  # way _project_me canonicalizes the actor's own tag — else a nominee's own accept won't match the
  # stored lead. nominate: $2 is the session; suggest: $2 is the suggested session.
  if [ "$verb" = "nominate" ] && [ -n "$2" ]; then set -- "$1" "$(_coord_plain "$2")" "${@:3}"; fi
  if [ "$verb" = "suggest" ] && [ -n "$2" ]; then set -- "$1" "$(_coord_plain "$2")" "${@:3}"; fi

  # `dispatch` is the one verb that spans two subsystems: it must place a real order.sh order AND
  # flip the job to dispatched, atomically-enough. order_dispatch takes its OWN flock, so we can't
  # nest it inside the project flock; instead: (1) validate readiness + emit the order spec under
  # the project lock, (2) place the order, (3) record the order_id on the job. Order-first would
  # orphan an order if step 3 died; spec-first (mark optimistically) would orphan a job if the
  # order failed. We do check → place → mark, and _dispatch_mark is idempotent on the order_id.
  if [ "$verb" = "dispatch" ]; then
    local pid="${1:-}" jobid="${2:-}"
    if [ -z "$pid" ] || [ -z "$jobid" ]; then echo "usage: project dispatch <id> <job>" >&2; return 1; fi
    local orderid="proj-${pid}__${jobid}"
    local spec; spec="$(project_dispatch _dispatch_check "$pid" "$jobid")"; local rc=$?
    if [ "$rc" -ne 0 ]; then printf '%s\n' "$spec" >&2; return "$rc"; fi
    # spec is \x1f-separated (unit separator): assignee|path|files|accept|desc|prio. \x1f (not tab)
    # because tab is IFS-whitespace and `read` would collapse an empty accept field, shifting prio.
    local assignee path files accept desc prio
    IFS=$'\x1f' read -r assignee path files accept desc prio <<<"$spec"
    [ -z "$prio" ] && prio="background"
    if ! command -v order_dispatch >/dev/null 2>&1; then
      echo "project: order.sh not available — can't dispatch a job as an order." >&2; return 1; fi
    local -a oargs=(place "$orderid" "to:$assignee" "path:$path" "files:$files")
    [ -n "$accept" ] && oargs+=("accept:$accept")   # array so a spaced accept test isn't split
    local placed; placed="$(order_dispatch "${oargs[@]}" 2>&1)"; rc=$?
    if [ "$rc" -ne 0 ]; then printf 'project: order placement failed: %s\n' "$placed" >&2; return 1; fi
    project_dispatch _dispatch_mark "$pid" "$jobid" "$orderid"; rc=$?
    [ "$rc" -ne 0 ] && return "$rc"
    # ⭐ WAKE THE WORKER. Placing an order tells NOBODY (Kyle, 2026-07-25: "job shows dispatched but
    # the worker is quiet"). Post a DIRECTED bus message (to:<assignee>) so Conductor's auto-delivery
    # wakes an idle worker and its prompt-hook surfaces the job — the "never be the courier" rule,
    # applied to job dispatch. Sender is whoever dispatched ($TAG: the lead, or claude-connect when
    # Conductor drives it). Best-effort: a bus-write failure must not un-dispatch a placed order.
    local _bf="${BUS_FILE:-$HOME/Documents/claude-bus/messages.md}"
    if [ -w "$_bf" ] || [ -w "$(dirname "$_bf")" ]; then
      {
        echo ""; echo "## $(date '+%Y-%m-%d %H:%M:%S') [$TAG]"; echo ""
        printf 'to:%s — 📋 Project "%s": job "%s" is assigned to you.\n' "$assignee" "$pid" "$jobid"
        [ -n "$desc" ] && printf '   %s\n' "$desc"
        if [ "$prio" = "urgent" ]; then
          printf '   ⚡ PRIORITY: URGENT — please prioritize this over your own current work.\n'
        else
          printf '   🍃 PRIORITY: BACKGROUND — fit this around your OWN work; do NOT interrupt it, and do NOT ask the operator to choose. High-value, not time-urgent.\n'
        fi
        printf '   Deliverable: %s in %s\n' "$files" "$path"
        printf '   Claim it, do the work, then deliver (it verifies the files landed):\n'
        printf '     ~/.claude/bin/bus.sh order claim %s\n' "$orderid"
        printf '     ~/.claude/bin/bus.sh order deliver %s\n' "$orderid"
      } >> "$_bf" 2>/dev/null \
        && echo "   📨 notified [$assignee] on the bus — it'll be woken to claim the job." \
        || echo "   ⚠ order placed, but couldn't post the wake to the bus ($_bf)." >&2
    fi
    return 0
  fi

  local STDIN=""
  # Read a body from stdin for the form-verbs — but ONLY when stdin is actually piped. Without the
  # tty guard, `project forward … ` with no heredoc blocks on cat forever (and a guard refusal never
  # gets to fire). Piped → read; interactive/no-pipe → empty body, and the verb validates it.
  case "$verb" in
    plan|escalate|forward) [ ! -t 0 ] && STDIN="$(cat 2>/dev/null || true)" ;;
  esac
  ( flock 9
    PROJECT_ROOT="$PROJECT_ROOT" ORDER_ROOT="$ORDER_ROOT" \
    PROJECT_ME="${PROJECT_ME_OVERRIDE:-$(_project_me)}" PROJECT_NOW="$(date +%s)" \
    PROJECT_STDIN="$STDIN" \
    python3 - "$verb" "$@" <<'PYEOF'
import json, os, sys, time

ROOT       = os.environ["PROJECT_ROOT"]
ORDER_ROOT = os.environ.get("ORDER_ROOT", "")
ME   = os.environ.get("PROJECT_ME", "") or "?"
NOW  = int(os.environ.get("PROJECT_NOW") or 0)
argv = sys.argv[1:]
verb = argv[0] if argv else "list"


def plain(t):
    """A tag/to:-token -> canonical bare name, matching bus.sh's _coord_plain (strip [], other:,
    lowercase) so a job's assignee is stored the same way the actor's own tag resolves."""
    t = (t or "").strip()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1]
    if t.startswith("other:"):
        t = t[6:]
    return t.lower()


def jobs_of(p):
    return p.setdefault("jobs", [])


def job_by_id(p, jid):
    return next((j for j in jobs_of(p) if j.get("id") == jid), None)


def deps_done(p, job):
    """True iff every dependency of this job is a job in state 'done'."""
    byid = {j["id"]: j for j in jobs_of(p)}
    return all(byid.get(d, {}).get("state") == "done" for d in job.get("deps", []))


def blocking_deps(p, job):
    byid = {j["id"]: j for j in jobs_of(p)}
    return [d for d in job.get("deps", []) if byid.get(d, {}).get("state") != "done"]


def order_state(oid):
    """Read an order.sh order's state straight off disk (no order_dispatch needed for a read)."""
    if not ORDER_ROOT:
        return None
    try:
        with open(os.path.join(ORDER_ROOT, oid + ".json"), encoding="utf-8") as f:
            return json.load(f).get("state")
    except (OSError, json.JSONDecodeError):
        return None

def path(pid): return os.path.join(ROOT, pid + ".json")

def load(pid):
    try:
        with open(path(pid), encoding="utf-8") as f: return json.load(f)
    except (OSError, json.JSONDecodeError): return None

def save(p):
    tmp = path(p["id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(p, f, indent=2)
    os.replace(tmp, path(p["id"]))

def logline(p, msg): p.setdefault("log", []).append({"ts": NOW, "who": ME, "msg": msg})
def die(msg, code=1): print("project: " + msg, file=sys.stderr); sys.exit(code)

def show(p):
    print("=== project %s === [%s]" % (p["id"], p["state"]))
    print("  goal   : " + (p.get("goal") or "(none)"))
    lead = p.get("lead")
    print("  lead   : %s (%s)" % (lead or "—", p.get("lead_status") or "unassigned"))
    ps = p.get("plan_status", "none")
    print("  plan   : %s%s" % (ps, ("  ⚠ notes: " + p["plan_notes"]) if p.get("plan_notes") else ""))
    if p.get("ceiling"):
        print("  budget : %s output tokens (ceiling)" % "{:,}".format(p["ceiling"]))
    for n in p.get("nominations", []):
        extra = (" → " + n["suggested"]) if n.get("suggested") else ""
        if n.get("reason"): extra += "  (%s)" % n["reason"]
        print("    · %s %s%s" % (n["session"], n["response"], extra))
    if p.get("plan") and verb == "status":
        print("  --- plan ---")
        for ln in p["plan"].splitlines(): print("    " + ln)

# ---- verbs ----
if verb == "list":
    try: files = sorted(f for f in os.listdir(ROOT) if f.endswith(".json"))
    except OSError: files = []
    if not files: print("No projects."); sys.exit(0)
    for f in files:
        p = load(f[:-5])
        if p: print("  %-24s [%s]  lead=%s  %s" % (
            p["id"], p["state"], p.get("lead") or "—", (p.get("goal") or "")[:60]))
    sys.exit(0)

if verb in ("new",):
    if len(argv) < 2: die("usage: project new <id> <goal…>")
    pid = argv[1]; goal = " ".join(argv[2:]).strip()
    if not pid.replace("-", "").replace("_", "").isalnum(): die("id must be alphanumeric/-/_")
    if load(pid): die("project '%s' already exists" % pid)
    p = {"id": pid, "goal": goal, "created_by": ME, "created_epoch": NOW, "state": "draft",
         "lead": None, "lead_status": "unassigned", "nominations": [],
         "plan": None, "plan_status": "none", "plan_notes": None, "ceiling": 0,
         "jobs": [], "issues": [], "log": []}
    logline(p, "created")
    save(p); print("✅ project '%s' created. Next: project nominate %s <session>" % (pid, pid))
    sys.exit(0)

if verb == "job":
    # project job add <pid> <jobid> to:<who> path:<dir> files:<a,b> [deps:<x,y>] [size:S|M|L]
    #                [accept:<test>] -- <desc…>    (only the accepted lead, project active/planning)
    sub = argv[1] if len(argv) > 1 else ""
    if sub != "add":
        die("usage: project job add <id> <jobid> to:<who> path:<dir> files:<a,b> [deps:x,y] -- <desc>")
    rest = argv[2:]
    if len(rest) < 2:
        die("usage: project job add <id> <jobid> to:<who> path:<dir> files:<a,b> [deps:x,y] -- <desc>")
    pid, jid = rest[0], rest[1]
    p = load(pid)
    if p is None:
        die("no project '%s'" % pid)
    if p.get("lead") != ME:
        die("only the accepted lead ([%s]) may add jobs; you are [%s]" % (p.get("lead"), ME))
    if p.get("state") not in ("planning", "plan_review", "active"):
        die("can't add jobs while project is '%s' (need a lead + a plan in progress)" % p.get("state"))
    if not jid.replace("-", "").replace("_", "").isalnum():
        die("job id must be alphanumeric/-/_")
    if job_by_id(p, jid):
        die("job '%s' already exists in project '%s'" % (jid, pid))
    # split kv tokens from the trailing "-- <desc>"
    toks = rest[2:]
    desc = ""
    if "--" in toks:
        i = toks.index("--"); kvtoks = toks[:i]; desc = " ".join(toks[i + 1:]).strip()
    else:
        kvtoks = toks
    kw = {}
    for a in kvtoks:
        if ":" in a:
            k, v = a.split(":", 1); kw[k] = v
    to = plain(kw.get("to", ""))
    jpath = kw.get("path", "")     # NOT `path` — that's the module-level path() fn; rebinding it breaks save()
    files = [f for f in kw.get("files", "").split(",") if f]
    deps = [d for d in kw.get("deps", "").split(",") if d]
    if not to:
        die("job needs to:<session> — a job is DIRECTED to one session, never broadcast")
    if not jpath or not files:
        die("job needs path:<dir> and files:<a,b> — dispatch places a verified order (files must land)")
    # deps must reference jobs that ALREADY exist — this is what makes a cycle impossible.
    unknown = [d for d in deps if not job_by_id(p, d)]
    if unknown:
        die("unknown dep(s): %s — a dependency must be a job already added to this project" % ",".join(unknown))
    if jid in deps:
        die("a job cannot depend on itself")
    # PRIORITY vs the worker's OWN work (slice 7). Default BACKGROUND: "fit this around your own work,
    # don't interrupt" — so a dispatched job stops implicitly demanding the worker drop everything (and
    # then ask the human to arbitrate). URGENT: "please prioritize this over your own work." The wake
    # message states which, so the worker self-arbitrates instead of kicking the decision to Kyle.
    prio = (kw.get("prio", "background") or "background").lower()
    if prio not in ("background", "urgent"):
        die("prio must be 'background' (default — fit around own work) or 'urgent'")
    job = {"id": jid, "to": to, "desc": desc, "deps": deps,
           "size": (kw.get("size", "") or "").upper(), "accept": kw.get("accept", ""),
           "prio": prio, "path": jpath, "files": files, "state": "planned", "order_id": None}
    jobs_of(p).append(job)
    logline(p, "job %s added -> %s (deps: %s)" % (jid, to, ",".join(deps) or "none"))
    save(p)
    print("✅ job '%s' added to '%s' -> [%s]%s. %s" % (
        jid, pid, to, (" (deps: %s)" % ",".join(deps)) if deps else "",
        "Dispatch when ready: project dispatch %s %s" % (pid, jid)))
    sys.exit(0)

# all remaining verbs take an id
if len(argv) < 2: die("usage: project %s <id> …" % verb)
pid = argv[1]; p = load(pid)
if p is None: die("no project '%s'" % pid)

if verb == "status": show(p); sys.exit(0)

if verb == "nominate":
    if len(argv) < 3: die("usage: project nominate <id> <session>")
    who = argv[2]
    p["lead"] = who; p["lead_status"] = "nominated"; p["state"] = "nominating"
    logline(p, "nominated %s as lead" % who)
    save(p)
    print("✅ nominated [%s] to lead '%s'. They should see the goal+scope, then: "
          "project {accept|decline|suggest} %s" % (who, pid, pid))
    sys.exit(0)

# --- lead-side actions: only the nominee may take them ---
if verb in ("accept", "decline", "suggest", "plan"):
    if p.get("lead_status") == "accepted" and verb in ("accept", "decline", "suggest"):
        die("lead already accepted; nothing to respond to")
    if verb in ("accept", "decline", "suggest") and p.get("lead") not in (ME, None) and p.get("lead") != ME:
        die("only the nominee ([%s]) may respond to this nomination; you are [%s]" % (p.get("lead"), ME))
    if verb == "plan" and p.get("lead") != ME:
        die("only the accepted lead ([%s]) may submit the plan; you are [%s]" % (p.get("lead"), ME))

if verb == "accept":
    if p.get("lead_status") != "nominated": die("no open nomination to accept")
    p["lead_status"] = "accepted"; p["state"] = "planning"
    p["nominations"].append({"session": ME, "response": "accepted", "ts": NOW})
    logline(p, "accepted lead")
    save(p); print("✅ [%s] is now lead of '%s'. Draft the plan, then: project plan %s" % (ME, pid, pid))
    sys.exit(0)

if verb == "decline":
    reason = " ".join(argv[2:]).strip() or "(no reason given)"
    p["nominations"].append({"session": ME, "response": "declined", "reason": reason, "ts": NOW})
    p["lead"] = None; p["lead_status"] = "declined"; p["state"] = "draft"
    logline(p, "declined: " + reason)
    save(p); print("↩ [%s] declined. Back to the operator to nominate another." % ME)
    sys.exit(0)

if verb == "suggest":
    if len(argv) < 3: die("usage: project suggest <id> <who> <why…>")
    other = argv[2]; why = " ".join(argv[3:]).strip() or "(no reason given)"
    p["nominations"].append({"session": ME, "response": "suggested", "suggested": other,
                             "reason": why, "ts": NOW})
    p["lead"] = None; p["lead_status"] = "declined"; p["state"] = "draft"
    logline(p, "suggested %s: %s" % (other, why))
    save(p); print("↩ [%s] suggests [%s] (%s). Operator decides — advisory." % (ME, other, why))
    sys.exit(0)

if verb == "plan":
    if p.get("lead_status") != "accepted": die("no accepted lead; can't submit a plan yet")
    text = os.environ.get("PROJECT_STDIN", "").strip()
    if not text: die("plan is empty — pipe it on stdin: project plan %s <<'EOF' … EOF" % pid)
    p["plan"] = text; p["plan_status"] = "submitted"; p["plan_notes"] = None; p["state"] = "plan_review"
    logline(p, "plan submitted (%d chars)" % len(text))
    save(p); print("✅ plan submitted for '%s'. Awaiting operator approval (Gate #1)." % pid)
    sys.exit(0)

# --- operator-side plan gate ---
if verb == "approve":
    if p.get("plan_status") != "submitted": die("no submitted plan to approve (status: %s)" % p.get("plan_status"))
    p["plan_status"] = "approved"; p["state"] = "active"
    logline(p, "plan approved")
    save(p); print("✅ plan approved — '%s' is ACTIVE. (Jobs/dispatch = next slice.)" % pid)
    sys.exit(0)

if verb == "revise":
    notes = " ".join(argv[2:]).strip() or "(revise)"
    p["plan_status"] = "revise"; p["plan_notes"] = notes; p["state"] = "planning"
    logline(p, "plan sent back: " + notes)
    save(p); print("↩ plan for '%s' sent back to the lead with notes." % pid)
    sys.exit(0)

if verb == "budget":
    # Set the project's token CEILING — a hard cap on measured spend (§5). Estimates are theater;
    # this is the scope+ceiling Kyle approves. The lead proposes it (part of the plan); the meter is
    # Conductor's (measured output tokens across the project's members). 0 clears it (meter only).
    if p.get("lead") not in (ME, None) and ME != "operator":
        die("only the lead ([%s]) or the operator may set the budget; you are [%s]" % (p.get("lead"), ME))
    raw = (argv[2] if len(argv) > 2 else "").lower().replace(",", "").strip()
    mult = 1
    if raw.endswith("k"): mult, raw = 1000, raw[:-1]
    elif raw.endswith("m"): mult, raw = 1_000_000, raw[:-1]
    try:
        ceiling = int(float(raw) * mult)
    except ValueError:
        die("usage: project budget <id> <tokens>  (e.g. 2m, 500k, 750000; 0 clears)")
    p["ceiling"] = ceiling
    logline(p, "budget ceiling set to %d output tokens" % ceiling)
    save(p)
    print("💰 budget for '%s' set to %s output tokens%s." % (
        pid, "{:,}".format(ceiling) if ceiling else "0",
        " (cap cleared — meter only)" if not ceiling else " — Conductor stops new dispatch near the cap."))
    sys.exit(0)

# ---- slice 2: the DAG ----
def readiness(p, j):
    if j["state"] == "done":
        return "done"
    if j["state"] == "dispatched":
        return "dispatched"
    return "ready" if deps_done(p, j) else "blocked"

if verb == "jobs":
    js = jobs_of(p)
    if not js:
        print("project '%s' has no jobs yet. Add: project job add %s <jobid> to:<who> …" % (pid, pid))
        sys.exit(0)
    print("=== jobs for %s === [%s]" % (pid, p["state"]))
    for j in js:
        r = readiness(p, j)
        icon = {"done": "✅", "dispatched": "📤", "ready": "▶", "blocked": "⛔"}[r]
        extra = ""
        if r == "blocked":
            extra = "  ⛔ waiting on: " + ",".join(blocking_deps(p, j))
        elif r == "dispatched" and j.get("order_id"):
            extra = "  order:%s (%s)" % (j["order_id"], order_state(j["order_id"]) or "?")
        elif r == "ready":
            extra = "  ▶ dispatchable"
        sz = (" " + j["size"]) if j.get("size") else ""
        pr = " ⚡urgent" if j.get("prio") == "urgent" else ""
        print("  %s %-14s -> [%s]%s%s  deps=%s%s" % (
            icon, j["id"], j.get("to", "?"), sz, pr, ",".join(j.get("deps", [])) or "—", extra))
        if j.get("desc"):
            print("       %s" % j["desc"])
    sys.exit(0)

if verb == "_dispatch_check":
    # internal: validate a job is dispatchable and EMIT its order spec (tab-separated) for the shell
    # to hand to order_dispatch. No write here — placement happens in the shell, then _dispatch_mark.
    jid = argv[2] if len(argv) > 2 else ""
    j = job_by_id(p, jid)
    if j is None:
        die("no job '%s' in project '%s'" % (jid, pid))
    # The lead decides WHAT to dispatch (it built the plan); Conductor (as 'operator') admits WHEN by
    # fleet load and places it on the lead's behalf — so both may dispatch, but no other session.
    if p.get("lead") != ME and ME != "operator":
        die("only the lead ([%s]) may dispatch jobs; you are [%s]" % (p.get("lead"), ME))
    if p.get("state") != "active":
        die("project '%s' is '%s' — approve the plan before dispatching jobs" % (pid, p.get("state")))
    if j["state"] == "dispatched":
        die("job '%s' is already dispatched (order %s)" % (jid, j.get("order_id")))
    if j["state"] == "done":
        die("job '%s' is already done" % jid)
    if not deps_done(p, j):
        die("job '%s' is blocked — waiting on: %s" % (jid, ",".join(blocking_deps(p, j))))
    # emit the order spec (tab-separated) + the desc, for the shell to place the order AND post the
    # directed wake to the assignee. \t and \n can't appear in these fields (ids/paths/one-line desc).
    # Join with the UNIT SEPARATOR (\x1f), NOT a tab: tab is IFS-whitespace, so bash `read` collapses
    # a consecutive run (an empty `accept` field) and shifts every field after it — which silently
    # dropped `prio`. \x1f is non-whitespace, so empty fields survive.
    sys.stdout.write("\x1f".join([j["to"], j["path"], ",".join(j["files"]),
                                  j.get("accept", ""), (j.get("desc", "") or "").replace("\x1f", " "),
                                  j.get("prio", "background")]))
    sys.exit(0)

if verb == "_dispatch_mark":
    jid = argv[2] if len(argv) > 2 else ""
    oid = argv[3] if len(argv) > 3 else ""
    j = job_by_id(p, jid)
    if j is None:
        die("no job '%s'" % jid)
    if j["state"] == "planned":
        j["state"] = "dispatched"; j["order_id"] = oid
        logline(p, "job %s dispatched as order %s -> %s" % (jid, oid, j["to"]))
        save(p)
    print("📤 dispatched job '%s' -> [%s] as order '%s'. The worker claims + delivers; the order "
          "verifies files landed; then project sync %s advances the DAG." % (jid, j["to"], oid, pid))
    sys.exit(0)

if verb == "sync":
    # advance the DAG: any dispatched job whose order reached CLOSED becomes 'done', which may
    # unblock dependents. Conductor calls this each scan; the lead can too. Read-only on orders.
    changed = []
    for j in jobs_of(p):
        if j["state"] == "dispatched" and order_state(j.get("order_id")) == "CLOSED":
            j["state"] = "done"; changed.append(j["id"])
            logline(p, "job %s done (order %s CLOSED)" % (j["id"], j.get("order_id")))
    if changed:
        save(p)
        newly = [j["id"] for j in jobs_of(p) if j["state"] == "planned" and deps_done(p, j)]
        print("✅ %d job(s) completed: %s.%s" % (
            len(changed), ", ".join(changed),
            ("  Now dispatchable: " + ", ".join(newly)) if newly else ""))
    else:
        print("no change — no dispatched job's order has reached CLOSED yet.")
    sys.exit(0)

# ---- slice 3: decision routing (the shield) ----
SEVERITIES = ("safety", "security", "data-loss", "premise")
DENYLIST   = ("scope", "budget", "goal", "risk", "irreversible")

def escs(p):
    return p.setdefault("escalations", [])

def esc_by_id(p, eid):
    return next((e for e in escs(p) if e.get("id") == eid), None)

def parse_esc_body(text):
    """A tiny key: value form on stdin -> the escalation shape. `option:` repeats."""
    q = why = rec = ""
    opts = []
    for ln in (text or "").splitlines():
        k, sep, v = ln.partition(":")
        if not sep:
            continue
        k = k.strip().lower(); v = v.strip()
        if k == "question":
            q = v
        elif k in ("why", "impact"):
            why = v
        elif k in ("option", "opt"):
            if v:
                opts.append(v)
        elif k in ("recommendation", "rec"):
            rec = v
    return q, why, opts, rec

if verb == "decide":
    # the AUDIT LOG (detection): a technical/domain decision made on Kyle's behalf. Any project
    # participant may log; it is a record, not a request — nobody is asked, nothing blocks.
    kw = {}
    words = []
    for a in argv[2:]:
        if a.startswith("job:"):
            kw["job"] = a[4:]
        else:
            words.append(a)
    text = " ".join(words).strip()
    if not text:
        die("usage: project decide <id> [job:<j>] <what you decided and why>")
    p.setdefault("decisions", []).append(
        {"by": ME, "job": kw.get("job", ""), "text": text, "ts": NOW})
    logline(p, "decision logged by %s%s" % (ME, (" [job %s]" % kw["job"]) if kw.get("job") else ""))
    save(p)
    print("📝 logged a technical decision on '%s' (audit trail — Kyle can spot-check it)." % pid)
    sys.exit(0)

if verb == "escalate":
    eid = argv[2] if len(argv) > 2 else ""
    if not eid:
        die("usage: project escalate <id> <eid> [job:<j>] [sev:<…>] [deny:<…>]  (+ body on stdin)")
    if esc_by_id(p, eid):
        die("escalation '%s' already exists" % eid)
    kw = {}
    for a in argv[3:]:
        if ":" in a:
            k, v = a.split(":", 1); kw[k] = v
    sev = (kw.get("sev", "") or "").lower()
    deny = (kw.get("deny", "") or "").lower()
    if sev and sev not in SEVERITIES:
        die("sev must be one of: %s" % ", ".join(SEVERITIES))
    if deny and deny not in DENYLIST:
        die("deny must be one of: %s" % ", ".join(DENYLIST))
    q, why, opts, rec = parse_esc_body(os.environ.get("PROJECT_STDIN", ""))
    if not q:
        die("escalation needs a body on stdin with at least 'question: …'. e.g.\n"
            "  project escalate %s e1 <<'EOF'\n  question: int8 or fp16 here?\n"
            "  why: int8 drops 2%% accuracy\n  option: int8\n  option: fp16\n"
            "  recommendation: fp16\n  EOF" % pid)
    # ROUTING: the denylist and the severity hatch go straight to Kyle and the lead can't answer
    # them; everything else goes to the lead. There is deliberately NO self-declared "urgent".
    target = "kyle" if (sev or deny) else "lead"
    e = {"id": eid, "raised_by": ME, "job": kw.get("job", ""), "question": q, "why": why,
         "options": opts, "recommendation": rec, "severity": sev, "deny": deny,
         "target": target, "state": "open", "answer": "", "answered_by": "",
         "answered_epoch": 0, "created": NOW}
    escs(p).append(e)
    logline(p, "escalation %s raised by %s -> %s%s" % (
        eid, ME, target, (" (%s)" % (sev or deny)) if (sev or deny) else ""))
    save(p)
    route = ("↑ Kyle DIRECTLY (%s) — the lead may not decide this" % (sev or deny)) if target == "kyle" \
            else "→ the lead"
    print("🚩 escalation '%s' raised %s. %s" % (
        eid, route, "It lands in Kyle's decision queue." if target == "kyle"
        else "The lead answers, or forwards it to Kyle if it hits the denylist."))
    sys.exit(0)

if verb == "answer":
    eid = argv[2] if len(argv) > 2 else ""
    e = esc_by_id(p, eid)
    if e is None:
        die("no escalation '%s' in project '%s'" % (eid, pid))
    if e["state"] != "open":
        die("escalation '%s' is already %s" % (eid, e["state"]))
    ans = " ".join(argv[3:]).strip()
    if not ans:
        die("usage: project answer <id> <eid> <the decision>")
    # Kyle (via Conductor, as 'operator') may answer ANY escalation — it's his queue. Otherwise the
    # shield's routing holds: the lead answers only LEAD-bound ones, and is STRUCTURALLY BARRED from
    # Kyle-bound ones (denylist/severity) — which is what gives the denylist its teeth.
    if ME != "operator":
        if e["target"] == "lead" and p.get("lead") != ME:
            die("only the lead ([%s]) may answer a lead-bound escalation; you are [%s]" % (p.get("lead"), ME))
        if e["target"] == "kyle" and p.get("lead") == ME:
            die("escalation '%s' is Kyle's to decide (%s) — the lead may not answer it. "
                "If you meant to weigh in, forward it with your recommendation." % (eid, e["severity"] or e["deny"]))
    e["state"] = "answered"; e["answer"] = ans; e["answered_by"] = ME; e["answered_epoch"] = NOW
    logline(p, "escalation %s answered by %s" % (eid, ME))
    save(p)
    print("✅ escalation '%s' answered by [%s]: %s" % (eid, ME, ans))
    sys.exit(0)

if verb == "forward":
    eid = argv[2] if len(argv) > 2 else ""
    e = esc_by_id(p, eid)
    if e is None:
        die("no escalation '%s'" % eid)
    if p.get("lead") != ME:
        die("only the lead ([%s]) forwards an escalation to Kyle; you are [%s]" % (p.get("lead"), ME))
    if e["state"] != "open":
        die("escalation '%s' is already %s" % (eid, e["state"]))
    kw = {}
    for a in argv[3:]:
        if ":" in a:
            k, v = a.split(":", 1); kw[k] = v
    deny = (kw.get("deny", "") or "").lower()
    if deny and deny not in DENYLIST:
        die("deny must be one of: %s" % ", ".join(DENYLIST))
    why_more = (os.environ.get("PROJECT_STDIN", "") or "").strip()
    e["target"] = "kyle"
    if deny:
        e["deny"] = deny
    if why_more:
        e["why"] = (e.get("why", "") + ("  [lead: " + why_more + "]")).strip()
    logline(p, "escalation %s forwarded to Kyle by %s%s" % (eid, ME, (" (%s)" % deny) if deny else ""))
    save(p)
    print("↑ escalation '%s' forwarded to Kyle's decision queue%s." % (
        eid, (" (%s)" % deny) if deny else ""))
    sys.exit(0)

if verb == "timeout-forward":
    # SYSTEM action (Conductor only): a lead-bound escalation the lead hasn't answered within the
    # timeout auto-escalates to Kyle — §4a's latency relief. There is deliberately NO lead guard and
    # NO worker trigger: only the CLOCK (via Conductor) flips it, so it can't become the self-declared
    # "I'm urgent" category that would swallow the shield.
    eid = argv[2] if len(argv) > 2 else ""
    e = esc_by_id(p, eid)
    if e is None:
        die("no escalation '%s'" % eid)
    if e["state"] != "open" or e["target"] != "lead":
        die("'%s' is not an open lead-bound escalation (state=%s target=%s)" % (eid, e["state"], e["target"]))
    e["target"] = "kyle"; e["timed_out"] = True
    logline(p, "escalation %s auto-escalated to Kyle (lead did not answer in time)" % eid)
    save(p)
    print("⏱ escalation '%s' auto-escalated to Kyle (lead timeout)." % eid)
    sys.exit(0)

if verb == "escalations":
    open_only = "--open" in argv[2:]
    es = [e for e in escs(p) if (not open_only or e["state"] == "open")]
    if not es:
        print("no%s escalations for '%s'." % (" open" if open_only else "", pid))
        sys.exit(0)
    print("=== escalations for %s ===" % pid)
    for e in es:
        icon = "🟢" if e["state"] == "answered" else ("🔴" if e["target"] == "kyle" else "🟡")
        tag = ("↑Kyle" if e["target"] == "kyle" else "→lead")
        mark = (" %s" % (e["severity"] or e["deny"])) if (e["severity"] or e["deny"]) else ""
        print("  %s %-12s %s%s  by %s%s : %s" % (
            icon, e["id"], tag, mark, e["raised_by"],
            (" [job %s]" % e["job"]) if e.get("job") else "", e["question"]))
        if e.get("why"):
            print("       why: %s" % e["why"])
        for o in e.get("options", []):
            print("        - %s" % o)
        if e.get("recommendation"):
            print("       rec: %s" % e["recommendation"])
        if e["state"] == "answered":
            print("       ✅ [%s]: %s" % (e["answered_by"], e["answer"]))
    sys.exit(0)

die("unknown verb '%s'" % verb, 2)
PYEOF
  ) 9>"$PROJECT_ROOT/.lock"
  local _rc=$?
  # WAKE THE NOMINEE. Like dispatch, `nominate` mutates state but told nobody — the nominated lead
  # never learned it was picked (Kyle, 2026-07-25). Post a directed bus message so Conductor's
  # auto-delivery wakes it and its hook surfaces the nomination; it reviews the goal, then accepts.
  if [ "$verb" = "nominate" ] && [ "$_rc" -eq 0 ]; then
    local _who="${2:-}" _pid="${1:-}"
    local _bf="${BUS_FILE:-$HOME/Documents/claude-bus/messages.md}"
    if [ -n "$_who" ] && { [ -w "$_bf" ] || [ -w "$(dirname "$_bf")" ]; }; then
      {
        echo ""; echo "## $(date '+%Y-%m-%d %H:%M:%S') [$TAG]"; echo ""
        printf 'to:%s — 🧭 You are nominated to LEAD project "%s".\n' "$_who" "$_pid"
        printf '   Review the goal + scope, then accept / decline / suggest another:\n'
        printf '     ~/.claude/bin/bus.sh project status %s\n' "$_pid"
        printf '     ~/.claude/bin/bus.sh project accept %s\n' "$_pid"
        printf '     (or) project decline %s "<why>"  ·  project suggest %s <who> "<why>"\n' "$_pid" "$_pid"
      } >> "$_bf" 2>/dev/null
    fi
  fi
  return "$_rc"
}
