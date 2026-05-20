# Claude Bus — reference implementation

This is the cross-session message bus that Conductor's 📬 features talk to. It's
a tiny, dependency-free shell script plus four Claude Code slash commands and two
hooks. Wiring it up is **optional** — Conductor monitors every session with or
without it (see ["What if a session isn't wired up?"](#what-if-a-session-isnt-wired-up)).

How it works: each Claude Code session is auto-tagged by its working directory
(`[backend]`, `[other:my-repo]`, …). `/msg-send` appends a tagged line to a shared
markdown log; `/msg-check` reads it. A `UserPromptSubmit` hook quietly tells a
session when new messages have arrived so it can offer to check them. Conductor
tails the same log and renders the traffic.

See [`../docs/claude-bus.md`](../docs/claude-bus.md) for the full format spec.

## Layout

| File | Install to | Purpose |
|------|-----------|---------|
| `bus.sh` | `~/.claude/bin/bus.sh` | the bus engine (send/check/all/rotate + hook outputs) |
| `commands/msg-*.md` | `~/.claude/commands/` | the `/msg-send` `/msg-check` `/msg-all` `/msg-rotate` slash commands |
| `settings.hooks.example.json` | merge into `~/.claude/settings.json` | makes sessions bus-aware automatically |

## Install

```bash
# from the repo root
install -Dm755 bus/bus.sh ~/.claude/bin/bus.sh
mkdir -p ~/.claude/commands
cp bus/commands/*.md ~/.claude/commands/
```

Then merge `bus/settings.hooks.example.json` into `~/.claude/settings.json`
(replace `/home/YOU` with your home path). If you already have `permissions` or
`hooks` keys, merge the inner arrays rather than overwriting them. Restart any
open Claude Code sessions so the hooks load.

Verify:

```bash
~/.claude/bin/bus.sh send "hello bus"
~/.claude/bin/bus.sh check
```

## Tag your projects

Out of the box every directory gets a tag of `[other:<dirname>]`. To give a
project a clean name, add a case branch near the top of `bus.sh`:

```bash
case "$CWD" in
  */my-api|*/my-api/*)   TAG="api" ;;
  */my-web|*/my-web/*)   TAG="web" ;;
  *)                     TAG="other:$(basename "$CWD")" ;;
esac
```

If you want a named tag to participate in the **automatic hooks** (SessionStart
context injection + UserPromptSubmit nudges), also add it to the `BUS_WHITELIST`
near the top of `bus.sh` (a `|`-separated list). Un-whitelisted tags can still
use the slash commands manually; they just won't get the automatic nudges. The
whitelist is what keeps the bus out of unrelated sessions.

> **Keep Conductor in sync:** when you add a named tag here, also add it to the
> `[bus.tags]` table in Conductor's `settings.toml` so it labels the tile with
> the same tag:
>
> ```toml
> [bus.tags]
> "~/code/my-api" = "api"
> ```
>
> See `settings.example.toml`. Anything unmapped falls back to `[other:<dir>]`.

## What if a session isn't wired up?

Nothing breaks. Conductor discovers sessions from OS process state, not the bus,
so an un-wired Claude appears as a full, normal tile (status dot, live preview,
message count, click-to-focus). It just has no bus state, so:

- it shows **no 📬 badge** (no pending messages tracked for it), and
- it draws **no connection line** to the Bus tile.

That's intentional: wired sessions are visually on the tunnel; un-wired ones are
monitored but silent.
