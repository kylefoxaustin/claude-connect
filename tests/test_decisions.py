"""The decision queue.

``plan_keystrokes`` is the load-bearing part: it turns "Kyle tapped Orin and IMX95" into
literal keys pressed in someone's terminal. Every failure mode here is SILENT — a wrong
digit doesn't raise, it submits an answer he never gave and the Claude proceeds on it
confidently. So it refuses far more eagerly than it guesses.

The key sequences below are not invented; they were measured against a live Claude Code
session (see docs/DECISION_QUEUE.md).
"""

from __future__ import annotations

import json
import time

import pytest

from conductor.decisions import STALE_AFTER_S, plan_keystrokes, read_decisions, reap_decision


def _q(question="Pick one", *, multi=False, opts=("A", "B", "C")):
    return {
        "question": question,
        "header": "H",
        "multiSelect": multi,
        "options": [{"label": o, "description": ""} for o in opts],
    }


# --- the measured sequences --------------------------------------------------
def test_single_select_is_digit_then_confirm():
    """MEASURED: pressing "2" then Return on a live picker returned "…"="Green"."""
    assert plan_keystrokes([_q(opts=("Red", "Green", "Blue"))], [["Green"]]) == ["2", "Return"]


def test_multi_select_toggles_then_opens_the_review_tab():
    """MEASURED: ["1", "3", "Right", "Return"] returned "…"="Orin, IMX95".

    The ``Right`` is load-bearing: a multi-select question does NOT submit when you toggle,
    it waits at the picker's own review tab ("Ready to submit your answers?"). Without it
    the Return lands on a checkbox and toggles it back off.
    """
    q = _q(multi=True, opts=("Orin", "IQ9", "IMX95", "RT1180"))
    assert plan_keystrokes([q], [["Orin", "IMX95"]]) == ["1", "3", "Right", "Return"]


def test_multi_select_of_one_still_needs_the_review_tab():
    q = _q(multi=True, opts=("Orin", "IQ9"))
    assert plan_keystrokes([q], [["IQ9"]]) == ["2", "Right", "Return"]


def test_two_questions_single_then_multi():
    """MEASURED end-to-end through POST /api/decisions:
        ["1", "1", "3", "Right", "Return"]
        -> "Ship it?"="Yes", "Which boards?"="Orin, IMX95"

    Note the asymmetry, which is the whole reason this is a test and not an assumption:
    a SINGLE-select question auto-advances to the next tab when you pick, so it needs no
    "Right" — but a MULTI-select one does. Emitting a "Right" for both would skip a
    question and submit it blank, and it would do that silently.
    """
    qs = [
        _q("Ship it?", multi=False, opts=("Yes", "No")),
        _q("Which boards?", multi=True, opts=("Orin", "IQ9", "IMX95")),
    ]
    assert plan_keystrokes(qs, [["Yes"], ["Orin", "IMX95"]]) == \
        ["1", "1", "3", "Right", "Return"]


def test_option_order_is_what_maps_to_the_digit():
    q = _q(opts=("zeta", "alpha", "mid"))
    assert plan_keystrokes([q], [["zeta"]]) == ["1", "Return"]     # not alphabetical
    assert plan_keystrokes([q], [["mid"]]) == ["3", "Return"]


# --- it must refuse rather than guess ----------------------------------------
def test_an_unknown_label_refuses():
    """The capture is our only model of what's on screen. If the answer names something
    that isn't on it, our model is wrong — and pressing a digit anyway would submit
    whatever happens to be at that position."""
    with pytest.raises(ValueError, match="not an option"):
        plan_keystrokes([_q()], [["Nonexistent"]])


def test_two_answers_to_a_single_select_refuses():
    with pytest.raises(ValueError, match="single-select"):
        plan_keystrokes([_q(multi=False)], [["A", "B"]])


def test_an_empty_answer_refuses():
    with pytest.raises(ValueError, match="no option chosen"):
        plan_keystrokes([_q()], [[]])


def test_wrong_number_of_answers_refuses():
    with pytest.raises(ValueError, match="expected 2"):
        plan_keystrokes([_q(), _q()], [["A"]])


def test_more_than_nine_options_refuses():
    """The picker numbers 1-9. A 10th option needs arrow navigation, which we have not
    measured — so we decline instead of pressing "1" and hoping."""
    q = _q(opts=tuple(f"o{i}" for i in range(10)))
    with pytest.raises(ValueError, match="more than 9"):
        plan_keystrokes([q], [["o9"]])


