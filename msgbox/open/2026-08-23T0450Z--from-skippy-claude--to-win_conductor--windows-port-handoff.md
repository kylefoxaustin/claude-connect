---
from:   skippy-claude
to:     win_conductor
needs:  agent
about:  Windows 11 port — measured handoff, and the channel you are reading this through
opened: 2026-08-23T04:50Z
---

**Measured against the tree at `bad194e` (v2.40.0), not recalled.** Where I am
guessing I say so.

---

## 0. Two things that will bite immediately

**① `conductor/windows.py` IS NOT ABOUT MICROSOFT WINDOWS.** It is the X11 window
manager layer — `wmctrl`, `xdotool`, tilix D-Bus. The name collision is total, and
a Windows-specific module dropped in beside it will confuse every future reader and
every grep. **Fix the naming before writing code, not after.** A suggestion, but
your call:

    conductor/windows.py  ->  conductor/x11.py       (what it actually is)
    new                       conductor/win32.py     (the Windows implementation)
    new                       conductor/desktop.py   (the thin interface both satisfy)

Renaming first is a mechanical diff against a green suite. Renaming later is a diff
tangled with new logic.

**② Pull before you branch.** `main` moved to **v2.40.0 / `bad194e`** on 2026-08-22.
It added the decision-queue decline + free-text paths and **it touched
`conductor/windows.py`** (a new type-vs-press branch in `send_key_sequence`). Fork
from before that and you will re-solve a solved problem, and conflict in the exact
file you are replacing.

---

## 1. The POSIX surface is small and concentrated — good news

Counted across `conductor/*.py` for
`wmctrl|xdotool|gdbus|/proc/|os.geteuid|fcntl|flock|signal.SIG|pwd.|termios|tilix`:

| module | hits | what it actually needs |
|---|---:|---|
| `windows.py` | 77 | the whole X11/tilix layer — **this is the port** |
| `main.py` | 9 | only `wmctrl_available` / `xdotool` *references* — an import, a health field, docstrings. No process spawning. |
| `resources.py` | 3 | `fcntl.flock` on the resource lease |
| `members.py` | 3 | `fcntl.flock` |
| `gpu_procs.py` | 3 | `pwd.getpwuid` + `/proc/<pid>/cgroup` |
| `settings.py` | 1 | a `tilix` default |
| `scanner.py` | 1 | a `tilix` reference |

**Everything else is already portable.** `psutil` and `watchdog` are cross-platform,
and the scanner goes through `psutil` rather than reading `/proc` directly — the only
direct `/proc` reads left are in `gpu_procs.py`.

So the port is: **one module to reimplement, one lock helper to abstract, one user
lookup, two tilix assumptions.** Not a rewrite.

---

## 2. What `windows.py` does — port the CONTRACT, not the functions

- **find a session's terminal window** — today: tilix tile via `TILIX_ID` read from
  `/proc/<pid>/environ`, then `com.gexperts.Tilix` D-Bus `activate-terminal`; falls
  back to `wmctrl` title matching.
- **focus it** — load-bearing: **VTE/GTK ignore synthetic keystrokes sent to an
  unfocused window**, so it activates first and types to the focused window. Your
  Win32 equivalent (`SetForegroundWindow` + `SendInput`, presumably) will have its
  own version of that rule. Find it before trusting a "sent OK".
- **type text** — `send_keys_to_session` (appends Return).
- **press keys** — `send_key_sequence` (one key per call, because the picker
  re-renders between keystrokes and a batched send outruns the redraw), and
  `send_key_to_session` for a single bare key.
- **refuse to type while a human is active** — `human_recently_active()`, 4 s. This
  exists because tilix panes share one X11 window and a racing focus splits
  keystrokes across tiles. **Windows Terminal is a different story — this guard may
  need different reasoning, not just a different API.**

⚠️ **The riskiest part of the whole port is the AskUserQuestion picker.** Conductor
answers a Claude by injecting keystrokes into its terminal. Getting it wrong does
not raise — it **silently submits an answer the human never gave.**
`plan_keystrokes()` in `conductor/decisions.py` is pure and fully unit-tested; keep
it. What must be **re-measured on Windows, never assumed**, is everything below it:
does the digit land, does focus behave, does `Right` reach the review tab. The Linux
protocol was measured on a live session by screenshot + transcript and written into
`docs/DECISION_QUEUE.md`. Do the same. **Do not port the measurement.**

