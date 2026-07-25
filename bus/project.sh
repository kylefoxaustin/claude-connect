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

_project_me() { _coord_plain "$TAG" 2>/dev/null || printf '%s' "$TAG"; }

project_dispatch() {
  local verb="${1:-list}"; shift 2>/dev/null || true
  local PROJECT_ROOT="${PROJECT_STATE_DIR:-$COORD_ROOT/projects}"   # lazy: COORD_ROOT set by call time
  mkdir -p "$PROJECT_ROOT" 2>/dev/null || true
  # Canonicalize the session-name argument (nominate <id> <session>, suggest <id> <who> …) the same
  # way _project_me canonicalizes the actor's own tag — else a nominee's own accept won't match the
  # stored lead. nominate: $2 is the session; suggest: $2 is the suggested session.
  if [ "$verb" = "nominate" ] && [ -n "$2" ]; then set -- "$1" "$(_coord_plain "$2")" "${@:3}"; fi
  if [ "$verb" = "suggest" ] && [ -n "$2" ]; then set -- "$1" "$(_coord_plain "$2")" "${@:3}"; fi
  local STDIN=""
  if [ "$verb" = "plan" ]; then STDIN="$(cat 2>/dev/null || true)"; fi
  ( flock 9
    PROJECT_ROOT="$PROJECT_ROOT" PROJECT_ME="$(_project_me)" PROJECT_NOW="$(date +%s)" \
    PROJECT_STDIN="$STDIN" \
    python3 - "$verb" "$@" <<'PYEOF'
import json, os, sys, time

ROOT = os.environ["PROJECT_ROOT"]
ME   = os.environ.get("PROJECT_ME", "") or "?"
NOW  = int(os.environ.get("PROJECT_NOW") or 0)
argv = sys.argv[1:]
verb = argv[0] if argv else "list"

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
         "plan": None, "plan_status": "none", "plan_notes": None,
         "jobs": [], "issues": [], "log": []}
    logline(p, "created")
    save(p); print("✅ project '%s' created. Next: project nominate %s <session>" % (pid, pid))
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

die("unknown verb '%s'" % verb, 2)
PYEOF
  ) 9>"$PROJECT_ROOT/.lock"
}
