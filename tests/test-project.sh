#!/usr/bin/env bash
# Jailed lifecycle test for the PROJECT LAYER (bus/project.sh), slice 1: the project object, the
# nomination handshake (accept/decline/suggest), and the plan gate. Identities derive from cwd
# basename (like the order test): the lead (95emulator), a bystander who must NOT be able to accept
# a nomination that isn't theirs (qualcomm), and an ops cwd standing in for the operator (Kyle acts
# through Conductor, which bus.sh does not identity-gate — only the LEAD-side actions are gated).
set -u
BUS=/home/kyle/Documents/GitHub/claude-connect/bus/bus.sh
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP"
SD="$HOME/.claude/bus-state"; mkdir -p "$SD/coord" "$HOME/Documents/claude-bus"
export BUS_FILE="$HOME/Documents/claude-bus/messages.md"
export PROJECT_STATE_DIR="$SD/coord/projects"
LEAD="$HOME/w/95emulator"; OTHER="$HOME/w/qualcomm"; IMG="$HOME/w/image_gen"; OPS="$HOME/w/ops"
mkdir -p "$LEAD" "$OTHER" "$IMG" "$OPS"
lead(){ (cd "$LEAD" && bash "$BUS" project "$@" 2>&1); }
other(){ (cd "$OTHER" && bash "$BUS" project "$@" 2>&1); }
img(){ (cd "$IMG" && bash "$BUS" project "$@" 2>&1); }
ops(){ (cd "$OPS" && bash "$BUS" project "$@" 2>&1); }

