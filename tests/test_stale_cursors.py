"""The stale-read-cursor alarm — and the reason it is scoped to live members.

image_gen's bus watermark sat at 2026-07-28 while the log ran on to 2026-08-24, and nothing
said a word. That failure is self-concealing: a stuck cursor and a genuinely quiet inbox
produce the identical observation — the number goes up. It surfaced only because a human
thought 157 unread looked absurd for a quiet mailbox.

⚠️ AND THE OBVIOUS VERSION OF THIS ALARM WOULD HAVE BEEN NOISE, which is the whole design.
"Cursor is old" fires on the graveyard: sorted by watermark this fleet has readers at
2026-06-14, 06-28, 06-30, 07-04 — nearly all dormant or deleted projects. image_gen itself
was CLOSED for the three weeks in question (116 transcript records on Jul 28, three on Aug 6,
all of them `/exit`, then nothing until Aug 24). A closed session's cursor is *supposed* to
stand still: no turns, no reads, no commits, no defect.

⭐ So the function stays pure and reports age for every cursor; the caller alarms on live
members only. Scoped that way it would have said nothing about image_gen — correctly — and
everything about a session that is running and not reading.
"""

from __future__ import annotations

import sys
import time

import pytest

from conductor.deps import stale_cursors

# ⚠️ must be LATER than every timestamp in the fixtures below. The first value here was a
# year earlier, which made every 'unread' message sit in the future and every age negative —
# the tests failed for a reason that had nothing to do with the code under test.
NOW = 1_787_600_000.0        # 2026-08-24 ~18:00 UTC
HOUR = 3600.0


def bus(tmp_path, *msgs):
    """msgs = "ts" (a broadcast) or ("ts", "to:tag") — the address line is what makes it DIRECTED."""
    out = []
    for m in msgs:
        ts, first = (m, "body") if isinstance(m, str) else m
        out.append(f"## {ts} [other:sender]\n\n{first} — body\n\n")
    p = tmp_path / "messages.md"
    p.write_text("".join(out), encoding="utf-8")
    return p


def cursors(tmp_path, **tag_to_ts: str):
    d = tmp_path / "bus-state"
    d.mkdir(exist_ok=True)
    for tag, ts in tag_to_ts.items():
        (d / f"{tag.replace('__', ':')}.last-seen").write_text(ts + "\n", encoding="utf-8")
    return d


# ⚠️ A COLON IN A TAG CANNOT BE A FILENAME ON NTFS, and this is a PRODUCT defect, not a fixture
# one — which is why the rows below are xfail(strict) rather than skipped.
#
# The cursor file is `<tag>.last-seen` (conductor/bus.py:402, bus.sh `_cursor_put_seen`), and real
# tags carry a colon: `other:image_gen`, `other:qualcomm`. On NTFS `other:image_gen.last-seen`
# does not name a file — the colon opens an ALTERNATE DATA STREAM, so the bytes land on a stream
# of a file called `other` and `glob("*.last-seen")` returns nothing. No error is raised at any
# point: the write "succeeds" and the read finds an empty fleet.
#
# Measured 2026-08-30 on Windows 11. It is the same root cause as the push-gate finding sent to
# skippy the same day — a Windows path/identifier becoming a filename with the drive-or-stream
# colon still in it — in a second, unrelated subsystem, which is why it is worth fixing at the
# naming layer rather than per-site.
#
# strict=True on purpose: the day the tag-to-filename encoding is fixed these XPASS, and an XPASS
# under strict is a FAILURE that says so. That is the known_gaps table's self-announcing property,
# and the alternative — a skip — would let the fix land silently and leave the marker lying.
_colon_tag_on_ntfs = pytest.mark.xfail(
    sys.platform == "win32",
    strict=True,
    reason="tag contains ':' -> on NTFS the cursor file becomes an alternate data stream, so the "
           "glob finds nothing. Product defect, reported to skippy 2026-08-30.",
)


def test_unread_mail_addressed_to_you_is_the_trigger(tmp_path):
    b = bus(tmp_path, ("2026-08-01 09:00:00", "to:behind"), "2026-08-24 13:00:00")
    d = cursors(tmp_path, behind="2026-07-28 13:21:42")
    r = stale_cursors(b, d, now=NOW, stale_h=24.0)[0]
    assert r["stale"] is True
    assert r["directed_unread"] == 1 and r["senders"] == ["sender"]


