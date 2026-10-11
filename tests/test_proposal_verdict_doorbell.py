"""An approved push-proposal must ride the DOORBELL, not a sentence about the grant.

Kyle, 2026-10-10, from a phone screenshot of the PAI session: *"For some reason pai keeps
getting the long form push msg."*

v2.41 replaced the gate-approval keystroke with a 16-character doorbell (``push approved:
<repo>``) that ``bus.sh``'s hook expands FROM THE GRANT FILE at read time. **That fix was
never carried one branch to the left**, so the push-PROPOSAL verdict — a different endpoint,
reached when a session asks *"should I push now?"* rather than being denied by the gate — kept
typing 136 characters of prose. PAI uses proposals, which is why only PAI saw it.

Both reasons v2.41 gives apply here unchanged, and the second is the serious one:

1. Every extra character is another chance for xdotool keysym remapping to drop or repeat one
   (``waits for youuuuu`` x130 is in the record).
2. **The prose is composed when Kyle taps and typed minutes later, once the session goes
   quiet.** "The approval is already armed" is therefore an assertion about a state the
   sentence cannot see — and the grant is ONE-SHOT, so a push in between consumes it and the
   session is told it holds a permission it does not hold. 95emulator received four such
   notices for a repo with nothing pending.

A doorbell cannot go stale because it carries no claim: the hook reads the grant file and can
say *"there is NO ARMED GRANT for it now"*, which no sentence composed at tap time could.

⚠️ THE ASYMMETRY IS DELIBERATE. A DECLINE keeps its prose, because Kyle's chosen alternative
exists in no file for a hook to expand, and unlike "a grant is armed" a decision he made does
not go stale.

These tests drive the REAL endpoint. Asserting on a re-typed copy of the message-building
logic would pass while the shipped path did anything at all — a mirror, not a test.
"""

from __future__ import annotations

import time

from starlette.testclient import TestClient

from conductor.main import AppState, app
from conductor.settings import load_settings


def _st(tmp_path) -> AppState:
    s = load_settings()
    s.server.auth_token = ""
    st = AppState(s)
    st.coord_root = tmp_path / "coord"
    st.coord_root.mkdir(parents=True, exist_ok=True)
    return st


def _client(st, monkeypatch) -> TestClient:
    monkeypatch.delenv("CONDUCTOR_AUTH_TOKEN", raising=False)
    app.state.cond = st
    return TestClient(app)


def _propose(st, key="pai", alts=("keep digging on the sizer",)):
    st._push_proposals = [{
        "key": key, "repo": f"/home/kyle/{key}", "repo_name": key,
        "cwd": "/home/kyle/x", "why": "tests pass", "alts": list(alts),
        "commits": ["abc thing"], "epoch": int(time.time()),
    }]
    return st


def _notice(st, key="pai"):
    return st._push_notices.get(f"proposal:{key}")


def test_an_approval_queues_no_text_so_the_doorbell_is_used(tmp_path, monkeypatch):
    """The bug Kyle reported. `text` must be ABSENT, not empty-string: the delivery path
    reads `note.get("text") or "push approved: <repo>"`, so a falsy value would also work
    today — but a future `if "text" in note` would silently resurrect the prose."""
    st = _propose(_st(tmp_path))
    c = _client(st, monkeypatch)
    assert c.post("/api/proposals/pai", json={"choice": ""}).status_code == 200
    n = _notice(st)
    assert n is not None, "the verdict must still reach the session"
    assert "text" not in n, f"an approval is carrying prose again: {n.get('text')!r}"


def test_the_delivered_keystroke_is_the_16_char_doorbell(tmp_path, monkeypatch):
    """Pin what actually gets TYPED, by resolving it exactly as the delivery loop does.
    This is the assertion that would have caught the original defect."""
    st = _propose(_st(tmp_path))
    c = _client(st, monkeypatch)
    c.post("/api/proposals/pai", json={"choice": ""})
    n = _notice(st)
    typed = n.get("text") or f"push approved: {n['repo']}"
    assert typed == "push approved: pai"
    assert typed.isascii(), "a non-ASCII keystroke is what xdotool remaps"
    assert "\n" not in typed, "a newline commits the line early"
    assert len(typed) < 40, f"{len(typed)} chars is the long form again"


def test_an_approval_never_asserts_that_a_grant_is_armed(tmp_path, monkeypatch):
    """The staleness bug specifically: no claim about grant state may be composed here,
    because it is typed minutes later and the grant is one-shot."""
    st = _propose(_st(tmp_path))
    c = _client(st, monkeypatch)
    c.post("/api/proposals/pai", json={"choice": ""})
    typed = (_notice(st).get("text") or "").lower()
    for claim in ("armed", "approved the", "covers exactly one", "just run your push"):
        assert claim not in typed, f"re-asserting a state it cannot see: {claim!r}"


def test_a_decline_still_carries_the_alternative_kyle_picked(tmp_path, monkeypatch):
    """The asymmetry. Dropping prose here would lose information no hook can recover —
    and a session told only "not yet" does not know what to do instead."""
    st = _propose(_st(tmp_path), alts=("keep digging on the sizer",))
    c = _client(st, monkeypatch)
    r = c.post("/api/proposals/pai", json={"choice": "keep digging on the sizer"})
    assert r.status_code == 200
    n = _notice(st)
    assert "text" in n, "a decline must carry its reason"
    assert "keep digging on the sizer" in n["text"]
    assert "\n" not in n["text"], "a newline in injected text commits the line early"


def test_a_decline_does_not_arm_a_grant(tmp_path, monkeypatch):
    """Guards the branch itself: the two paths must not have merged."""
    from conductor.coord import read_push_grants
    st = _propose(_st(tmp_path))
    c = _client(st, monkeypatch)
    c.post("/api/proposals/pai", json={"choice": "keep digging on the sizer"})
    assert read_push_grants(st.coord_root) == []


def test_an_unrecognised_choice_is_refused_and_queues_nothing(tmp_path, monkeypatch):
    """A label we don't know means our view of the question is stale. Refusing is right —
    but it must also not leave a verdict queued for a decision Kyle never made."""
    st = _propose(_st(tmp_path))
    c = _client(st, monkeypatch)
    assert c.post("/api/proposals/pai", json={"choice": "something else"}).status_code == 400
    assert _notice(st) is None


def test_the_gate_approval_path_still_uses_the_doorbell_too():
    """Rule 3 from CLAUDE.md: when you fix one site, sweep the tree for the same shape.

    v2.41 fixed the gate branch and the proposal branch was left standing for weeks — the
    same "fixed in one place, left in another" the identity rules were written for. This
    pins the sibling so the pair can only regress together, loudly.

    NOT written as `if hasattr(...)`: a guarded assertion passes silently the day someone
    renames the function, which is a test that cannot fail.
    """
    import inspect

    from conductor import main as m

    assert hasattr(m, "decide_push"), "the gate-approval endpoint was renamed — re-point this"
    body = inspect.getsource(m.decide_push)
    assert "already armed" not in body
    assert "covers exactly one push" not in body
    # and it must still queue a notice at all, or the doorbell is moot
    assert "_push_notices[key]" in body