# --- reading the queue -------------------------------------------------------
def test_reads_pending_questions_oldest_first(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    now = time.time()
    for sid, age in (("new", 10), ("old", 600), ("mid", 120)):
        (d / f"{sid}.json").write_text(json.dumps({
            "session_id": sid, "cwd": "/x", "asked_epoch": now - age,
            "questions": [_q()],
        }))
    got = read_decisions(tmp_path, now=now)
    assert [r["session_id"] for r in got] == ["old", "mid", "new"]


def test_a_stale_record_is_not_a_pending_question(tmp_path):
    """A session killed mid-picker leaves its file behind. Showing it would be a false
    alarm on the one screen that exists to tell you what genuinely needs you."""
    d = tmp_path / "decisions"
    d.mkdir()
    now = time.time()
    (d / "ghost.json").write_text(json.dumps({
        "session_id": "ghost", "cwd": "/x", "asked_epoch": now - STALE_AFTER_S - 1,
        "questions": [_q()],
    }))
    assert read_decisions(tmp_path, now=now) == []


def test_garbage_never_crashes_a_scan(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "half-written.json").write_text('{"session_id": "x", "quest')
    (d / "empty.json").write_text("{}")
    assert read_decisions(tmp_path) == []


def test_missing_dir_is_just_empty(tmp_path):
    assert read_decisions(tmp_path) == []


def test_reap_is_idempotent(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "s.json").write_text(json.dumps(
        {"session_id": "s", "cwd": "/x", "asked_epoch": time.time(), "questions": [_q()]}))
    reap_decision(tmp_path, "s")
    reap_decision(tmp_path, "s")          # already gone — must not raise
    assert read_decisions(tmp_path) == []


# --- the guard: a picker eats keystrokes -------------------------------------
# This is not hypothetical. Observed on a live session: a prompt typed at a Claude that
# had a picker open did not become a prompt — it became option 5 of the menu:
#
#     4. [ ] RT1180
#   > 5. [ ] Use the AskUserQuestion tool now. ONE question: 'Which boards should I…
#
# So injecting `/msg-check` at a session that is asking Kyle a question corrupts the very
# question he is about to answer. The WAITING-status guard used to hide this by accident —
# but autonomy windows deliberately lift that guard, which is exactly when it fires.
import asyncio
import types

from conductor.main import AppState
from conductor.models import Status
from conductor.settings import load_settings


def _app(tmp_path):
    s = AppState(load_settings())
    s.coord_root = tmp_path / "coord"
    s._wake_outstanding = {}
    return s


def _rec(project_dir, session_id="s1"):
    return types.SimpleNamespace(
        tag="[other:x]", status=Status.IDLE, pid=1, terminal_pid=2,
        title="t", window_title="w", project_dir=project_dir, session_id=session_id)


def test_decision_matches_by_session_id_even_when_cwd_differs(tmp_path):
    """The bug: a session that cd'd (or whose launch cwd != proc.cwd) has a decision cwd that
    does NOT equal its project_dir, so a cwd-only join dropped the question off the phone.
    session_id is the exact join key — the record is literally named <session_id>.json."""
    app = _app(tmp_path)
    rec = _rec(str(tmp_path / "proj"), session_id="abc123")
    app.sessions = {"k": rec}
    d = {"session_id": "abc123", "cwd": str(tmp_path / "proj" / "sub" / "deeper")}
    assert app._session_for_decision(d) is rec


def test_decision_falls_back_to_cwd_when_no_session_id(tmp_path):
    app = _app(tmp_path)
    rec = _rec(str(tmp_path / "proj"), session_id="abc123")
    app.sessions = {"k": rec}
    d = {"session_id": "", "cwd": str(tmp_path / "proj")}
    assert app._session_for_decision(d) is rec


def test_decision_for_a_dead_session_is_dropped(tmp_path):
    """No live session with that id and no cwd match -> None, so a session killed mid-picker
    leaves no phantom question in the queue."""
    app = _app(tmp_path)
    rec = _rec(str(tmp_path / "proj"), session_id="abc123")
    app.sessions = {"k": rec}
    d = {"session_id": "GONE", "cwd": str(tmp_path / "elsewhere")}
    assert app._session_for_decision(d) is None


def test_never_types_at_a_session_with_a_question_open(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app.decisions = [{"session_id": "s1", "cwd": str(tmp_path / "proj"),
                      "questions": [_q()], "age": 5.0}]
    sent = []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: sent.append(kw) or True)

    ok = asyncio.run(app._inject_text(_rec(str(tmp_path / "proj")), "/msg-check", "test"))

    assert ok is False
    assert sent == []          # the keystrokes were never dispatched


def test_a_session_without_a_question_is_still_reachable(tmp_path, monkeypatch):
    """The guard must be surgical. If it silenced auto-delivery generally it would break
    the feature it's protecting."""
    app = _app(tmp_path)
    app.decisions = [{"session_id": "s1", "cwd": str(tmp_path / "other"),
                      "questions": [_q()], "age": 5.0}]
    sent = []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: sent.append(kw) or True)

    # A DIFFERENT session (distinct id + cwd) than the one with the open question — real
    # session_ids are unique, so it matches neither the decision's id nor its cwd.
    ok = asyncio.run(app._inject_text(
        _rec(str(tmp_path / "proj"), session_id="s2"), "/msg-check", "test"))

    assert ok is True
    assert len(sent) == 1


