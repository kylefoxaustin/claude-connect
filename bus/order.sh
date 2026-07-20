#!/usr/bin/env bash
# Agentic request-delivery — a durable ORDER with a verified-landing lifecycle (image_gen's spec,
# 2026-07-19; ~/.claude/proposals/agentic-delivery/SPEC.md). SOURCE this into bus.sh.
#
# Orders live in $COORD_ROOT/orders/<id>.json; every mutation is atomic under one flock. The whole
# state machine lives in the embedded python (_order_run) so the transitions and actor checks are in
# ONE place, not scattered across shell.
#
# THE LOAD-BEARING INVARIANT (image_gen's #1): `order deliver` READS THE ARTIFACT BACK from the
# address and refuses to move to DELIVERED unless every declared file actually landed. So "delivered"
# is a verified fact, never a claim — the verified-send discipline (the bus two-phase commit) applied
# to service delivery. And the REQUESTER owns the address + acceptance test: a service cannot grade
# its own delivery (the independent-estimator rule).
#
# Lifecycle:  PLACED ─claim→ CLAIMED ─deliver(verified)→ DELIVERED ─accept→ CONFIRMED → CLOSED
#                                          ▲                    └─reject(reasons,rev++)→ COOKING ┘
# No silent transitions: every arrow is an explicit, logged verb, retained in the order's history.

ORDER_REVISION_CEILING="${ORDER_REVISION_CEILING:-5}"   # past this, surface to the human (spec §4)

_order_me() { _coord_plain "$TAG" 2>/dev/null || printf '%s' "$TAG"; }