pass=0 fail=0
okc(){ if printf '%s' "$2" | grep -qiF "$3"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — missing [$3] in: $2"; fi; }
field(){ python3 -c "import sys,json;print(json.load(open('$PROJECT_STATE_DIR/$1.json')).get('$2',''))"; }
ok(){ if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected [$3] got [$2]"; fi; }

# 1. new (operator names the goal)
okc "new" "$(ops new neutron 'add Neutron NPU support to the 95 emulator')" "created"
ok  "state draft" "$(field neutron state)" "draft"

# 2. nominate — operator may type the friendly name; it canonicalizes to the lead's own tag
okc "nominate" "$(ops nominate neutron 95emulator)" "nominated"
ok  "state nominating" "$(field neutron state)" "nominating"
ok  "lead recorded canonical" "$(field neutron lead)" "95emulator"
# nominate WAKES the nominee: a directed bus message so the lead learns it was picked
okc "nominate posts a directed wake" "$(cat "$BUS_FILE")" "to:95emulator"
okc "wake tells the nominee to accept" "$(cat "$BUS_FILE")" "project accept neutron"

# 3. a bystander cannot accept a nomination that is not theirs
okc "bystander cannot accept" "$(other accept neutron)" "only the nominee"
ok  "still nominating" "$(field neutron state)" "nominating"

# 4. the nominee accepts -> planning
okc "nominee accepts" "$(lead accept neutron)" "is now lead"
ok  "state planning" "$(field neutron state)" "planning"

# 5. only the accepted lead may submit the plan; a bystander cannot
okc "bystander cannot plan" "$(printf 'x' | other plan neutron)" "only the accepted lead"

# 6. lead submits the plan on stdin -> plan_review (the gate)
okc "lead submits plan" "$(lead plan neutron <<'EOF'
A extract ISA tables -> qualcomm
B decode (needs A)    -> 93emulator
EOF
)" "plan submitted"
ok  "state plan_review" "$(field neutron state)" "plan_review"
ok  "plan_status submitted" "$(field neutron plan_status)" "submitted"

# 7. empty plan is refused
okc "empty plan refused" "$(printf '' | lead plan neutron)" "plan is empty"

# 8. operator revises -> back to planning with notes
okc "operator revises" "$(ops revise neutron 'split B into decode+execute')" "sent back"
ok  "state planning again" "$(field neutron state)" "planning"
okc "notes retained" "$(ops status neutron)" "split B into decode"

# 9. re-plan + approve -> active (Gate #1 passes)
lead plan neutron <<'EOF' >/dev/null
A -> B1(decode) -> B2(execute)
EOF
okc "operator approves" "$(ops approve neutron)" "ACTIVE"
ok  "state active" "$(field neutron state)" "active"
ok  "plan_status approved" "$(field neutron plan_status)" "approved"

# 10. can't approve when there's nothing submitted
okc "no double-approve" "$(ops approve neutron)" "no submitted plan"

# 11. decline path (fresh project) -> back to draft, reason retained
ops new p2 "second goal" >/dev/null
ops nominate p2 image_gen >/dev/null
okc "nominee declines" "$(img decline p2 'GPU saturated this week')" "declined"
ok  "state back to draft" "$(field p2 state)" "draft"
ok  "lead cleared" "$(field p2 lead)" "None"

# 12. suggest-another (advisory) path
ops nominate p2 qualcomm >/dev/null
okc "nominee suggests another" "$(other suggest p2 image_gen 'they own the GPU rig')" "suggests"
okc "suggestion recorded in status" "$(ops status p2)" "image_gen"

# 13. list shows both projects
okc "list shows projects" "$(ops list)" "neutron"
okc "list shows p2" "$(ops list)" "p2"

# ============================ SLICE 2: jobs, the DAG, dispatch-as-orders ======================
# neutron is active with lead 95emulator. Build an A -> B chain and drive it to completion.
DROP="$HOME/drop"; mkdir -p "$DROP"
jfield(){ python3 -c "import sys,json;p=json.load(open('$PROJECT_STATE_DIR/$1.json'));j=[x for x in p['jobs'] if x['id']=='$2'][0];print(j.get('$3',''))"; }

# 14. add jobs — a job is DIRECTED and must declare a landing (path+files)
okc "add jobA" "$(lead job add neutron jobA to:qualcomm path:$DROP files:isa.md -- extract ISA)" "added"
okc "add jobB deps A" "$(lead job add neutron jobB to:image_gen path:$DROP files:dec.c deps:jobA -- decode)" "added"
ok  "jobA state planned" "$(jfield neutron jobA state)" "planned"

# 15. guards: unknown dep, self-dep, non-lead can't add, broadcast (no to:) refused
okc "unknown dep refused" "$(lead job add neutron jobX to:qualcomm path:$DROP files:x.md deps:nope -- x)" "unknown dep"
# a self-dep is refused by the unknown-dep guard (the job doesn't exist yet) — which is exactly
# why cycles are impossible: you can only depend on jobs that already exist.
okc "self-dep refused (no back-edges possible)" "$(lead job add neutron jobY to:qualcomm path:$DROP files:y.md deps:jobY -- y)" "unknown dep"
okc "non-lead can't add" "$(other job add neutron jobZ to:qualcomm path:$DROP files:z.md -- z)" "only the accepted lead"
okc "broadcast job refused" "$(lead job add neutron jobW path:$DROP files:w.md -- no assignee)" "DIRECTED to one session"

# 16. jobs view shows readiness
okc "jobs: A dispatchable" "$(ops jobs neutron)" "jobA"
okc "jobs: B blocked on A" "$(ops jobs neutron)" "waiting on: jobA"

# 17. the DAG blocks dispatch of B until A is done
okc "dispatch B refused (blocked)" "$(lead dispatch neutron jobB)" "blocked"
disp_out="$(lead dispatch neutron jobA)"
okc "dispatch A ok (ready)" "$disp_out" "dispatched"
okc "dispatch NOTIFIES the assignee" "$disp_out" "notified [qualcomm]"
ok  "jobA now dispatched" "$(jfield neutron jobA state)" "dispatched"
ok  "jobA has an order id" "$(jfield neutron jobA order_id)" "proj-neutron__jobA"
# the wake is a DIRECTED bus message (to:assignee) — what Conductor's auto-delivery wakes on
okc "wake lands on the bus, addressed to the worker" "$(cat "$BUS_FILE")" "to:qualcomm"
okc "wake carries the claim instruction" "$(cat "$BUS_FILE")" "order claim proj-neutron__jobA"

# 18. only the lead dispatches; can't re-dispatch
okc "non-lead can't dispatch" "$(other dispatch neutron jobB)" "only the lead"
okc "no double-dispatch" "$(lead dispatch neutron jobA)" "already dispatched"

# 19. complete jobA's order: worker (qualcomm) claims + delivers (file lands) + lead accepts -> CLOSED
OID=proj-neutron__jobA
worker(){ (cd "$OTHER" && bash "$BUS" order "$@" 2>&1); }        # qualcomm is jobA's assignee
leadorder(){ (cd "$LEAD" && bash "$BUS" order "$@" 2>&1); }      # 95emulator dispatched it = the order's requester
okc "worker claims" "$(worker claim $OID)" "Claimed"
printf 'isa\n' > "$DROP/isa.md"
okc "worker delivers (verified)" "$(worker deliver $OID)" "DELIVERED"
okc "lead accepts order" "$(leadorder accept $OID)" "CONFIRMED"

# 20. sync advances the DAG: jobA done -> jobB unblocks
okc "sync completes jobA" "$(ops sync neutron)" "jobA"
ok  "jobA done" "$(jfield neutron jobA state)" "done"
okc "jobB now dispatchable" "$(ops jobs neutron)" "jobB"
okc "dispatch B now allowed" "$(lead dispatch neutron jobB)" "dispatched"

# ============================ SLICE 3: decision routing (the shield) ==========================
efield(){ python3 -c "import sys,json;p=json.load(open('$PROJECT_STATE_DIR/$1.json'));e=[x for x in p['escalations'] if x['id']=='$2'][0];print(e.get('$3',''))"; }

# 21. the audit log — a worker LOGS a technical decision (no escalation, nobody asked)
okc "decide logs" "$(other decide neutron job:jobA chose int8 over fp16 within tolerance)" "logged"

# 22. a project question routes to the LEAD
okc "escalate to lead" "$(other escalate neutron e1 job:jobA <<'EOF'
question: int8 model or wait for fp16?
why: jobB parity depends on it
option: int8
option: fp16
recommendation: int8
EOF
)" "the lead"
ok  "e1 target lead" "$(efield neutron e1 target)" "lead"

