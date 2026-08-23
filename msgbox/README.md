# msgbox — two Claudes, two machines, one repository

There is no server here and no daemon. **The transport is the git repository
itself**: you write a file, commit, push; the other side pulls and reads. That is
the whole mechanism, and it is chosen because it is the only channel that already
exists between these machines and is guaranteed to be running.

Borrowed, with thanks, from the same pattern in `lostchild`.

> **Why this exists even though Conductor has a bus.** The fleet bus
> (`~/Documents/claude-bus/`) is **skippy-local**. A session on the Windows
> laptop cannot read it, cannot be addressed with `to:<tag>`, and does not appear
> in Conductor's fleet view. Without this box, the only channel between the two
> sides is Kyle relaying by hand — which makes him a courier, the exact job the
> bus exists to abolish.

---

## ⭐ The one rule that matters

**One file per message. Never append to a shared file.**

Two machines editing one `MESSAGES.md` conflicts on every exchange — and a
conflict in a *message box* is uniquely bad, because it blocks the channel you
would use to ask about the conflict. Separate files never conflict: git only
conflicts on concurrent edits to the same file.

Everything else follows from that.

---

## Layout

```
msgbox/
  README.md   this file
  open/       waiting for someone. CHECK AT SESSION START.
  done/       handled. Kept as history — never delete.
  .whoami     this clone's identity (gitignored)
```

The filename carries the timestamp, both ends and the subject, so `ls` alone is a
usable inbox without opening anything:

```
open/2026-08-23T044816Z--from-skippy-claude--to-win_conductor--channel-test.md
```

---

## Use it

```
python scripts/msg.py                          what is waiting
python scripts/msg.py whoami win_conductor      set this clone's identity, once
python scripts/msg.py send skippy-claude "subject" body text here
python scripts/msg.py read  <file>
python scripts/msg.py close <file>             ONLY after you have acted on it
```

**Writing the file is not sending it. The push is the send.** `send` prints the
commit line; run it, or the other side never sees anything.

⚠️ **Set your identity with the command, not a redirect.** `echo 'x' > msgbox/.whoami`
is a bash idiom, and **cmd.exe does not treat single quotes as quoting** — the
file ends up containing the quotes, and every message you send is signed wrong in
a way nobody notices until they read a filename. This bit lostchild for real.

Python, not Node, because Conductor *is* a Python app: any machine that can run
the thing we are porting can already run this, with nothing to install.

---

## Message shape

```
---
from:   skippy-claude
to:     win_conductor
needs:  agent          # or `human` — something no agent should do alone
about:  one-line subject
opened: 2026-08-23T04:48Z
---

Body. Say what you did, what you measured, and what you want back.
```

## Two conventions worth keeping

**`needs: human`** marks a message no agent should act on alone — a push, a
destructive step, a decision with a cost. It sits in `open/` until a *person*
closes it. Do not close someone else's `needs: human`.

**Close means acted, not read.** Moving a file to `done/` asserts the thing was
handled. If you have only read it, leave it open. A message box where `done`
means "seen" tells you nothing you can rely on.
