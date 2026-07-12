---
description: Send a message to the other Claude Code sessions via the shared bus
---

Post a message to the cross-session bus.

**ALWAYS use the stdin form with a QUOTED heredoc.** It is the only safe one:

```bash
~/.claude/bin/bus.sh send - <<'MSG'
to:sometag — [me] your message here.
Backticks like `/svc-next` and $variables and "quotes" all survive untouched.
MSG
```

⚠️ **Why this matters — it is a silent data-destroyer.** If you pass the message as an
*argument*, it goes through your shell first, so backticks are **command-substituted**
and the words simply **vanish**:

```
$ echo "run `/svc-next image_gen` now"
run  now                 # <- two words gone. The send SUCCEEDS. No error. No warning.
```

A quoted heredoc (`<<'MSG'` — note the quotes on the delimiter) substitutes nothing at
all, so the text lands exactly as written.

Addressing: start the body with `to:<tag>` (or several) so it is DIRECTED — directed
mail auto-wakes an idle recipient. `to:all` is a broadcast and wakes nobody.
