---
description: Ask Kyle whether to push NOW — with what's in it and what you'd do instead
---

You think the work is ready to push. **Do not just push.** The gate would stop you and Kyle
would get a content-free "wants to push" card — a rubber stamp on a decision he never made.

Instead, ask him the question he actually needs to answer, with the context only you have:

```bash
~/.claude/bin/bus.sh push propose - <<'EOF'
why: <your case for pushing NOW — what's done, what's tested, why it's a good stopping point>
else: <a real alternative you're weighing — "keep digging into X first">
else: <another, if you have one>
EOF
```

`why:` is required. Each `else:` is a genuine alternative Kyle can pick instead — he'll tap
one and you'll be told which. **The commits are attached automatically; don't paste them.**

Then **stop and wait.** If Kyle says push, the approval is already armed — just run your push.
If he picks an alternative, do that instead and propose again later.
