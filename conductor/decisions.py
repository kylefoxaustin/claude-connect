"""The decision queue — questions a Claude is blocked on, answerable from anywhere.

Kyle's ask: *"a Claude is giving me choices to make — 1 or 2, or select several — and
submit it back. Responding unblocks a lot of work that I have to walk to the PC for."*

Two facts make this work, and one of them is a trap. See ``docs/DECISION_QUEUE.md``.

**The trap:** you cannot read a pending question out of the session transcript. Claude
Code does not flush the assistant message until the tool completes, so while a picker is
on screen and the session is genuinely stuck, there is *nothing on disk*. The record
appears only once the question has been answered. A transcript-driven queue would show you
exactly the questions that no longer need you, and stay silent about every one that does.

**What works:** a ``PreToolUse(AskUserQuestion)`` hook (``bus/ask-capture.sh``) writes the
question to ``coord/decisions/<session_id>.json`` *before* the picker renders; a
``PostToolUse`` hook deletes it when it is answered — by us, or by Kyle at the keyboard.

Answering is a keystroke sequence into the session's terminal. That is puppeteering a TUI
we do not own, so it is done conservatively: we plan the keys from the *captured* question,
we refuse if the capture no longer matches, and we lean on the picker's OWN review step
(``Right`` → "Ready to submit your answers?" → ``Return``) rather than inventing a
confirmation of our own.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("conductor.decisions")

# A record whose session has been gone this long is wreckage, not a pending question: a
# session killed mid-picker leaves its file behind. Surfacing it would be crying wolf.
STALE_AFTER_S = 24 * 3600


def decisions_dir(coord_root: Path) -> Path:
    return coord_root / "decisions"


def read_decisions(coord_root: Path, *, now: float | None = None) -> list[dict[str, Any]]:
    """Every pending question, oldest first (the one that has been waiting longest)."""
    now = time.time() if now is None else now
    out: list[dict[str, Any]] = []
    d = decisions_dir(coord_root)
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                      # half-written or garbage: skip, never crash a scan
        if not rec.get("session_id") or not rec.get("questions"):
            continue
        asked = float(rec.get("asked_epoch") or 0.0)
        if now - asked > STALE_AFTER_S:
            continue
        rec["age"] = max(0.0, now - asked)
        out.append(rec)
    out.sort(key=lambda r: -r["age"])
    return out


def reap_decision(coord_root: Path, session_id: str) -> None:
    """Drop a record. Called after we answer, so the queue empties without waiting for the
    PostToolUse hook to land (it will, but the phone should not show a stale item for a
    scan tick)."""
    try:
        os.unlink(decisions_dir(coord_root) / f"{session_id}.json")
    except OSError:
        pass


def plan_keystrokes(
    questions: list[dict[str, Any]],
    answers: list[list[str]],
) -> list[str]:
    """Turn chosen option labels into the exact keys that drive Claude Code's picker.

    Measured against a live session (see ``docs/DECISION_QUEUE.md``):

      * the options are a numbered list — pressing the digit selects (single) or
        toggles (multi) that option;
      * for a **single-select** question the digit alone commits and advances;
      * for a **multi-select** question you toggle each choice, and the selection is
        *not* submitted until you reach the picker's own review tab;
      * ``Right`` moves between question tabs, and past the last question it lands on
        that review tab (``"Ready to submit your answers?"`` → ``1. Submit answers``),
        where ``Return`` commits.

    So a multi-select question needs an explicit ``Right``; a single-select one does not,
    because choosing already advanced it. The final ``Return`` confirms the review.

    Pure function — no I/O, no X11 — because it is the part that must be right. Getting it
    wrong doesn't error, it silently submits an answer Kyle never gave.

    Raises ValueError if an answer names an option that isn't on the question. We would
    rather refuse than press a digit we guessed at.
    """
    if len(answers) != len(questions):
        raise ValueError(
            f"expected {len(questions)} answer(s), got {len(answers)}")

    keys: list[str] = []
    for q, chosen in zip(questions, answers):
        opts = [o.get("label", "") for o in (q.get("options") or [])]
        multi = bool(q.get("multiSelect"))
        if not chosen:
            raise ValueError(f"no option chosen for {q.get('question', '?')!r}")
        if not multi and len(chosen) > 1:
            raise ValueError(
                f"{q.get('question', '?')!r} is single-select but {len(chosen)} options were chosen")
        for label in chosen:
            if label not in opts:
                raise ValueError(f"{label!r} is not an option of {q.get('question', '?')!r}")
            idx = opts.index(label) + 1
            if idx > 9:
                # The picker numbers options 1-9; a 10th would need arrow navigation and we
                # have not measured that. Refuse rather than press a digit that means
                # something else.
                raise ValueError("cannot answer a question with more than 9 options")
            keys.append(str(idx))
        if multi:
            keys.append("Right")     # single-select already advanced when we picked
    keys.append("Return")            # confirm on the review tab
    return keys


# MEASURED, on a live session:
#   single-select, one question :  ["2", "Return"]                  -> "…"="Green"
#   multi-select,  one question :  ["1", "3", "Right", "Return"]    -> "…"="Orin, IMX95"
# The multi-QUESTION path (whether a single-select answer auto-advances to the next
# question's tab, or needs its own "Right") is verified by tests/live_decision_probe.py
# rather than assumed — an extra "Right" would skip a question and submit a blank one,
# and it would do it silently.

