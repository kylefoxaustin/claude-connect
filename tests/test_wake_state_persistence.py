"""The wake-state round trip.

Regression guard for the defect measured 2026-09-17: write_wake_state persisted
only ``[v[0], v[1]]`` while the scanner stored a 4-tuple, and read_wake_state
accepted only ``len == 2``. The activity stamp never survived a restart, so
_unpack_wake defaulted it to +inf and the lost-keystroke retry — "the transcript
MOVED while the watermark did NOT" — could never fire again. Four live sessions
held 2,475 unread messages, each with its dedup key pinned to a watermark that
only a successful read could advance.
"""
import json
from conductor.coord import read_wake_state, write_wake_state
from conductor.main import _unpack_wake

FULL = ("2026-09-17 19:00:00", 1789690000.0, 1789689000.0, "2026-09-17 18:59")


def test_activity_stamp_survives_the_round_trip(tmp_path):
    write_wake_state(tmp_path, {"[x]": FULL})
    _, _, activity, latest = _unpack_wake(read_wake_state(tmp_path)["[x]"])
    assert activity == FULL[2], "activity stamp lost -> retry permanently blocked"
    assert latest == FULL[3]


def test_all_four_fields_reach_disk(tmp_path):
    write_wake_state(tmp_path, {"[x]": FULL})
    raw = json.loads((tmp_path / "wake-state.json").read_text())
    assert len(raw["[x]"]) == 4, "a truncated write is what caused the original defect"


def test_legacy_two_element_entry_still_loads_and_stays_retry_blocked(tmp_path):
    # Dropping short entries would re-prod every session with unread mail on the
    # next restart -- the storm this state is persisted to prevent.
    (tmp_path / "wake-state.json").write_text(
        json.dumps({"[old]": ["2026-08-02 10:44:16", 1787021466.9]})
    )
    state = read_wake_state(tmp_path)
    assert "[old]" in state, "legacy entry dropped -> boot storm"
    _, _, activity, _ = _unpack_wake(state["[old]"])
    assert activity == float("inf")


def test_three_element_entry_is_tolerated(tmp_path):
    (tmp_path / "wake-state.json").write_text(
        json.dumps({"[mid]": ["2026-09-01 00:00", 1789000000.0, 1788999000.0]})
    )
    _, _, activity, latest = _unpack_wake(read_wake_state(tmp_path)["[mid]"])
    assert activity == 1788999000.0
    assert latest == ""


def test_garbage_entry_is_skipped_not_fatal(tmp_path):
    (tmp_path / "wake-state.json").write_text(
        json.dumps({"[bad]": ["only-one"], "[ok]": list(FULL)})
    )
    state = read_wake_state(tmp_path)
    assert "[bad]" not in state and "[ok]" in state