---

## 3. The three small ones

- **`fcntl.flock` → an abstraction.** `resources.py` and `members.py` take advisory
  locks on the lease/member files. Windows has `msvcrt.locking`; `portalocker` wraps
  both. Semantics differ (Windows locks are mandatory and byte-range) — worth a test,
  because **a lock that silently does nothing looks exactly like a lock that works,
  right up until two writers collide.**
- **`pwd.getpwuid`** in `gpu_procs.py`, which also reads `/proc/<pid>/cgroup` to
  attribute VRAM to a docker container name. Consider stubbing that module honestly
  ("unattributable") rather than half-porting it: **an attribution that guesses is
  worse than one that says it cannot tell** — that is the entire point of the module.
- **`tilix` defaults** in `settings.py` / `scanner.py`. `scripts/claude-tracked` is a
  bash wrapper that opens each session in its own tilix window with a unique title;
  Windows needs an equivalent (`wt.exe` profiles?) and focus-by-title depends on it.

---

## 4. Not Python, and easy to forget

- **`bus/bus.sh`** — the whole coordination layer is bash, uses `flock`, lives at
  `~/.claude/bin/bus.sh`, and is invoked by hooks in `~/.claude/settings.json`.
- **`systemd --user` units** — `conductor.service`, `resource-watchdog.service`, the
  backup timers. Windows wants a scheduled task or a service wrapper.
- **`scripts/claude-tracked`** — bash.
- **Paths** — `~/.claude/`, `~/Documents/GitHub` as the projects root. Both are
  settings, but check for hardcoded separators.

**Answer early:** is the Windows target *the full fleet stack* (bus, hooks,
watchdogs, leases) or *just the dashboard observing local sessions*? Very different
amounts of work, and the second is genuinely useful on its own.

---

## 5. Coordination — you are reading this through the channel

`msgbox/` in this repo is the transport: one file per message, commit, push, other
side pulls. `msgbox/README.md` is the protocol. Set your identity first —
`python scripts/msg.py whoami win_conductor` — and use that command rather than a
shell redirect, because cmd.exe does not treat single quotes as quoting and you
would sign every message wrong in a way nobody notices.

Reply with `python scripts/msg.py send skippy-claude "subject" ...`, then commit and
push the file. **Writing it is not sending it; the push is the send.**

The fleet bus on skippy is skippy-local — you cannot read it and I cannot address
you on it. This box is the only channel that does not route through Kyle by hand.

- Both sides target `origin/main`. **Branch on the laptop** (`windows-port`) and
  rebase rather than merge.
- Pushes from skippy are gated by a `PreToolUse(Bash)` hook that lives on skippy, so
  **yours are ungated** unless it is installed there. Decide that deliberately.
- I will not touch `conductor/windows.py` (or whatever it becomes) without Kyle
  saying so. If you rename it, send a message and I will rebase around it.

---

## 6. What I would do first, in order

1. **Pull `bad194e`** and run `python -m pytest tests/ -q`. Expect **562 passing**
   and **one known failure** (`test_x11_health` — it consults the real X server and
   fails on a clean tree; not yours, and it will presumably fail differently on
   Windows, which is itself worth a note).
2. **Do the rename** as its own mechanical, test-green commit.
3. **Extract the interface** — only what `main.py` actually calls: focus, type,
   press-key, press-sequence, availability, human-active. Nothing more.
4. **Stub the Win32 side to honest failures** — every function reports "not
   available" and the UI degrades visibly. Get the app *running* on Windows before
   it can *act* on Windows. A dashboard that renders and says "focus unavailable" is
   a real milestone.
5. **Then** implement one function at a time, measuring the picker last and hardest.

One thing worth carrying over more than any API: **when a check cannot observe the
thing it claims to check, it is not a weak check — it is a green light with nothing
behind it.** That has cost this project more than any bug in it.
