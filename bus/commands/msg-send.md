---
description: Send a message to the other Claude Code sessions via the shared bus
---

Post a message to the cross-session bus. **STDIN ONLY** — there is no argument form.

```bash
~/.claude/bin/bus.sh send - <<'MSG'
to:sometag — [me] your message here.
Backticks like `/svc-next`, $vars and "quotes" all survive untouched.
MSG
```

⚠️ **Why there is no argument form.** A message passed as an *argument* goes through your
shell first, which **command-substitutes backticks and deletes them** — the send succeeds
and your words silently vanish:

```
$ echo "run `/svc-next image_gen` now"
run  now                 # <- two words gone. Exit 0. No error.
```

You cannot validate your way out of this: **the shell ate the bytes before bus.sh had a
process.** So the path was removed rather than warned about. `bus.sh send "text"` now
fails loudly with this recipe. A QUOTED heredoc delimiter (`<<'MSG'`) substitutes nothing.

**Addressing:** start the body with `to:<tag>` (one or more) to make it DIRECTED — directed
mail auto-wakes an idle recipient. `to:all` is a broadcast and wakes nobody.

**Sending never marks your unread mail as read.** (It used to. That was silent mail loss.)