def test_a_cursor_days_behind_with_NO_mail_for_it_is_silent(tmp_path):
    """⭐ The whole design. Measured on the real fleet, raw cursor age fired on 36 of 36 cursors
    and 17 of 17 live members — a lagging cursor is the NORMAL state of a session nobody is
    talking to. Alarming on that teaches people to swipe the alarm away."""
    b = bus(tmp_path, "2026-08-01 09:00:00", "2026-08-24 13:00:00")   # broadcasts only
    d = cursors(tmp_path, quiet="2026-06-14 18:21")                   # ten weeks behind
    r = stale_cursors(b, d, now=NOW, stale_h=24.0)[0]
    assert r["behind"] > 60 * 24 * HOUR
    assert r["stale"] is False, "a quiet mailbox is not a broken reader"


def test_freshly_arrived_mail_is_not_an_alarm(tmp_path):
    """A session that simply has not got to this turn's mail yet is healthy."""
    b = bus(tmp_path, (_recent(1.0), "to:busy"))
    d = cursors(tmp_path, busy=_recent(2.0))
    assert stale_cursors(b, d, now=NOW, stale_h=24.0)[0]["stale"] is False


def test_a_mass_cc_is_not_a_debt(tmp_path):
    """Being cc'd is not being asked — the same rule the wait-graph uses, and the reason
    orb_slam got woken for six hours by traffic it was merely copied on."""
    many = " ".join(f"to:t{i}" for i in range(9))
    b = bus(tmp_path, ("2026-08-01 09:00:00", many), "2026-08-24 13:00:00")
    d = cursors(tmp_path, t0="2026-07-01 00:00:00")
    assert stale_cursors(b, d, now=NOW, stale_h=24.0)[0]["stale"] is False


@_colon_tag_on_ntfs
def test_your_own_message_is_not_unread_mail(tmp_path):
    b = bus(tmp_path, ("2026-08-01 09:00:00", "to:other:sender"), "2026-08-24 13:00:00")
    d = cursors(tmp_path, other__sender="2026-07-01 00:00:00")
    assert stale_cursors(b, d, now=NOW, stale_h=24.0)[0]["stale"] is False


def test_worst_first(tmp_path):
    b = bus(tmp_path, ("2026-08-20 09:00:00", "to:newer"), ("2026-08-02 09:00:00", "to:older"),
            "2026-08-24 13:00:00")
    d = cursors(tmp_path, newer="2026-08-19 00:00:00", older="2026-08-01 00:00:00")
    assert [r["tag"] for r in stale_cursors(b, d, now=NOW)][:2] == ["older", "newer"]


@_colon_tag_on_ntfs
def test_a_cursor_far_behind_the_tail_is_flagged(tmp_path):
    b = bus(tmp_path, "2026-08-24 13:00:00")
    d = cursors(tmp_path, other__behind="2026-07-28 13:21:42")
    rows = stale_cursors(b, d, now=NOW, stale_h=6.0)
    assert len(rows) == 1 and rows[0]["tag"] == "other:behind"
    assert rows[0]["behind"] > 20 * 24 * HOUR, "the age is still reported, it is just not the trigger"


@_colon_tag_on_ntfs
def test_a_current_cursor_is_not_flagged(tmp_path):
    b = bus(tmp_path, ("2026-08-24 13:00:00", "to:other:fresh"))
    d = cursors(tmp_path, other__fresh="2026-08-24 12:59:00")
    assert stale_cursors(b, d, now=NOW)[0]["stale"] is False


def test_both_timestamp_dialects_parse(tmp_path):
    """The bus carries HH:MM and HH:MM:SS. A cursor written before the seconds era is old,
    not malformed — reading it as malformed would silently drop the reader from the alarm."""
    b = bus(tmp_path, "2026-08-24 13:00:00")
    d = cursors(tmp_path, minute="2026-08-24 12:58", second="2026-08-24 12:58:30")
    rows = {r["tag"]: r for r in stale_cursors(b, d, now=NOW)}
    assert set(rows) == {"minute", "second"}
    assert all(r["stale"] is False for r in rows.values())
    assert rows["second"]["cursor_ep"] > rows["minute"]["cursor_ep"]





