"""The attestation ledger — "was Kyle at the keyboard, or did Conductor type that?"

Kyle: "I didn't type that /msg-check." He was right. Conductor typed it, and it arrived in the
session's transcript AS A USER TURN — indistinguishable from him. The receiving Claude then
answered him as though he had asked.

You cannot authenticate a sender from inside the channel the sender controls, so a self-applied
marker is worthless (the marker would be typed by the very thing you are distinguishing). Hence
a ledger, written BEFORE the keystrokes, joined on PID.

TWO THINGS IT IS NOT:
  * ATTESTATION, not AUTHENTICATION. Conductor self-declares; the threat model is AMBIGUITY,
    not an adversary.
  * ADVISORY, never AUTHORITY. It may change what a Claude SAYS. It may never change what a
    Claude is PERMITTED to do — "a provenance label that confers authority is just the
    I-accept-the-risk checkbox with better branding."
"""

from __future__ import annotations

import json
import time

from conductor.provenance import STALE_AFTER_S, attest, ledger_path, prune, read_ledger


def test_an_injection_is_recorded_before_it_happens(tmp_path):
    attest(tmp_path, target_pid=1234, target_tag="[other:qualcomm]", text="/msg-check",
           why="1 unread addressed to it", source="conductor:_inject_text")
    e = read_ledger(tmp_path)[0]
    assert e["target_pid"] == 1234
    assert e["text"] == "/msg-check"
    assert e["actor"] == "conductor"          # NOT Kyle


def test_the_CONSENT_channel_records_who_drove_it(tmp_path):
    """The one image_gen's own spec missed, and the one that matters.

    /msg-check is a read-only nudge. ANSWERING AN AskUserQuestion PICKER is how "yes, install
    it" reaches a Claude. A ledger that attests the nudge and not the consent channel is
    theatre — it watches the door nobody breaks in through.
    """
    attest(tmp_path, target_pid=99, target_tag="[other:image_gen]",
           text="[picker] [['Both (Recommended)']]", why="answered via 100.74.130.60",
           source="conductor:answer_decision", actor="human:100.74.130.60")
    e = read_ledger(tmp_path)[0]
    assert e["source"] == "conductor:answer_decision"
    assert e["actor"].startswith("human:")     # a VERIFIED join, not an assumption


def test_the_ledger_is_NUL_free_and_greppable(tmp_path):
    """The bug that produced a false statement about Kyle's consent.

    conductor.log had 2,426 NUL bytes, so grep classified it as BINARY and searched NOTHING —
    returning EMPTY, not an error. image_gen read that silence as "Conductor didn't wake me"
    and told Kyle the /msg-check was probably his. It wasn't.

    An audit log a text tool cannot parse is a green light with nothing behind it.
    """
    attest(tmp_path, target_pid=1, target_tag="[x]",
           text="hello\x00world\x07\x1b[31m", why="ctl\x00bytes",
           source="conductor:_inject_text")
    raw = ledger_path(tmp_path).read_bytes()
    assert b"\x00" not in raw
    assert b"\x07" not in raw
    # ...and it is still one valid JSON object per line
    for line in raw.decode().splitlines():
        json.loads(line)


def test_a_stale_entry_cannot_attach_itself_to_an_unrelated_prompt(tmp_path):
    """Keystrokes can go into the void (they have). An unconsumed entry that lingered would
    later claim an innocent prompt was injected — asserting a fact not in evidence, in the
    tool built to prevent exactly that."""
    ledger_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    old = {"ts": time.time() - STALE_AFTER_S - 1, "target_pid": 1, "text": "/msg-check",
           "consumed": False}
    ledger_path(tmp_path).write_text(json.dumps(old) + "\n")
    assert read_ledger(tmp_path) == []


def test_garbage_lines_are_skipped_never_fatal(tmp_path):
    ledger_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    ledger_path(tmp_path).write_text('{"broken\nnot json at all\n')
    assert read_ledger(tmp_path) == []


def test_prune_keeps_only_the_live_ones(tmp_path):
    attest(tmp_path, target_pid=1, target_tag="[a]", text="x", why="", source="s")
    ledger_path(tmp_path).open("a").write(
        json.dumps({"ts": time.time(), "consumed": True, "text": "done"}) + "\n")
    assert prune(tmp_path) == 1
    assert len(read_ledger(tmp_path)) == 1


def test_a_write_failure_never_stops_a_wake(tmp_path):
    """An attestation failure must not break delivery — but it is LOGGED, because a silent one
    would leave a keystroke with no provenance and nothing would say so."""
    bad = tmp_path / "nope"
    bad.write_text("i am a file, not a directory")
    attest(bad, target_pid=1, target_tag="[a]", text="x", why="", source="s")   # must not raise
