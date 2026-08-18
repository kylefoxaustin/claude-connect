"""Broadcast change-gates (docs/V3_REVIEW.md F6).

Conductor pushes its full state to every connected client every 3 s. Three of those
payloads were repeating themselves; the gates here stop that. The rule these tests
exist to enforce is the one the push-grant gate already documents and that the
projects gate then violated one function later:

    ⭐ compare on DURABLE identity, never on a value that ticks —
      a gate keyed on a live field is not a gate, it just costs a comparison.
"""

from __future__ import annotations

from conductor.main import _PROJECT_VOLATILE_JOB_FIELDS, _projects_gate_key


def _proj(assignee_status: str = "active", state: str = "done", extra=None):
    job = {"id": "relwork", "to": "claude-connect", "state": state,
           "assignee_status": assignee_status, "assignee_busy": assignee_status != "offline"}
    if extra:
        job.update(extra)
    return [{"id": "ieee-paper", "lead": "claude-connect", "jobs": [job]}]


def test_gate_ignores_assignee_liveness():
    """active <-> warm is a working session breathing, not a project change.

    MEASURED 2026-08-16: this flip alone defeated the gate on ~9 of every 10 ticks,
    ~414 MB/day per client of a payload that had not meaningfully changed.
    """
    assert _projects_gate_key(_proj("active")) == _projects_gate_key(_proj("warm"))
    assert _projects_gate_key(_proj("active")) == _projects_gate_key(_proj("offline"))


def test_gate_still_fires_on_real_change():
    """The gate must not be so eager that it hides work actually moving."""
    assert _projects_gate_key(_proj(state="done")) != _projects_gate_key(_proj(state="dispatched"))
    assert _projects_gate_key(_proj()) != _projects_gate_key(_proj(extra={"spend": 1200}))
    assert _projects_gate_key([]) != _projects_gate_key(_proj())


def test_gate_is_order_stable_and_hashable():
    """Same content, different dict ordering -> same key (else it never gates)."""
    a = [{"id": "p", "jobs": [{"id": "j", "state": "done", "to": "x"}]}]
    b = [{"jobs": [{"to": "x", "state": "done", "id": "j"}], "id": "p"}]
    assert _projects_gate_key(a) == _projects_gate_key(b)
    assert isinstance(_projects_gate_key(a), str)


def test_gate_survives_unexpected_shapes():
    """Never raise inside the scan loop: a malformed record must not kill the tick."""
    assert _projects_gate_key([{"id": "p"}])                       # no jobs key
    assert _projects_gate_key([{"id": "p", "jobs": None}])         # jobs not a list
    assert _projects_gate_key([{"id": "p", "jobs": ["oops", 3]}])  # jobs not dicts


def test_volatile_field_list_is_actually_applied():
    """Guards against the list drifting away from the stripping code."""
    key = _projects_gate_key(_proj())
    for f in _PROJECT_VOLATILE_JOB_FIELDS:
        assert f not in key, f"{f} must not appear in the gate key"


# --------------------------------------------------------------------------
# thin_unchanged_keys — delta-by-omission on the sessions broadcast
#
# MEASURED 2026-08-16: `parked` (13.4 KB) and `members` (5.8 KB) changed ZERO times
# across 8 consecutive broadcasts while `sessions` changed every one — 83% of a
# 23.2 KB payload retransmitted every 3 s. The contract these pin is the dangerous
# part: ABSENT means "unchanged, keep yours", never "empty".
# --------------------------------------------------------------------------

from conductor.main import thin_unchanged_keys

KEYS = ("parked", "members")


def test_first_call_sends_everything_then_omits_unchanged():
    d: dict[str, str] = {}
    full = {"sessions": [1], "parked": ["a"], "members": {"x": 1}}
    first = thin_unchanged_keys(full, d, KEYS)
    assert first == full, "a client with no prior state must get everything"

    second = thin_unchanged_keys(full, d, KEYS)
    assert "parked" not in second and "members" not in second
    assert second["sessions"] == [1], "volatile keys are never thinned"


def test_a_changed_key_is_resent():
    d: dict[str, str] = {}
    thin_unchanged_keys({"parked": ["a"], "members": {}}, d, KEYS)
    out = thin_unchanged_keys({"parked": ["a", "b"], "members": {}}, d, KEYS)
    assert out["parked"] == ["a", "b"]
    assert "members" not in out


def test_emptying_a_key_is_a_CHANGE_and_must_be_sent():
    """The nastiest case: all parked sessions go live, so `parked` becomes [].

    If emptiness were confused with absence the dock would never clear.
    """
    d: dict[str, str] = {}
    thin_unchanged_keys({"parked": ["a"]}, d, KEYS)
    out = thin_unchanged_keys({"parked": []}, d, KEYS)
    assert "parked" in out and out["parked"] == []


def test_force_full_resends_and_reseeds():
    d: dict[str, str] = {}
    payload = {"parked": ["a"], "members": {"x": 1}}
    thin_unchanged_keys(payload, d, KEYS)
    assert "parked" not in thin_unchanged_keys(payload, d, KEYS)
    forced = thin_unchanged_keys(payload, d, KEYS, force_full=True)
    assert forced == payload, "the periodic full send must carry everything"
    assert "parked" not in thin_unchanged_keys(payload, d, KEYS), "and reseed the digests"


def test_missing_key_is_not_invented():
    d: dict[str, str] = {}
    out = thin_unchanged_keys({"sessions": []}, d, KEYS)
    assert "parked" not in out and "members" not in out
    assert d == {}, "absent keys must not seed a digest"


def test_does_not_mutate_the_source_payload():
    d: dict[str, str] = {}
    full = {"sessions": [1], "parked": ["a"]}
    thin_unchanged_keys(full, d, KEYS)
    thin_unchanged_keys(full, d, KEYS)
    assert full == {"sessions": [1], "parked": ["a"]}, "REST/connect must still see it whole"


def test_key_order_does_not_defeat_the_digest():
    d: dict[str, str] = {}
    thin_unchanged_keys({"members": {"a": 1, "b": 2}}, d, KEYS)
    out = thin_unchanged_keys({"members": {"b": 2, "a": 1}}, d, KEYS)
    assert "members" not in out, "same content, different order -> still unchanged"
