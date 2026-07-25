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
okc "dispatch A ok (ready)" "$(lead dispatch neutron jobA)" "dispatched"
ok  "jobA now dispatched" "$(jfield neutron jobA state)" "dispatched"
ok  "jobA has an order id" "$(jfield neutron jobA order_id)" "proj-neutron__jobA"

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

echo "---"; echo "project: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
