# Answering a Claude's question from your phone

**Status:** shipped. Capture hook, answer endpoint, guard, and the phone console at `/m`.
Every keystroke sequence below was measured against a live session, not inferred.

Kyle's ask:

> *"A Claude is giving me choices to make — 1 or 2, or select from several options — and
> submit it back. I want to respond to those, because responding unblocks a lot of work
> that I currently have to walk to the PC to accept."*

This is the phone app's reason to exist. Everything else it shows is a nice-to-have; this
is the thing that gives Kyle his time back. So the mechanism was **measured, not designed
from what seemed reasonable** — and the first thing measuring did was kill the plan.

---

## The plan that would have shipped broken

The obvious approach: Claude Code records `AskUserQuestion` in the session transcript with
the full payload — question, header, `multiSelect`, and every option with its label and
description. An `AskUserQuestion` **tool_use with no matching tool_result** is, by
definition, a Claude blocked on a human. Read the transcripts, find the unanswered ones,
show them on the phone. **Zero adoption effort — it captures every question the fleet
already asks.**

I confirmed the payload was in the transcripts. It is. I nearly built on it.

**It does not work, and it fails in the worst possible way.**

Claude Code **does not flush the assistant message until the tool completes.** While a
picker is on screen and the session is genuinely stuck waiting for a human, there is
**nothing on disk**:

```
probe transcript, WHILE the picker was live on screen:
  0: mode
  1: permission-mode
  2: file-history-snapshot
  3: user            | "Use the AskUserQuestion tool right now to ask me to pick a colour…"
  4-8: attachments, ai-title
                     ← and that is the end of the file. No assistant message. No tool_use.
                       File size unchanged for 4 minutes while the picker sat there waiting.
```

The tool_use record appears **only once the question has been answered**. So every ask I
"confirmed" in the transcripts was one that no longer needed answering.

> **A transcript-driven decision queue would show you exactly the questions that don't need
> you, and would be silent about every question that does.** It would have looked like it
> worked. It would have been empty precisely when it mattered, and full of resolved
> questions the rest of the time — which reads as "nothing needs me right now."

Same failure class the fleet spent a day cataloguing: **plausible, self-confirming, silent.**
It only died because it was tested against a live session instead of reasoned about.

---

## What actually works

Two halves, both measured on a live Claude Code session.

### Capture — a `PreToolUse` hook

`bus/ask-capture.sh`, matched on `AskUserQuestion`. `PreToolUse` fires **before** the tool
runs and is handed the full `tool_input`, so we get the question, the options and the
`multiSelect` flag at the only moment they matter — while the human is still needed.

It writes `~/.claude/bus-state/coord/decisions/<session_id>.json`:

```json
{
  "session_id": "…", "cwd": "/home/kyle/Documents/GitHub/foo",
  "asked_epoch": 1783830482.8,
  "questions": [{
    "question": "Which boards should I test on?",
    "header": "Boards", "multiSelect": true,
    "options": [{"label": "Orin", "description": "NVIDIA Jetson Orin board"}, …]
  }]
}
```

A `PostToolUse` hook on the same tool **deletes the record** — so it clears whether Kyle
answered on the phone or walked over and answered at the keyboard. One pending ask per
session (a blocked session cannot ask twice), so the record is keyed on `session_id` and
naturally supersedes itself.

**Zero adoption cost.** No fleet habit to teach, no new command. It captures every native
`AskUserQuestion` the fleet already asks, starting the moment the hook is installed.

**It can never break anything.** It always exits 0 — verified against a non-ask payload,
malformed JSON, and empty stdin. Worst case it writes nothing. An observability feature
must not be able to take the fleet down.

### Answer — keystroke injection into the session's window

Conductor already resolves session → tilix tile → window (`conductor/windows.py`), and
already types `/msg-check` into live sessions. The same channel drives the picker.

**Measured protocol** (every step verified by screenshot + transcript on a live session):

| | keys | verified result |
|---|---|---|
| **Focus** | `wmctrl -i -a <win>` | **Required.** `xdotool type --window` uses XSendEvent, which **VTE/GTK ignore**. Must activate, then type to the focused window. |
| **Single-select** | `<digit>` → `Return` | `"Which colour do you pick?"="Green"` — option 2 selected. |
| **Multi-select** | `<digit>` per choice → `Right` → `Return` | `Right` opens a **built-in review tab** (*"Ready to submit your answers?"* → `1. Submit answers / 2. Cancel`) which reads back the selection before committing. Result: `="Orin, IMX95"` — exactly the two toggled. |
| **Multi-question** | a single-select auto-advances; a multi-select needs its own `Right` | MEASURED through the real API: `["1","1","3","Right","Return"]` → `"Ship it?"="Yes", "Which boards?"="Orin, IMX95"`. The asymmetry matters — emitting a `Right` for both would skip a question and submit it blank, silently. |
| **Free text** | the last numbered option is an **Other** field that accepts typed text | this is the escape hatch for "none of the above" |
| **Decline** | `Escape` | → *"User declined to answer questions"* |

The picker's own review step is a gift: **the confirmation is native.** We are not
inventing a safety net, we are using the one Claude Code already renders.

---

## ⚠️ A bug this found in already-shipped code

**A picker steals typed text into its free-text "Other" field.** Observed directly — a
prompt typed at a session with a picker up did not become a prompt; it became option 5:

```
  4. [ ] RT1180
❯ 5. [ ] Use the AskUserQuestion tool now. ONE question: 'Which boards should I…
```

So **injecting `/msg-check` into a session parked on a picker types it into the picker.**

Today the `WAITING`-status guard accidentally hides this — a session on a picker is
`WAITING`, and `_WAKEABLE_STATUSES` excludes it. But **v2.23.0's autonomy windows
deliberately lift that guard** (`peers_in_window` → `allowed = True` even when `WAITING`),
which is exactly the condition where this fires. A linked session sitting on an ask can
have its picker corrupted by an auto-delivery wake.

**The ask-capture hook is also the fix**: Conductor now *knows* which sessions have a
picker up, so `_inject_msg_check` can refuse to type at them. Capture and safety are the
same signal.

---

## What shipped

* **`GET /api/decisions`** — the pending asks, oldest first. Records whose session is gone
  are dropped (a session killed mid-picker leaves its file behind; that is wreckage, not a
  pending question, and showing it would be a false alarm on the one screen that exists to
  say what genuinely needs you).
* **`POST /api/decisions/{session_id}`** — `{"answers": [["Orin","IMX95"]]}`. Resolves the
  session's window and drives the picker. It refuses rather than guesses: the question must
  still be pending (409 if Kyle already answered at the keyboard), the session must still be
  live, and **every chosen label must exist on the captured question** — a label we can't
  find means our model of the screen is wrong, and pressing a digit anyway would submit an
  answer he never gave.
* **`conductor/decisions.py::plan_keystrokes`** — a pure function, because it is the part
  that must be right. Every failure mode here is silent.
* **The guard**: `_inject_text` refuses to type at a session with a question open.
* **`/api/ops`** and the phone console at **`/m`**, where a pending question is the top item.

The injection is puppeteering a TUI we do not own, so it verifies before it types and leans
on the picker's own review step rather than fabricating a confirmation. If the state doesn't
match what we captured, it does nothing and says so.
