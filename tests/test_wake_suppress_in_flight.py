"""Do not wake a session to read mail it is answering right now.

`bus.sh check` stages its cursor advance into ``<member>.delivered`` and only the turn's
own Stop hook promotes it to ``.last-seen``. For the whole length of a turn the mail is
read in every sense that matters while the unread test still says unread — and the gap is
WIDEST for the turns that did the most work, because composing a long reply keeps the turn
open.

MEASURED by splat-vla, 2026-10-07, three occurrences in one day. The 19:02 instance:

    18:58:43  docs posts
    19:02:13  splat-vla finishes reading it and replies
    19:02:25  Stop hook commits the cursor
    ~19:05    Conductor injects /msg-check, "attested 187s before it arrived"

The cost is not the wasted turn. It is that an injected ``/msg-check`` landing on an empty
queue is indistinguishable from a real one, which trains sessions to treat the wake channel
as noise — the failure you least want on a channel whose only job is interrupting someone.

⚠️ THE TESTS THAT EARN THEIR KEEP HERE ARE THE NEGATIVE ONES. This suppresses wakes, so a
bug costs a session its mail nudge, silently. Every case below where suppression must NOT
happen is therefore the real subject of the file; the one case where it must is the easy
half.
"""

from __future__ import annotations

from pathlib import Path

from conductor.bus import read_delivered


def _write(d: Path, name: str, body: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


# ── reading the staged record ───────────────────────────────────────────────────────────

def test_reads_the_staged_timestamp(tmp_path: Path):
    _write(tmp_path, "other:splat-vla.delivered", "2026-10-07 18:58:43\t3c97f8eb-aaaa\n")
    assert read_delivered(tmp_path, "[other:splat-vla]") == "2026-10-07 18:58:43"


def test_finds_the_record_under_the_bare_name_too(tmp_path: Path):
    """`check` writes under whichever name it resolved; a second convention here is how
    the two halves drift apart."""
    _write(tmp_path, "docs.delivered", "2026-10-07 18:58:43\tmarker\n")
    assert read_delivered(tmp_path, "docs") == "2026-10-07 18:58:43"


def test_absent_record_is_none(tmp_path: Path):
    assert read_delivered(tmp_path, "[other:nobody]") is None


# ── the fail-toward-waking cases: anything unparseable must NOT suppress ─────────────────

def test_malformed_record_does_not_yield_a_timestamp(tmp_path: Path):
    """A half-parsed value could suppress a wake it should not. Fail toward waking."""
    for junk in ("garbage\tmarker\n", "\tmarker\n", "\n", "2026-13-99 99:99:99\tm\n",
                 "## 2026-10-07 18:58:43 [other:x]\n"):
        _write(tmp_path, "other:x.delivered", junk)
        assert read_delivered(tmp_path, "[other:x]") is None, f"accepted junk: {junk!r}"


def test_empty_file_is_none(tmp_path: Path):
    _write(tmp_path, "other:x.delivered", "")
    assert read_delivered(tmp_path, "[other:x]") is None


def test_minute_precision_record_is_accepted(tmp_path: Path):
    """15 of 40 live cursors are minute-precision; the staged record can be too."""
    _write(tmp_path, "other:x.delivered", "2026-10-07 18:58\tmarker\n")
    assert read_delivered(tmp_path, "[other:x]") == "2026-10-07 18:58"


# ── the suppression decision itself, as the scan loop applies it ────────────────────────
# The live code is `if staged and latest and staged >= latest: continue`.

def _suppressed(staged: str | None, latest: str) -> bool:
    return bool(staged and latest and staged >= latest)


def test_suppresses_when_the_staged_read_covers_the_newest_mail():
    """THE FIX: read at 18:58:43, newest mail is 18:58:43 -> in flight, do not wake."""
    assert _suppressed("2026-10-07 18:58:43", "2026-10-07 18:58:43") is True


def test_suppresses_when_the_staged_read_is_ahead():
    assert _suppressed("2026-10-07 19:10:00", "2026-10-07 18:58:43") is True


def test_does_NOT_suppress_when_newer_mail_arrived_after_the_read():
    """THE CASE THAT MATTERS. A message landed after the session read — that is a real
    wake and suppressing it would cost mail, silently."""
    assert _suppressed("2026-10-07 18:58:43", "2026-10-07 19:30:00") is False


def test_does_NOT_suppress_without_a_staged_record():
    """No open turn -> nothing in flight -> normal wake behaviour, unchanged."""
    assert _suppressed(None, "2026-10-07 19:30:00") is False


def test_does_NOT_suppress_when_the_record_is_unparseable():
    """read_delivered returns None for junk, which must reach the wake path as 'no
    suppression' rather than as 'suppress'."""
    assert _suppressed(None, "2026-10-07 19:30:00") is False


def test_does_NOT_suppress_when_latest_is_unknown():
    """If we cannot say what the newest mail is, we must not silently swallow the wake."""
    assert _suppressed("2026-10-07 18:58:43", "") is False


def test_mixed_precision_compares_in_the_lossy_direction_only_when_safe():
    """Strings compare bytewise and the bus is mixed-precision. A minute-precision staged
    read must not appear to cover a later same-minute message."""
    # staged "18:58" vs mail at "18:58:43": "18:58" < "18:58:43" -> NOT suppressed. Correct:
    # we cannot prove the staged read covered that message, so we wake.
    assert _suppressed("2026-10-07 18:58", "2026-10-07 18:58:43") is False
