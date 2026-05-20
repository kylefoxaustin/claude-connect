# Claude Bus — Cross-Session Message Spec

> Format spec for the reference message bus. Conductor's `MarkdownBusAdapter` in
> `conductor/bus.py` integrates with this exact format. The runnable
> implementation ships in [`../bus/`](../bus/).

## File locations

| Item            | Path                                       |
|-----------------|--------------------------------------------|
| Bus script      | `~/.claude/bin/bus.sh`                     |
| Message log     | `~/Documents/claude-bus/messages.md`       |
| Seen-state dir  | `~/.claude/bus-state/`                     |

The message log is append-only markdown. The state dir holds per-session
`<tag>.last-seen` and `<tag>.pending` files used by the prompt-check hook.

## Session tags (auto-detected from CWD)

Each session is tagged by its working directory via the case-table in `bus.sh`.
Map your own project dirs there; anything unmapped falls back to the basename.
Example:

| Tag                  | Working directory      |
|----------------------|------------------------|
| `[api]`              | `~/code/my-api`        |
| `[web]`              | `~/code/my-web`        |
| `[other:<basename>]` | anywhere else          |

Tags are appended automatically — no configuration needed per session.

## Slash commands (user-invocable)

| Command                  | What it does                                    |
|--------------------------|-------------------------------------------------|
| `/msg-send <text>`       | Append a tagged message to the bus              |
| `/msg-check`             | Read the last 80 lines; mark as seen            |
| `/msg-all`               | Dump the full log                               |
| `/msg-rotate [YYYY-MM]`  | Archive current log to `messages-YYYY-MM.md`, start fresh |

## Hooks (automatic, no user action needed)

### SessionStart hook
Fires when a new Claude Code session opens inside a whitelisted directory.
Injects the last 60 lines of the bus as `additionalContext` so the new
session knows what other sessions said while it was offline. No-op outside
the whitelisted dirs.

### UserPromptSubmit hook
Fires on every user prompt. Checks whether any new messages arrived on the
bus (from a different session tag) since the current session last called
check. If yes, injects a one-line nudge:

> "Claude Bus — N pending message(s) from [tag] since you last checked
> (newest: YYYY-MM-DD HH:MM). Content NOT shown. At a natural pause,
> mention to the user and ask whether to check."

**Important:** Claude is instructed NOT to auto-check — it must pause, tell
the user, and wait for approval before running `/msg-check`.

## Message format

```
## YYYY-MM-DD HH:MM [tag]

<freeform message text>
```

Messages are appended to the bottom of `messages.md`. The log is never
edited, only appended (except on rotate).

## Bus script CLI (direct usage)

```bash
~/.claude/bin/bus.sh send "your message"   # send
~/.claude/bin/bus.sh check                 # read last 80 lines + mark seen
~/.claude/bin/bus.sh all                   # full log
~/.claude/bin/bus.sh rotate [YYYY-MM]      # archive + reset
~/.claude/bin/bus.sh session-start         # hook: emit additionalContext JSON
~/.claude/bin/bus.sh prompt-check          # hook: emit pending-count nudge JSON
```

The `BUS_FILE` env var overrides the default log path (useful for testing).

## Adding a new session / directory

1. Add a case branch in `bus.sh` mapping the directory pattern to a tag.
2. Add the tag to `BUS_WHITELIST` so it participates in the automatic hooks.
3. No other configuration needed — the state dir and log file are created
   automatically.

> **Conductor mirror:** when you add a named tag, also add it to the
> `[bus.tags]` table in Conductor's `settings.toml` (`"<dir>" = "<tag>"`) so
> Conductor labels session tiles with the same tag. See `settings.example.toml`.