def _recent(hours_ago: float) -> str:
    import time as _t
    return _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(NOW - hours_ago * HOUR))


def test_a_cursor_ahead_of_the_tail_never_reads_as_behind(tmp_path):
    """A hand-repaired cursor can legitimately sit past the newest message. Negative age must
    not wrap into a huge positive one."""
    b = bus(tmp_path, "2026-08-24 13:00:00")
    d = cursors(tmp_path, repaired="2026-08-25 09:00:00")
    r = stale_cursors(b, d, now=NOW)[0]
    assert r["behind"] == 0.0 and r["stale"] is False


def test_an_empty_bus_cannot_make_anyone_look_behind(tmp_path):
    """The control that matters most. If the log is missing or unparseable the tail is unknown,
    and an unknown tail must produce NO alarm rather than flagging the entire fleet."""
    (tmp_path / "messages.md").write_text("", encoding="utf-8")
    d = cursors(tmp_path, someone="2026-06-01 00:00:00")
    assert stale_cursors(tmp_path / "messages.md", d, now=NOW) == []
    assert stale_cursors(tmp_path / "nope.md", d, now=NOW) == []


def test_junk_in_the_state_dir_is_skipped_not_crashed_on(tmp_path):
    b = bus(tmp_path, "2026-08-24 13:00:00")
    d = cursors(tmp_path, good="2026-08-01 00:00:00")
    (d / "bad.last-seen").write_text("not a timestamp\n", encoding="utf-8")
    (d / "empty.last-seen").write_text("", encoding="utf-8")
    (d / "other.pending").write_text("7\n", encoding="utf-8")
    (d / "other.delivered").write_text("2026-08-01 00:00:00\tmark\n", encoding="utf-8")
    tags = {r["tag"] for r in stale_cursors(b, d, now=NOW)}
    assert tags == {"good"}, f"only real cursor files should be read, got {tags}"


@pytest.mark.parametrize("hours,expect", [(1.0, True), (999.0, False)])
def test_the_threshold_is_the_knob(tmp_path, hours, expect):
    b = bus(tmp_path, ("2026-08-01 09:00:00", "to:t"), "2026-08-24 13:00:00")
    d = cursors(tmp_path, t="2026-07-01 00:00:00")
    assert stale_cursors(b, d, now=NOW, stale_h=hours)[0]["stale"] is expect


# =======================================================================================
# The signal has to REACH a surface. A fleet-health alarm that is computed and never
# rendered is the silent no-op this whole family of bugs is made of, so these pin the
# wiring: the field is on the payload the desktop reads, on the phone's aggregate, seeded
# on websocket connect, and referenced by both frontends.
# =======================================================================================

def test_the_signal_is_wired_all_the_way_to_both_surfaces():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    main = (root / "conductor" / "main.py").read_text(encoding="utf-8")
    # broadcast on change, seeded on connect, and present in the phone aggregate
    assert 'broadcast("stale_cursors"' in main
    assert '"kind": "stale_cursors"' in main, "a client connecting mid-session would never see it"
    assert main.count('"stale_cursors": self._stale_cursors') >= 1
    assert '"stale_cursors": state._stale_cursors' in main

    app = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'case "stale_cursors":' in app, "the desktop would drop the live update"
    assert "state.stale_cursors = payload.stale_cursors" in app, "and the initial payload too"
    assert "alert-stale" in app

    ops = (root / "frontend" / "m" / "ops.js").read_text(encoding="utf-8")
    assert "ops.stale_cursors" in ops, "the phone would never show it"

    css = (root / "frontend" / "style.css").read_text(encoding="utf-8")
    # ⚠️ v2.40 shipped a rule whose only colour came from an UNDEFINED var, which yields no
    # colour and no error. Every colour here must carry a literal fallback.
    import re
    for m in re.finditer(r"\.alert-stale[^{]*\{([^}]*)\}", css):
        for var in re.finditer(r"var\(\s*(--[\w-]+)\s*(,)?", m.group(1)):
            assert var.group(2), f"{var.group(1)} is used with no fallback — it will render as nothing"

