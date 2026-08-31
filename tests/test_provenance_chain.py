"""Tamper-EVIDENCE for the injection ledger, and an honest account of what it buys.

Kyle asked whether the ledger can itself be spoofed, and whether it wants encryption. It can,
and it does not.

⭐ THE ATTACK IS OMISSION, NOT FORGERY. An entry asserts "Conductor typed this, Kyle did not",
so forging one merely makes a session distrust a real human prompt — annoying, not dangerous.
The attack that gains something is the reverse: an injector that never attests at all. It does
not need to defeat this file; it needs only to type with xdotool and skip the choke point. A
ledger cannot bind what never passes through it.

Which is why signing would be theatre. A signature proves AUTHORSHIP OF A LINE; the property
under attack is COMPLETENESS OF THE LOG. And every session on this host runs as the same user,
so any key Conductor could sign with is one every session can read and sign with too.

So: a keyless chain that makes deletion and reordering DETECTABLE, plus a reader that treats an
unattested injectable prompt as "unknown" rather than "Kyle" — which is the change that makes
omission worthless. Neither prevents tampering. Both prevent SILENT tampering, and that is the
whole of what is claimed.
"""

from __future__ import annotations

import json

from conductor.provenance import attest, ledger_path, verify_chain


def _seed(d, n=3):
    for i in range(n):
        attest(d, target_pid=1000 + i, target_tag=f"[other:s{i}]",
               text="/msg-check", why=f"reason {i}", source="conductor:_inject_text")


def test_an_untouched_ledger_verifies(tmp_path):
    _seed(tmp_path)
    r = verify_chain(tmp_path)
    assert r["ok"] is True and r["entries"] == 3


def test_a_deleted_entry_is_detected(tmp_path):
    """The attack that matters, if the attacker bothers with this file at all."""
    _seed(tmp_path)
    lines = ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()
    ledger_path(tmp_path).write_text("\n".join([lines[0], lines[2]]) + "\n")
    r = verify_chain(tmp_path)
    assert r["ok"] is False and r["first_bad"] == 2


def test_an_altered_entry_is_detected(tmp_path):
    """Rewriting a reason to make an injection look like something else."""
    _seed(tmp_path)
    lines = [json.loads(x) for x in ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()]
    lines[1]["why"] = "kyle asked for this"
    ledger_path(tmp_path).write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    assert verify_chain(tmp_path)["ok"] is False


def test_reordering_is_detected(tmp_path):
    _seed(tmp_path)
    lines = ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()
    ledger_path(tmp_path).write_text("\n".join([lines[0], lines[2], lines[1]]) + "\n")
    assert verify_chain(tmp_path)["ok"] is False


def test_consuming_an_entry_is_not_tampering(tmp_path):
    """The reader marks entries consumed. That is a legitimate later mutation, so the digest
    must exclude it — otherwise every normal read would look like an attack, and an alarm that
    fires on correct behaviour is one you switch off."""
    _seed(tmp_path)
    rows = [json.loads(x) for x in ledger_path(tmp_path).read_text(encoding="utf-8").splitlines()]
    rows[1]["consumed"] = True
    ledger_path(tmp_path).write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    assert verify_chain(tmp_path)["ok"] is True


def test_pre_chain_history_is_not_condemned(tmp_path):
    """The live ledger has 38 entries written before the chain existed. A mechanism added later
    must not report the history that predates it as tampering — that would be a false alarm on
    day one, which is how a real alarm gets ignored."""
    p = ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ts": 1, "target_tag": "[old]", "text": "/msg-check",
                             "why": "before the chain", "source": "s", "actor": "conductor",
                             "consumed": False}) + "\n")
    attest(tmp_path, target_pid=7, target_tag="[new]", text="/msg-check", why="after",
           source="conductor:_inject_text")
    r = verify_chain(tmp_path)
    assert r["ok"] is True and r["entries"] == 2


def test_a_missing_ledger_is_not_an_alarm(tmp_path):
    r = verify_chain(tmp_path / "nope")
    assert r["ok"] is True and r["entries"] == 0
