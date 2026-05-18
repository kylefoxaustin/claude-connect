# Claude Bus — Cross-Session Message Spec

> Reproduced verbatim from Kyle's spec. Conductor's `MarkdownBusAdapter` in
> `conductor/bus.py` integrates with this exact format.

## File locations

| Item            | Path                                       |
|-----------------|--------------------------------------------|
| Bus script      | `~/.claude/bin/bus.sh`                     |
| Message log     | `~/Documents/claude-bus/messages.md`       |
| Seen-state dir  | `~/.claude/bus-state/`                     |

The message log is append-only markdown. The state dir holds per-session
`<tag>.last-seen` and `<tag>.pending` files used by the prompt-check hook.

## Session tags (auto-detected from CWD)

| Tag                  | Working directory                                    |
|----------------------|------------------------------------------------------|
| `[backend]`          | `~/Documents/GitHub/keyhole`                         |
| `[frontend]`         | `~/Documents/GitHub/keyhole-UI`                      |
| `[sizer]`            | `~/Documents/GitHub/keyhole-sizer`                   |
| `[docs]`             | `~/Documents/GitHub/personal-ai-framework`           |
| `[pai-sizer]`        | `~/Documents/GitHub/personal-ai-assistant-sizer`     |
| `[other:<basename>]` | anywhere else                                        |

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
> mention to Kyle and ask whether to check."

**Important:** Claude is instructed NOT to auto-check — it must pause, tell
Kyle, and wait for approval before running `/msg-check`.

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

1. Add a new case branch in `bus.sh` mapping the directory pattern to a tag.
2. Add the tag to the whitelists in both `session-start` and `prompt-check`
   case statements.
3. No other configuration needed — the state dir and log file are created
   automatically.

> **Conductor mirror:** when you add a new tag, also extend `_BUS_TAG_TABLE`
> in `conductor/scanner.py` so Conductor labels session tiles correctly.
