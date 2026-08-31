"""The header and the inbox must never disagree, and a card must not name the wrong reason.

Kyle's phone showed this for days:

    ● Conductor    nothing needs you    1 stuck  1 working  16 idle
    NEEDS YOU
      📋 ieee-paper
         lead seat is empty — re-nominate

Two independent bugs in one card, and each is worse than a missing feature:

1. THE CARD NAMED A REASON THAT WAS NOT TRUE. ieee-paper's state was `active`, its lead was
   `claude-connect`, and its `needs` was **stalled** — three orders nobody had claimed in 29
   days. `projectInfoRow` had a two-branch chain whose FALLBACK asserted a fact, so every
   `needs` value that was not `awaiting-nominee` rendered as "lead seat is empty". A card that
   names the wrong reason sends you to fix something that was never broken and hides the thing
   that is.

2. THE SUMMARY CONTRADICTED THE LIST. `needs_you` counted only `approve-plan`, while the inbox
   rendered a card for ANY project with a `needs`. A green "nothing needs you" sitting directly
   above a card resolves the wrong way — the header is the stronger signal, so the card becomes
   furniture you stop seeing. Which is exactly what happened: it sat there "a while".
"""

from __future__ import annotations

import re
from pathlib import Path

from conductor.projects import _needs_operator, projects_needing_operator

ROOT = Path(__file__).resolve().parent.parent


def test_a_stalled_project_is_not_reported_as_a_missing_lead():
    """The real ieee-paper shape: active, led, and stalled."""
    p = {"state": "active", "lead": "claude-connect",
         "nominations": [{"session": "claude-connect", "response": "accepted"}],
         "stalls": [{"id": "ablation-93", "stall": "never-claimed", "order_age_hours": 701.6}]}
    assert _needs_operator(p) == "stalled"


def test_the_missing_lead_case_still_reports_itself():
    """The control — otherwise "not renominate" is satisfied by never saying renominate."""
    p = {"state": "draft", "lead": None,
         "nominations": [{"session": "a", "response": "declined"}]}
    assert _needs_operator(p) == "renominate"


def test_the_inbox_counter_counts_exactly_what_the_inbox_renders():
    """Both sides read from projects_needing_operator, so they cannot drift apart."""
    main = (ROOT / "conductor" / "main.py").read_text(encoding="utf-8")
    m = re.search(r'"needs_you":\s*\((.*?)\),\n', main, re.S)
    assert m, "the needs_you counter moved — re-point this test"
    body = m.group(1)
    assert "projects_needing_operator(state.projects)" in body, \
        "the header counts a different set than the inbox renders — the green summary will lie"
    assert 'p.get("needs") == "approve-plan"' not in body, \
        "still counting only the plan gate; a stalled project renders a card and is not counted"


def test_every_needs_value_has_its_own_line_on_the_phone():
    """No fallback may assert a fact. An unknown `needs` must say it is unknown rather than
    borrowing the nearest sentence — which is how a stalled project claimed to have no lead."""
    ops = (ROOT / "frontend" / "m" / "ops.js").read_text(encoding="utf-8")
    m = re.search(r"function projectInfoRow\(p\) \{(.*?)\n\}", ops, re.S)
    assert m, "projectInfoRow moved — re-point this test"
    body = m.group(1)
    for needs in ("awaiting-nominee", "renominate", "stalled"):
        assert f'"{needs}"' in body, f"{needs} has no branch — it would fall through to another's text"
    assert "unspecified" in body, "no honest default for a needs value this UI does not know"


def test_the_selector_is_the_single_definition():
    projects = [{"needs": "stalled"}, {"needs": None}, {"needs": "approve-plan"}, {}]
    assert len(projects_needing_operator(projects)) == 2
