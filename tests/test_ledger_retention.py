"""The provenance ledger deleted its own proof of delivery.

``prune()`` retained exactly what ``read_ledger()`` returns, and read_ledger EXCLUDES
consumed entries. prune runs on every scan tick (~3s), so:

    attest              -> 1 line, consumed=False
    the hook consumes it-> 1 line, consumed=True     (delivery is now PROVEN)
    one prune tick      -> 0 lines                   (the proof is DELETED)

⇒ ``consumed=False`` was the only state the file could ever show, and "was this injection
ever delivered?" was permanently unanswerable.

⚠️ THAT INVERTS THE SUBSYSTEM'S OWN STATED THREAT MODEL. provenance.py says the attack on a
ledger is OMISSION, not forgery — and the implementation made omission the routine designed
behaviour. It was a delivery queue wearing the word "ledger".

HOW IT WAS FOUND, which is the whole point: agentic-skills-imx tried to AUDIT it after a push
approval silently failed, saw 13 of 13 entries unconsumed, and **withdrew its own fleet-wide
alarm** because it could not find a single ``consumed=True`` anywhere to establish what the
field meant. Its reasoning was exactly right — *"the absence of a positive example was the
whole signal"* — and the reason no positive example existed is that prune deleted them all.

A record store discovered to be unauditable *by someone failing to audit it*.
"""

from __future__ import annotations

import json
import time

from conductor.provenance import (DELIVERED_RETAIN_S, STALE_AFTER_S, attest, delivered,
                                  ledger_path, prune, read_ledger)


def _attest(d, text="push approved: x", **kw):
    attest(d, target_tag=kw.get("tag", "other:x"), target_pid=1, source="conductor",
           text=text, why=kw.get("why", "push verdict"), actor=kw.get("actor", "human:1.2.3.4"))


def _consume(d, idx=0):
    """Do exactly what bus.sh:3225 does on arrival — including its tolerance of a torn line
    (it parks a None in the slot and writes back only the rows it could parse)."""
    rows = []
    for line in ledger_path(d).read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append(None)
    [r for r in rows if r is not None][idx]["consumed"] = True
    ledger_path(d).write_text("".join(json.dumps(r) + "\n" for r in rows if r is not None))


def _lines(d):
    try:
        return [l for l in ledger_path(d).read_text().splitlines() if l.strip()]
    except OSError:
        return []


def test_the_bug_proof_of_delivery_survives_a_prune_tick(tmp_path):
    _attest(tmp_path)
    _consume(tmp_path)
    prune(tmp_path)
    assert len(_lines(tmp_path)) == 1, "the evidence of delivery was deleted again"


def test_delivery_is_now_an_answerable_question(tmp_path):
    """The capability that did not exist: asking whether something was delivered."""
    _attest(tmp_path, actor="human:10.0.0.9")
    _consume(tmp_path)
    got = delivered(tmp_path)
    assert len(got) == 1
    assert got[0]["actor"] == "human:10.0.0.9"      # and WHO drove it
    assert got[0]["consumed"] is True


def test_consumed_entries_stay_OUT_of_matching(tmp_path):
    """Retention must not resurrect them as match candidates. If a delivered entry could be
    matched again it would attach itself to a later, unrelated prompt — the 4.9-hour
    mis-attribution bus.sh documents, reintroduced from the other end."""
    _attest(tmp_path)
    _consume(tmp_path)
    prune(tmp_path)
    assert read_ledger(tmp_path) == []


def test_an_outstanding_entry_is_still_kept(tmp_path):
    """The original purpose must survive the change."""
    _attest(tmp_path)
    prune(tmp_path)
    assert len(read_ledger(tmp_path)) == 1


def test_delivered_records_are_still_BOUNDED(tmp_path):
    """Retention without a horizon is a disk leak, and this repo has been bitten by
    unbounded-by-default once already (v2.39: 18.5 TB/day to count lines)."""
    _attest(tmp_path)
    _consume(tmp_path)
    prune(tmp_path, now=time.time() + DELIVERED_RETAIN_S + 60)
    assert _lines(tmp_path) == []


def test_the_audit_horizon_outlives_the_match_horizon(tmp_path):
    """If delivered evidence expired at STALE_AFTER_S it would still be gone before anyone
    could reasonably audit a morning's pushes."""
    assert DELIVERED_RETAIN_S > STALE_AFTER_S


def test_stale_UNCONSUMED_wreckage_is_still_reaped(tmp_path):
    """An old unconsumed entry must not linger and claim an unrelated prompt."""
    _attest(tmp_path)
    prune(tmp_path, now=time.time() + STALE_AFTER_S + 60)
    assert _lines(tmp_path) == []


def test_a_malformed_line_is_never_fatal(tmp_path):
    """The ledger is written by two independent processes; a torn line must not take the
    scan loop down, and must not silently eat the good records either."""
    _attest(tmp_path)
    with ledger_path(tmp_path).open("a") as fh:
        fh.write("{not json\n")
    _consume(tmp_path)
    prune(tmp_path)
    assert len(delivered(tmp_path)) == 1


def test_mixed_entries_are_each_handled_on_their_own_merits(tmp_path):
    """One delivered, one outstanding: both kept, for different reasons."""
    _attest(tmp_path, text="push approved: a")
    _attest(tmp_path, text="/msg-check")
    _consume(tmp_path, 0)
    prune(tmp_path)
    assert len(_lines(tmp_path)) == 2
    assert len(delivered(tmp_path)) == 1
    assert len(read_ledger(tmp_path)) == 1


def test_prune_is_idempotent(tmp_path):
    """It runs every ~3s forever; it must not churn the file or drift."""
    _attest(tmp_path)
    _consume(tmp_path)
    prune(tmp_path)
    first = ledger_path(tmp_path).read_text()
    for _ in range(5):
        prune(tmp_path)
    assert ledger_path(tmp_path).read_text() == first
