"""Tests for the JSONL bus adapter."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from conductor.bus import JSONLBusAdapter, _coerce_event
from conductor.models import BusEvent


def test_coerce_event_basic():
    obj = {
        "timestamp": 1000.0,
        "source": "s1",
        "destination": "s2",
        "topic": "x",
        "payload": "hello",
    }
    ev = _coerce_event(obj)
    assert isinstance(ev, BusEvent)
    assert ev.source_session == "s1"
    assert ev.destination_session == "s2"
    assert ev.topic == "x"
    assert ev.payload_summary == "hello"


def test_coerce_event_dict_payload_stringified():
    ev = _coerce_event({"source": "s1", "topic": "t", "payload": {"k": "v" * 100}})
    assert ev is not None
    assert len(ev.payload_summary) <= 80


def test_coerce_event_missing_source_returns_none():
    assert _coerce_event({"topic": "t"}) is None


def test_coerce_event_default_destination_broadcast():
    ev = _coerce_event({"source": "s1", "topic": "t"})
    assert ev is not None
    assert ev.destination_session == "broadcast"


@pytest.mark.asyncio
async def test_jsonl_bus_adapter_picks_up_appended_lines(tmp_path: Path):
    log = tmp_path / "bus.jsonl"
    log.write_text("")  # exists, empty

    adapter = JSONLBusAdapter(log, poll_interval=0.05)
    await adapter.start()
    try:
        # Append after start so adapter picks it up incrementally.
        await asyncio.sleep(0.1)
        with log.open("a") as f:
            f.write(json.dumps({"source": "a", "destination": "b", "topic": "t", "payload": "hi"}) + "\n")
            f.write(json.dumps({"topology": {"a": ["t"], "b": ["t"]}}) + "\n")

        # Drain one event from the stream with a timeout.
        gen = adapter.stream_events()
        ev = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        assert ev.source_session == "a"
        assert ev.topic == "t"

        # Topology should have been merged from the topology-line.
        await asyncio.sleep(0.2)
        topo = adapter.get_topology()
        assert "a" in topo.subscribers and "b" in topo.subscribers
    finally:
        await adapter.stop()