# --- session->decision lookup (the #2 UX fix: a wake refused because a session is asking
#     YOU should route you to answer, not silently no-op). Reuses _app/_rec above. -----
def test_decision_for_matches_by_session_id_then_cwd(tmp_path):
    app = _app(tmp_path)
    rec = _rec(str(tmp_path / "proj"), session_id="sX")
    # session_id join wins even when the decision's cwd differs (session cd'd away)
    app.decisions = [{"session_id": "sX", "cwd": str(tmp_path / "proj" / "sub"),
                      "questions": [{"question": "Reboot?"}]}]
    d = app._decision_for(rec)
    assert d is not None and d["session_id"] == "sX"
    assert app._has_open_picker(rec) is True


def test_decision_for_falls_back_to_cwd(tmp_path):
    app = _app(tmp_path)
    rec = _rec(str(tmp_path / "proj"), session_id="sX")
    app.decisions = [{"session_id": "", "cwd": str(tmp_path / "proj"),
                      "questions": [{"question": "Q?"}]}]
    assert app._decision_for(rec) is not None
    assert app._has_open_picker(rec) is True


def test_decision_for_none_when_not_asking(tmp_path):
    app = _app(tmp_path)
    rec = _rec(str(tmp_path / "proj"), session_id="sX")
    app.decisions = []
    assert app._decision_for(rec) is None
    assert app._has_open_picker(rec) is False
    # a decision for a DIFFERENT session/cwd doesn't match this one
    app.decisions = [{"session_id": "other", "cwd": str(tmp_path / "elsewhere"),
                      "questions": [{"question": "Q?"}]}]
    assert app._decision_for(rec) is None


# ── free text via the picker's "Other" field, and declining ────────────────────
# The digit protocol was measured on a live picker; so was the existence of an Other
# field as the LAST numbered option, and Escape as a real decline. What is NOT yet
# measured is whether Other needs its own Return before the review tab — the plan
# therefore emits exactly one, and that count is asserted here so a change to it is a
# deliberate act with a failing test, not a silent edit.

_ABC = ("A", "B", "C")


def test_other_is_numbered_after_the_real_options():
    from conductor.decisions import OTHER_TEXT, TYPE_PREFIX, plan_keystrokes
    keys = plan_keystrokes([_q()], [[OTHER_TEXT + "my own words"]])
    # 3 captured options -> the picker renders Other as 4
    assert keys == ["4", TYPE_PREFIX + "my own words", "Return"]
    assert keys.count("Return") == 1, "exactly one Return — see the UNVERIFIED note"


def test_other_index_tracks_the_option_count():
    from conductor.decisions import OTHER_TEXT, plan_keystrokes
    for n in (1, 5, 8):
        opts = tuple(chr(ord("A") + i) for i in range(n))
        assert plan_keystrokes([_q(opts=opts)], [[OTHER_TEXT + "x"]])[0] == str(n + 1)


def test_refuses_unreachable_other():
    from conductor.decisions import OTHER_TEXT, plan_keystrokes
    # 9 options -> Other would be 10, and the picker only numbers 1-9. Refuse rather
    # than press a digit that means something else.
    opts = tuple(chr(ord("A") + i) for i in range(9))
    with pytest.raises(ValueError, match="more than 8 options"):
        plan_keystrokes([_q(opts=opts)], [[OTHER_TEXT + "x"]])


def test_refuses_empty_and_multiline_free_text():
    from conductor.decisions import OTHER_TEXT, plan_keystrokes
    with pytest.raises(ValueError, match="empty"):
        plan_keystrokes([_q()], [[OTHER_TEXT + "   "]])
    # a newline would commit the picker mid-sentence and submit a truncated answer
    with pytest.raises(ValueError, match="single line"):
        plan_keystrokes([_q()], [[OTHER_TEXT + "line one\nline two"]])


def test_free_text_cannot_be_mixed_with_a_picked_option():
    from conductor.decisions import OTHER_TEXT, plan_keystrokes
    with pytest.raises(ValueError):
        plan_keystrokes([_q(multi=True)], [["A", OTHER_TEXT + "and also this"]])


def test_normal_picks_are_byte_for_byte_unchanged():
    """The free-text branch must not perturb the measured digit protocol."""
    from conductor.decisions import plan_keystrokes
    assert plan_keystrokes([_q()], [["B"]]) == ["2", "Return"]
    assert plan_keystrokes([_q(multi=True)], [["A", "C"]]) == ["1", "3", "Right", "Return"]


def test_sender_and_planner_agree_on_the_type_prefix():
    """A mismatch would make the sender PRESS a key literally named '\\x00type:hello'."""
    from conductor.decisions import TYPE_PREFIX
    from conductor.windows import TYPE_ACTION
    assert TYPE_ACTION == TYPE_PREFIX
