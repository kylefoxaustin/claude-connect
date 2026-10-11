"""A push verdict must reach the session that asked — and say so when it cannot.

Kyle tapped Approve SIX times for two repos because each tap appeared to do nothing
(agentic-skills-imx, 2026-10-10). The approval was granted, the tokens were correct and
matched HEAD, and the work sat unpushed because nobody told the session.

ROOT CAUSE: **two writers disagree about one field.**

    bus/push-gate.sh      (tool layer)  cwd=$CWD   <- the SESSION's directory
    ~/.claude/git-hooks/pre-push        cwd=$PWD   <- git runs hooks from the REPO TOPLEVEL

Delivery resolved the recipient with ``_session_for_cwd``, which demands an exact
``project_dir == cwd`` match — and its docstring even asserts the assumption, *"the gate
records the session's cwd"*, which is true for one writer and false for the other. A session
pushing a repo other than its own project filed a cwd no session lives in.

⭐ The reporter's own evidence states it better than the cross-repo framing: in ONE session,
minutes apart, a SPURIOUS request filed by the tool layer delivered perfectly while both
GENUINE pushes resolved to None. **Deliverability tracked which code path filed the request,
not whether the request was real.**

Two defects, and the second is why it went unnoticed for so long:

1. ROUTING — a proxy (cwd) stood in for identity, and the proxy drifted. CLAUDE.md rule 2.
2. SILENCE — "nobody to tell" and "busy, retry shortly" took the SAME ``continue``. An
   undeliverable verdict was indistinguishable from patience: nothing logged, nothing
   surfaced, dropped an hour later with the comment "it'll find out by pushing".

Rule 1 of this project: an absence must not be reported by the same silence as a success.
"""

from __future__ import annotations

import logging

from conductor.main import AppState, _BUSY_STATUSES
from conductor.models import SessionRecord, Status
from conductor.settings import load_settings


def _st() -> AppState:
    s = load_settings()
    s.server.auth_token = ""
    return AppState(s)


def _sess(st, *, sid, cwd, status=Status.IDLE):
    """A REAL SessionRecord, every required field supplied.

    conftest.py records why this matters: a fake missing a field the real object always
    carries is a fake that passes while production crashes on the same line.
    """
    r = SessionRecord(session_id=sid, pid=4242, terminal_pid=None, project_dir=cwd,
                      title=cwd.rsplit("/", 1)[-1], status=status,
                      last_activity_at=0.0, message_count=0, tag=f"[other:{sid}]")
    st.sessions[cwd] = r
    return r


# ---- routing -------------------------------------------------------------------------

def test_the_reported_bug_a_cross_repo_push_is_now_routed():
    """The exact live shape: the session lives in agentic-skills-imx, the request carries
    the repo toplevel it pushed. cwd can never match; the session_id must carry it."""
    st = _st()
    _sess(st, sid="sid-imx", cwd="/home/kyle/Documents/GitHub/agentic-skills-imx")
    note = {"session_id": "sid-imx",
            "cwd": "/home/kyle/Documents/GitHub/imx95-device-skills",   # no session lives here
            "repo": "imx95-device-skills"}
    rec, why = st._session_for_push(note)
    assert rec is not None and why == ""
    assert rec.session_id == "sid-imx"


def test_without_an_id_it_still_falls_back_to_cwd():
    """Older gates omit session_id. Nothing may regress before the gate patch is installed."""
    st = _st()
    _sess(st, sid="sid-a", cwd="/home/kyle/p/a")
    rec, why = st._session_for_push({"cwd": "/home/kyle/p/a"})
    assert rec is not None and rec.session_id == "sid-a" and why == ""


def test_an_id_that_matches_nothing_does_NOT_fall_back_to_cwd():
    """The id is the stronger key. Falling back on a miss is how a verdict reaches the wrong
    twin when two sessions share one repo — a measured condition here (detect_collisions)."""
    st = _st()
    _sess(st, sid="sid-live", cwd="/home/kyle/p/shared")
    rec, why = st._session_for_push({"session_id": "sid-GONE", "cwd": "/home/kyle/p/shared"})
    assert rec is None and why == "unroutable"


def test_an_ended_session_is_never_a_recipient():
    st = _st()
    _sess(st, sid="sid-dead", cwd="/home/kyle/p/d", status=Status.ENDED)
    assert st._session_for_push({"session_id": "sid-dead"})[0] is None


# ---- the silence, which is the reason it took six taps to notice ---------------------

def test_unroutable_and_busy_are_DIFFERENT_outcomes():
    """These shared one `continue`. Conflating them is what made the failure invisible."""
    st = _st()
    busy_status = next(iter(_BUSY_STATUSES))
    _sess(st, sid="sid-busy", cwd="/home/kyle/p/b", status=busy_status)
    assert st._session_for_push({"session_id": "sid-busy"})[1] == "busy"
    assert st._session_for_push({"session_id": "sid-none"})[1] == "unroutable"


def test_an_unroutable_verdict_is_logged_once_not_per_tick(caplog):
    """It must say so — and exactly once. Logging per tick is the storm v2.26.1 and v2.39
    exist to end (744 injections / 101,345 characters in one five-hour episode)."""
    import asyncio
    st = _st()
    st._push_notices["k"] = {"cwd": "/nope", "repo": "r", "queued": 9e9, "session_id": ""}
    with caplog.at_level(logging.WARNING, logger="conductor"):
        for _ in range(5):
            asyncio.run(st._deliver_push_notices())
    hits = [r for r in caplog.records if "UNROUTABLE" in r.getMessage()]
    assert len(hits) == 1, f"logged {len(hits)} times, want exactly 1"
    assert "r" in hits[0].getMessage()


def test_an_unroutable_notice_is_KEPT_not_discarded():
    """A session may yet appear in that directory, and the verdict is still true."""
    import asyncio
    st = _st()
    st._push_notices["k"] = {"cwd": "/nope", "repo": "r", "queued": 9e9, "session_id": ""}
    asyncio.run(st._deliver_push_notices())
    assert "k" in st._push_notices


def test_the_resolver_names_which_key_it_failed_on(caplog):
    """A log line that does not say WHICH key missed cannot be acted on."""
    import asyncio
    st = _st()
    st._push_notices["k"] = {"cwd": "/x", "repo": "r", "queued": 9e9, "session_id": "sid-Q"}
    with caplog.at_level(logging.WARNING, logger="conductor"):
        asyncio.run(st._deliver_push_notices())
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "sid-Q" in msg and "session_id" in msg


def test_the_OLD_cwd_only_resolver_provably_cannot_route_the_reported_case():
    """The other half of the proof, and the one that cannot rot.

    It is not enough to show the new resolver works; this pins WHY it was needed, by
    asserting that the resolver still used as the fallback genuinely fails on the exact live
    input. If someone "simplifies" _session_for_push back to cwd-only, the test above would
    still pass against a fixture that happens to share a directory — this one would not.
    """
    st = _st()
    _sess(st, sid="sid-imx", cwd="/home/kyle/Documents/GitHub/agentic-skills-imx")
    # what the pre-push hook actually filed, measured from the live request files
    assert st._session_for_cwd("/home/kyle/Documents/GitHub/imx95-device-skills") is None
    assert st._session_for_cwd("/home/kyle/Documents/GitHub/imx95-bsp-skills") is None
    # ...while the SPURIOUS request the tool layer filed was perfectly deliverable. Same
    # session, minutes apart, opposite outcomes: deliverability tracked the code path that
    # filed the request, not whether the request was real.
    assert st._session_for_cwd("/home/kyle/Documents/GitHub/agentic-skills-imx") is not None
