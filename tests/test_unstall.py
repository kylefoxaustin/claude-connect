"""Telling a stalled cycle that it is stalled.

Kyle's ask, and the shape of it is the interesting part:

    **A mutual stall is invisible to its participants BY CONSTRUCTION.**

Each side believes it is politely awaiting a reply — and each is *correct* about that. Both
are behaving well. Neither can see that the other believes exactly the same thing about
them, which is why neither speaks, which is why the silence continues. From the inside it
looks identical to a conversation in progress, so there is no moment at which either one
would think to check.

The only actor who can see the loop is the one standing outside it. That's the dashboard.
So the message must carry the fact they cannot derive: *you are both waiting on each other.*
"""

from __future__ import annotations

from conductor.main import _stall_message


def _edges():
    return [
        {"src": "a", "dst": "b", "why": "2 unread message(s) — awaiting a reply"},
        {"src": "b", "dst": "a", "why": "1 unread message(s) — awaiting a reply"},
    ]


def test_a_mutual_stall_tells_them_to_SPEAK_not_to_hurry():
    m = _stall_message(["a", "b"], deadlock=False, edges=_edges())
    assert "to:a to:b" in m                       # directed, so auto-delivery reaches them
    assert "MUTUAL STALL" in m
    assert "Either of you can end it right now by replying" in m
    # It must NOT tell them they're broken or blocked — they aren't, and a false alarm here
    # teaches them to discount the next one.
    assert "Nobody is blocked and nothing is broken" in m


def test_it_names_the_loop_and_every_edge():
    """The fact they cannot see. Without it this is just a nag."""
    m = _stall_message(["a", "b"], deadlock=False, edges=_edges())
    assert "a → b → a" in m
    assert "a is waiting on b" in m
    assert "b is waiting on a" in m


def test_it_licenses_the_cheapest_possible_answer():
    """A stalled Claude may have nothing to add — and if 'I have nothing further' doesn't feel
    like a legitimate reply, it will keep saying nothing, which is the stall."""
    m = _stall_message(["a", "b"], deadlock=False, edges=_edges())
    assert "I have nothing further" in m


def test_a_deadlock_gets_a_DIFFERENT_message():
    """Telling a resource deadlock to 'just reply' would be worse than useless — it's exactly
    the advice that keeps them stuck. Someone has to RELEASE."""
    m = _stall_message(["a", "b"], deadlock=True, edges=[
        {"src": "a", "dst": "b", "why": "waiting for orin-agx (held by b)"},
        {"src": "b", "dst": "a", "why": "waiting for iq9-evk (held by a)"},
    ])
    assert "DEADLOCK" in m
    assert "One of you has to release" in m
    assert "/release" in m
    assert "Either of you can end it right now by replying" not in m
    # And it must name the trap they're in: both politely waiting IS the deadlock.
    assert "Do not both wait for the other to go first" in m


def test_a_three_way_cycle_reads_correctly():
    m = _stall_message(["a", "b", "c"], deadlock=False, edges=[
        {"src": "a", "dst": "b", "why": "x"},
        {"src": "b", "dst": "c", "why": "y"},
        {"src": "c", "dst": "a", "why": "z"},
    ])
    assert "a → b → c → a" in m
    assert "to:a to:b to:c" in m