# 23. a severity finding takes the HATCH — straight to Kyle
okc "security escalates to Kyle" "$(other escalate neutron e2 sev:security <<'EOF'
question: patch the push-gate bypass now?
why: a security control has a hole
option: patch now
option: file it
EOF
)" "Kyle DIRECTLY"
ok  "e2 target kyle" "$(efield neutron e2 target)" "kyle"

# 24. the lead answers a lead-bound escalation; is BARRED from a Kyle-bound one
okc "lead answers lead-bound" "$(lead answer neutron e1 use int8)" "answered"
okc "lead BARRED from kyle-bound" "$(lead answer neutron e2 patch it)" "may not answer"
ok  "e2 still open" "$(efield neutron e2 state)" "open"

# 25. Kyle (operator) answers the Kyle-bound one
okc "operator answers kyle-bound" "$(ops answer neutron e2 patch now)" "answered"
ok  "e2 answered" "$(efield neutron e2 state)" "answered"

# 26. forward — a lead pushes a lead-bound item to Kyle on a denylist realization
other escalate neutron e3 <<'EOF' >/dev/null
question: add ONNX export as a deliverable?
why: hinted but not in the approved plan
option: add it
option: keep to plan
EOF
okc "lead forwards (scope)" "$(lead forward neutron e3 deny:scope </dev/null)" "forwarded"
ok  "e3 now kyle-bound" "$(efield neutron e3 target)" "kyle"
okc "lead barred after forward" "$(lead answer neutron e3 add it)" "may not answer"
okc "non-lead cannot forward" "$(other forward neutron e3 </dev/null)" "only the lead"

# 27. escalations view + deny routing straight to Kyle
okc "deny routes to Kyle" "$(img escalate neutron e4 deny:irreversible <<'EOF'
question: delete old checkpoints (40GB)?
why: irreversible
option: delete
option: archive first
EOF
)" "Kyle DIRECTLY"
# 27b. lead-timeout auto-escalate (the system verb Conductor calls) flips a lead-bound one to Kyle
other escalate neutron e5 <<'EOF' >/dev/null
question: which sequencing for the last two jobs?
why: coordination call
option: A then B
option: B then A
EOF
ok  "e5 starts lead-bound" "$(efield neutron e5 target)" "lead"
okc "timeout-forward flips to Kyle" "$(ops timeout-forward neutron e5)" "auto-escalated"
ok  "e5 now kyle-bound" "$(efield neutron e5 target)" "kyle"
ok  "e5 marked timed_out" "$(efield neutron e5 timed_out)" "True"
okc "lead barred after timeout" "$(lead answer neutron e5 A then B)" "may not answer"