# order_dispatch <verb> [args...] — all order verbs run through the python state machine under flock.
order_dispatch() {
  local verb="${1:-status}"; shift 2>/dev/null || true
  local ORDER_ROOT="${ORDER_STATE_DIR:-$COORD_ROOT/orders}"   # lazy: COORD_ROOT is set by call time
  mkdir -p "$ORDER_ROOT" 2>/dev/null || true
  ( flock 9
    ORDER_ROOT="$ORDER_ROOT" ORDER_ME="$(_order_me)" ORDER_NOW="$(date +%s)" \
    ORDER_CEIL="$ORDER_REVISION_CEILING" ORDER_VERB="$verb" \
    python3 - "$@" <<'PYEOF'
import json, os, sys, time

ROOT   = os.environ["ORDER_ROOT"]
ME     = os.environ.get("ORDER_ME", "") or "?"
NOW    = int(os.environ.get("ORDER_NOW") or 0)
CEIL   = int(os.environ.get("ORDER_CEIL") or 5)
VERB   = os.environ.get("ORDER_VERB", "status")
ARGS   = sys.argv[1:]

STATES_WORKING = ("CLAIMED", "COOKING")

def die(msg, code=1):
    print(msg); sys.exit(code)

def opath(oid):
    return os.path.join(ROOT, oid + ".json")

def load(oid):
    try:
        with open(opath(oid)) as f: return json.load(f)
    except (OSError, ValueError):
        return None

def save(o):
    p = opath(o["order_id"]); tmp = p + ".tmp"
    with open(tmp, "w") as f: json.dump(o, f, indent=2, sort_keys=True)
    os.replace(tmp, p)

def kv(args):
    """key:value tokens -> dict; bare tokens ignored. Values may contain ':'."""
    d = {}
    for a in args:
        if ":" in a:
            k, v = a.split(":", 1); d[k] = v
    return d

def log(o, event, note=""):
    o.setdefault("history", []).append(
        {"rev": o.get("revision", 0), "event": event, "by": ME, "at": NOW, "note": note})
    o["updated"] = NOW

def require_state(o, *ok):
    if o["state"] not in ok:
        die("order %s is %s — %s needs %s." % (o["order_id"], o["state"], VERB, "/".join(ok)))

def require_actor(o, field, role):
    if o.get(field) not in (ME, None, ""):
        die("only %s (%s) may %s this order — you are %s." % (role, o.get(field), VERB, ME))

# ---- verbs ----
if VERB == "list":
    orders = []
    for fn in sorted(os.listdir(ROOT)) if os.path.isdir(ROOT) else []:
        if fn.endswith(".json"):
            o = load(fn[:-5])
            if o: orders.append(o)
    if not orders: die("No orders.", 0)
    for o in orders:
        print("%-22s %-10s rev%d  %s -> %s  (%d file%s)" % (
            o["order_id"], o["state"], o.get("revision", 0),
            o.get("requester", "?"), o.get("service", "?") or "unclaimed",
            len(o.get("deliverable", {}).get("files", [])),
            "" if len(o.get("deliverable", {}).get("files", [])) == 1 else "s"))
    sys.exit(0)

oid = ARGS[0] if ARGS else ""
if not oid:
    die("usage: bus.sh order <place|claim|deliver|accept|reject|status|list> <order_id> …")
rest = ARGS[1:]
o = load(oid)

if VERB == "status":
    if not o: die("No order '%s'." % oid, 1)
    print(json.dumps(o, indent=2, sort_keys=True)); sys.exit(0)

if VERB == "place":
    if o: die("order '%s' already exists (state %s). Use reject to revise, not place." % (oid, o["state"]))
    kw = kv(rest)
    files = [f for f in kw.get("files", "").split(",") if f]
    path  = kw.get("path", "")
    if not files or not path:
        die("place needs files:a,b,c and path:<dir>. e.g. bus.sh order place tipo-btns "
            "to:image_gen path:/…/antique files:btn.png,btn-down.png format:'512 RGBA' accept:'reads cast-in'")
    o = {
        "order_id": oid, "state": "PLACED", "requester": ME,
        "service": kw.get("to", "") or None, "revision": 0,
        "deliverable": {"files": files, "format": kw.get("format", ""), "spec": kw.get("spec", "")},
        "address": {"type": kw.get("type", "fs-dir"), "path": path},
        "accept_test": {"auto": kw.get("accept", ""), "human": kw.get("human", "")},
        "history": [], "created": NOW, "updated": NOW,
    }
    log(o, "PLACED", "requester=%s -> service=%s" % (ME, o["service"] or "any"))
    save(o)
    die("Placed order '%s' (%d file%s -> %s) addressed to %s. The service claims it, cooks, then "
        "`order deliver` — which verifies the files landed before it can say DELIVERED." % (
        oid, len(files), "" if len(files) == 1 else "s", o["address"]["path"],
        o["service"] or "any capable service"), 0)

if not o:
    die("No order '%s'. (place it first, or check the id.)" % oid, 1)

if VERB == "claim":
    require_state(o, "PLACED")
    if o.get("service") not in (None, "", ME):
        die("order '%s' is addressed to %s, not you (%s)." % (oid, o["service"], ME))
    o["service"] = ME; o["state"] = "CLAIMED"
    kw = kv(rest); eta = kw.get("eta", "")
    log(o, "CLAIMED", ("eta=%s" % eta) if eta else "")
    save(o)
    die("Claimed order '%s'%s. Cook it, then `bus.sh order deliver %s` (it verifies the drop "
        "landed before acking DELIVERED)." % (oid, (" (ETA %s)" % eta) if eta else "", oid), 0)

if VERB == "deliver":
    require_actor(o, "service", "the claiming service")
    require_state(o, *STATES_WORKING)
    # THE INVARIANT: read the artifact back from the address. No file on disk == not delivered.
    addr = o.get("address", {})
    if addr.get("type") != "fs-dir":
        die("deliver: only address.type 'fs-dir' is supported yet (got %r). Other adapters land next slice." % addr.get("type"))
    base = addr.get("path", ""); missing = []
    for fn in o["deliverable"]["files"]:
        fp = os.path.join(base, fn)
        try:
            if not (os.path.isfile(fp) and os.path.getsize(fp) > 0):
                missing.append(fn)
        except OSError:
            missing.append(fn)
    if missing:
        die("NOT DELIVERED — these declared files are missing or empty at %s: %s. Write them, THEN "
            "deliver. (delivered means LANDED, not sent — a service cannot ack a drop that isn't on "
            "disk.)" % (base, ", ".join(missing)))
    o["state"] = "DELIVERED"
    log(o, "DELIVERED", "verified %d file(s) landed at %s" % (len(o["deliverable"]["files"]), base))
    save(o)
    die("DELIVERED order '%s' — VERIFIED %d file(s) on disk at %s. Requester %s runs its acceptance "
        "test, then `order accept` or `order reject`." % (
        oid, len(o["deliverable"]["files"]), base, o.get("requester", "?")), 0)

if VERB == "accept":
    require_actor(o, "requester", "the requester")
    require_state(o, "DELIVERED")
    o["state"] = "CLOSED"
    log(o, "CONFIRMED", "accepted by requester")
    save(o)
    die("Order '%s' CONFIRMED and CLOSED." % oid, 0)

if VERB == "reject":
    require_actor(o, "requester", "the requester")
    require_state(o, "DELIVERED")
    reason = " ".join(rest) if rest else ""    # `order reject <id> reason words…`
    if not reason:
        die("reject needs a specific, testable reason. e.g. bus.sh order reject %s 'still reads pasted, not cast-in'" % oid)
    o["revision"] = o.get("revision", 0) + 1
    o["state"] = "COOKING"
    log(o, "REJECTED", reason)
    save(o)
    over = o["revision"] > CEIL
    msg = ("Rejected order '%s' (now rev %d) -> back to COOKING for %s. Reason retained on the order "
           "so a crash-relaunched service won't repeat it." % (oid, o["revision"], o.get("service", "?")))
    if over:
        msg += ("  ⚠ revision %d exceeds the ceiling (%d) — the spec may be underdetermined, not the "
                "work bad. Worth pulling Kyle in." % (o["revision"], CEIL))
    die(msg, 0)

die("unknown order verb '%s' (place|claim|deliver|accept|reject|status|list)" % VERB, 2)
PYEOF
  ) 9>"$ORDER_ROOT/.lock"
}
