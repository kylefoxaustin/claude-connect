#!/usr/bin/env bash
# prompt-route.sh — UserPromptSubmit hook. If you @-address a registered session at the START
# or END of your prompt, route the message THERE as a live prompt and block it here — so you
# can talk to any Claude from whatever session you're in (incl. the Claude app over /rc, since
# UserPromptSubmit fires on those prompts too).
#
#   "@qualcomm rerun the benchmark"        -> qualcomm gets "rerun the benchmark"
#   "yeah let's do it @qualcomm"           -> qualcomm gets "yeah let's do it"
#   "the @qualcomm session is buggy"       -> NOT routed (mid-sentence = talking ABOUT it)
#   "@notasession do x" / normal prompts   -> NOT routed (unknown tag / no leading-or-trailing @)
#
# SAFETY: this runs on EVERY prompt, so it FAILS OPEN — any error, any doubt, exit 0 and your
# prompt runs untouched. It only ever routes a leading/trailing @<KNOWN, registered> tag that
# isn't yourself. A route is always VISIBLE (the block reason tells you), never silent.
set -uo pipefail

STATE_DIR="${BUS_STATE_DIR:-$HOME/.claude/bus-state}"
PR_PAYLOAD="$(cat 2>/dev/null || true)"
[ -n "$PR_PAYLOAD" ] || exit 0
# Cheap prefilter: no '@' anywhere -> not a route, don't even start python.
case "$PR_PAYLOAD" in *"@"*) : ;; *) exit 0 ;; esac

PR_PAYLOAD="$PR_PAYLOAD" PR_STATE_DIR="$STATE_DIR" python3 - <<'PY' 2>/dev/null || exit 0
import json, os, re, sys, time

try:
    p = json.loads(os.environ["PR_PAYLOAD"])
except Exception:
    sys.exit(0)                                   # unparseable -> fail open

text = (p.get("user_input") or p.get("prompt") or "")
sid  = (p.get("session_id") or "").strip()
if not text.strip() or "@" not in text:
    sys.exit(0)

state = os.environ["PR_STATE_DIR"]
TAGCH = r'[A-Za-z0-9_:\-]+'

# @tag at the START ("@x message") or END ("message @x") — never mid-sentence.
tag = message = None
m = re.match(r'^\s*@(' + TAGCH + r')\s+(.+)$', text, re.S)
if m:
    tag, message = m.group(1), m.group(2).strip()
else:
    m = re.match(r'^(.+?)\s+@(' + TAGCH + r')[.!?,;:]*\s*$', text, re.S)
    if m:
        message, tag = m.group(1).strip(), m.group(2)
if not tag or not message:
    sys.exit(0)

def ident(t):
    t = t.strip().strip("[]").lower()
    return t[6:] if t.startswith("other:") else t

want = ident(tag)

# Route ONLY to a registered session (guards against a stray "@word"): check active-tags.
known = set()
try:
    with open(os.path.join(state, "active-tags"), encoding="utf-8") as f:
        known = {ident(ln) for ln in f if ln.strip()}
except OSError:
    pass
if want not in known:
    sys.exit(0)                                   # not a real session -> proceed normally

# Don't route to myself — resolve my own member from session_id (members registry).
me = None
try:
    with open(os.path.join(state, "members"), encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("#"):
                continue
            c = ln.rstrip("\n").split("\t")
            if len(c) >= 2 and c[0] == sid:
                me = ident(c[1]); break
except OSError:
    pass
if me and want == me:
    sys.exit(0)                                   # @self -> just handle it here

# It's a real route. Drop a request Conductor delivers, and BLOCK this prompt here.
rdir = os.path.join(state, "coord", "prompt-routes")
try:
    os.makedirs(rdir, exist_ok=True)
    stamp = int(time.time() * 1000)
    tmp   = os.path.join(rdir, f".{stamp}-{os.getpid()}.tmp")
    final = os.path.join(rdir, f"{stamp}-{os.getpid()}.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"target": want, "message": message, "source_session": sid, "ts": time.time()}, f)
    os.replace(tmp, final)
except OSError:
    sys.exit(0)                                   # couldn't queue it -> don't block, fail open

print(json.dumps({"decision": "block", "reason":
    f"→ routed to @{tag}. It will receive your message as a prompt (delivered when it's "
    f"free) — this was NOT handled here. To talk to THIS session, resend without the @{tag}."}))
sys.exit(0)
PY
exit 0