okc "escalations --open lists open e4" "$(ops escalations neutron --open)" "e4"
okc "escalations --open lists forwarded e3" "$(ops escalations neutron --open)" "e3"
# e2 is answered, so it must NOT appear under --open (but DOES in the full view)
if printf '%s' "$(ops escalations neutron --open)" | grep -qF "e2"; then
  fail=$((fail+1)); echo "FAIL: answered e2 should not be in --open"; else pass=$((pass+1)); fi
okc "full view shows answered e2" "$(ops escalations neutron)" "e2"

# ===== operator override: Conductor acts as 'operator', not its cwd tag (collision regression) =====
# The live bug: Conductor shells from its own cwd, so when the project's lead runs where Conductor
# does, ME == lead and the 'lead may not answer a Kyle-bound escalation' guard misfires. Fixed by
# PROJECT_ME_OVERRIDE=operator. Here the ANSWERER shares the lead's cwd (LEAD), so without the
# override ME would be the lead and be barred; with it, operator answers fine.
opas(){ (cd "$LEAD" && PROJECT_ME_OVERRIDE=operator bash "$BUS" project "$@" 2>&1); }
lead job add neutron jobD to:qualcomm path:$DROP files:d.md -- extra >/dev/null
lead escalate neutron e6 deny:budget <<'EOF' >/dev/null
question: spend 2x the token budget to finish?
why: budget denylist
option: yes
option: no
EOF
okc "operator answers a kyle-bound one from the lead's own cwd" "$(opas answer neutron e6 no)" "answered"
# and operator can dispatch even though it isn't literally the lead tag
okc "operator may dispatch (admits on lead's behalf)" "$(opas dispatch neutron jobD)" "dispatched"

# ===== slice 5: the budget ceiling (the meter itself is Conductor-side / python-tested) =====
okc "set budget (2m shorthand)" "$(lead budget neutron 2m)" "2,000,000 output tokens"
ok  "ceiling stored" "$(python3 -c "import json;print(json.load(open('$PROJECT_STATE_DIR/neutron.json'))['ceiling'])")" "2000000"
okc "status shows the budget" "$(ops status neutron)" "2,000,000 output tokens"
okc "500k shorthand" "$(lead budget neutron 500k)" "500,000"
okc "bad value refused" "$(lead budget neutron nope)" "usage: project budget"
okc "non-lead/non-operator refused" "$(other budget neutron 1m)" "only the lead"
okc "operator may set it" "$(opas budget neutron 750000)" "750,000"
okc "0 clears the cap" "$(lead budget neutron 0)" "cap cleared"

# ===== slice 7: job priority (background default / urgent) — the wake states it, worker self-arbitrates =====
jf(){ python3 -c "import json;p=json.load(open('$PROJECT_STATE_DIR/neutron.json'));j=[x for x in p['jobs'] if x['id']=='$1'][0];print(j.get('$2',''))"; }
lead job add neutron bgjob to:qualcomm path:$DROP files:bg.md -- a background job >/dev/null
lead job add neutron urgjob to:qualcomm path:$DROP files:urg.md prio:urgent -- an urgent job >/dev/null
ok  "default prio is background" "$(jf bgjob prio)" "background"
ok  "explicit prio urgent" "$(jf urgjob prio)" "urgent"
okc "bad prio refused" "$(lead job add neutron xj to:qualcomm path:$DROP files:x.md prio:nope -- x)" "prio must be"
okc "jobs view marks urgent" "$(ops jobs neutron)" "⚡urgent"
# the wake message states the priority so the worker self-arbitrates (doesn't ask the operator)
lead dispatch neutron bgjob >/dev/null
okc "background wake tells worker to fit it around own work" "$(cat "$BUS_FILE")" "PRIORITY: BACKGROUND"
okc "background wake says do NOT ask the operator" "$(cat "$BUS_FILE")" "do NOT ask the operator"
lead dispatch neutron urgjob >/dev/null
okc "urgent wake says prioritize over own work" "$(cat "$BUS_FILE")" "PRIORITY: URGENT"

echo "---"; echo "project: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
