"""Push proposals — "should I push NOW?", which is not the question the gate asks.

Kyle spotted the conflation:

    THE GATE asks  "MAY you push?"            and protects the REPO.
    A CLAUDE asks  "should I push NOW, or keep digging into X?"  and protects the WORK.

**A gate approval cannot answer the second one.** Kyle's inbox showed him
`claude-connect — git push origin main`: nothing about what is in the commits, whether the
session thinks it's finished, or what it would do instead. Tapping Approve on that is a
rubber stamp on a decision he never made.

Which means a session that "just pushes and lets the gate sort it out" has quietly appointed
ITSELF the judge of whether the work was ready — the push-happy behaviour Kyle explicitly
does not want, and the one the gate does NOT protect him from.

So the session states its case, and Kyle answers one question with the information in front
of him. Choosing "push" ARMS the grant, so there is no second content-free tap. The gate is
untouched: still one push per grant, still consumed on use, still revocable.
"""

from __future__ import annotations

import time

from conductor.coord import clear_push_proposal, read_push_grants, read_push_proposals
from conductor.main import _mint_grant


def _write(tmp_path, key="repo_a", why="done and tested", alts=("keep digging",),
           commits=("abc v1: thing", "def v2: other")):
    d = tmp_path / "push-proposals"
    d.mkdir(parents=True, exist_ok=True)
    lines = [f"repo=/home/kyle/{key}", f"repo_name={key}", "cwd=/home/kyle/x", f"why={why}"]
    lines += [f"alt={a}" for a in alts]
    lines += [f"commits={'|'.join(commits)}", f"epoch={int(time.time())}",
              "created=2026-07-12 09:40"]
    (d / key).write_text("\n".join(lines) + "\n")
    return d / key


def test_a_proposal_carries_what_the_gate_never_could(tmp_path):
    _write(tmp_path)
    p = read_push_proposals(tmp_path)[0]
    assert p["why"] == "done and tested"          # the case for shipping NOW
    assert p["alts"] == ["keep digging"]          # what it would do instead
    assert len(p["commits"]) == 2                 # and what is actually in it


def test_multiple_alternatives_survive(tmp_path):
    """`alt=` repeats, so a flat one-value-per-key parser silently keeps only the last —
    and Kyle would be shown one option when the session offered three."""
    _write(tmp_path, alts=("read the bus", "clean the queue", "run the benchmark"))
    assert len(read_push_proposals(tmp_path)[0]["alts"]) == 3


def test_a_proposal_with_no_why_is_not_a_proposal(tmp_path):
    d = tmp_path / "push-proposals"
    d.mkdir()
    (d / "x").write_text("repo_name=x\nalt=something\n")
    assert read_push_proposals(tmp_path) == []


def test_approving_a_proposal_ARMS_the_grant(tmp_path):
    """THE POINT. Kyle answers the real question once, and the push is authorised by that same
    tap — instead of being asked a second, content-free question ten minutes later."""
    _mint_grant(tmp_path, "repo_a", "claude-connect", "/home/kyle/claude-connect")
    g = read_push_grants(tmp_path)
    assert len(g) == 1
    assert g[0]["repo_name"] == "claude-connect"
    assert g[0]["expires_in"] > 80000                  # durable, like every other grant


def test_the_minted_grant_is_readable_by_the_GATE(tmp_path):
    """It must be byte-compatible with what push-gate.sh parses, or Kyle's tap arms a token
    the gate ignores — and the push is denied after he already said yes."""
    _mint_grant(tmp_path, "repo_a", "cc", "/repo")
    txt = (tmp_path / "push-tokens" / "repo_a").read_text()
    assert txt.startswith("expires=")
    exp = int(txt.split("\n")[0].split("=")[1])
    assert exp > time.time()
    assert "repo_name=cc" in txt


def test_answering_clears_the_proposal(tmp_path):
    _write(tmp_path)
    clear_push_proposal(tmp_path, "repo_a")
    assert read_push_proposals(tmp_path) == []
    clear_push_proposal(tmp_path, "repo_a")           # idempotent


def test_no_proposals_dir_is_quiet(tmp_path):
    assert read_push_proposals(tmp_path) == []
