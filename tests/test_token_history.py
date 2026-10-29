"""🪙 Token history — day × project spend from transcripts, each reply counted once, persisted."""
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from conductor.token_history import TokenHistory
from conductor.tokens import TokenAccountant


def rec(mid, out, ts="2026-10-12T15:00:00Z", cwd="/home/u/GitHub/alpha", cache_read=100):
    return json.dumps({"type": "assistant", "timestamp": ts, "cwd": cwd,
                       "message": {"id": mid, "role": "assistant",
                                   "usage": {"input_tokens": 1, "cache_creation_input_tokens": 0,
                                             "cache_read_input_tokens": cache_read,
                                             "output_tokens": out}}})


def user_line():
    return json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})


def write(p: Path, lines, mode="w"):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, mode, encoding="utf-8") as fh:
        for ln in lines:
            fh.write(ln + "\n")


# --- the double count (the reason this module exists) ----------------------------------------

def test_one_reply_written_as_several_lines_counts_once(tmp_path):
    """Claude Code writes each content block as its own line and repeats the reply's usage on
    every one. MEASURED 2026-10-29: summing lines counted 539K output for 225K real."""
    t = tmp_path / "p" / "s.jsonl"
    write(t, [user_line(), rec("m1", 50), rec("m1", 50), rec("m1", 50), rec("m2", 7)])
    h = TokenHistory(tmp_path / "p"); h.scan()
    a = h.snapshot()["all_time"]
    assert a == {"output": 57, "total": 57 + 2 * 101, "replies": 2}


def test_the_live_tile_counter_dedupes_too(tmp_path):
    t = tmp_path / "s.jsonl"
    write(t, [rec("m1", 50), rec("m1", 50), rec("m2", 7)])
    u = TokenAccountant().usage_for(str(t))
    assert (u["output"], u["turns"]) == (57, 2)


def test_a_later_line_with_bigger_numbers_adds_only_the_difference(tmp_path):
    t = tmp_path / "p" / "s.jsonl"
    write(t, [rec("m1", 10), rec("m1", 30)])
    h = TokenHistory(tmp_path / "p"); h.scan()
    assert h.snapshot()["all_time"]["output"] == 30
    assert h.snapshot()["all_time"]["replies"] == 1


def test_a_reply_split_across_two_scans_is_still_counted_once(tmp_path):
    t = tmp_path / "p" / "s.jsonl"
    write(t, [rec("m1", 40)])
    h = TokenHistory(tmp_path / "p"); h.scan()
    write(t, [rec("m1", 40), rec("m2", 5)], mode="a")
    h.scan()
    assert h.snapshot()["all_time"]["output"] == 45


# --- incremental + partial lines ---------------------------------------------------------------

def test_a_half_written_last_line_waits_for_its_newline(tmp_path):
    t = tmp_path / "p" / "s.jsonl"
    write(t, [rec("m1", 10)])
    with open(t, "a", encoding="utf-8") as fh:
        fh.write(rec("m2", 20)[:30])                      # no newline yet
    h = TokenHistory(tmp_path / "p"); h.scan()
    assert h.snapshot()["all_time"]["output"] == 10
    with open(t, "a", encoding="utf-8") as fh:
        fh.write(rec("m2", 20)[30:] + "\n")
    h.scan()
    assert h.snapshot()["all_time"]["output"] == 30


def test_incremental_equals_one_shot(tmp_path):
    a, b = tmp_path / "a" / "x" / "s.jsonl", tmp_path / "b" / "x" / "s.jsonl"
    lines = [rec(f"m{i}", i, ts=f"2026-10-{10 + i % 3:02d}T12:00:00Z") for i in range(1, 30)]
    write(a, lines)
    one = TokenHistory(tmp_path / "a"); one.scan()
    inc = TokenHistory(tmp_path / "b")
    for i in range(0, len(lines), 7):
        write(b, lines[i:i + 7], mode="a"); inc.scan()
    assert one.snapshot()["series"] == inc.snapshot()["series"]


# --- buckets ---------------------------------------------------------------------------------

def test_buckets_by_day_and_by_the_sessions_folder(tmp_path):
    write(tmp_path / "p" / "-x-alpha" / "s1.jsonl", [rec("a", 5, ts="2026-10-01T12:00:00Z")])
    write(tmp_path / "p" / "-x-beta" / "s2.jsonl",
          [rec("b", 9, ts="2026-10-02T12:00:00Z", cwd="/home/u/GitHub/beta")])
    h = TokenHistory(tmp_path / "p"); h.scan()
    s = h.snapshot()
    assert s["days"] == ["2026-10-01", "2026-10-02"]
    assert s["series"]["2026-10-01"]["alpha"][0] == 5
    assert s["series"]["2026-10-02"]["beta"][0] == 9
    assert [p["name"] for p in s["projects"]] == ["beta", "alpha"]    # largest first


def test_subagent_transcripts_count(tmp_path):
    write(tmp_path / "p" / "-x-alpha" / "s1" / "subagents" / "agent-1.jsonl", [rec("sa", 11)])
    h = TokenHistory(tmp_path / "p"); h.scan()
    assert h.snapshot()["all_time"]["output"] == 11


# --- persistence -----------------------------------------------------------------------------

def test_the_history_outlives_the_transcript(tmp_path):
    """Claude Code deletes old transcripts; the history must not forget them."""
    t = tmp_path / "p" / "-x-alpha" / "s.jsonl"
    cache = tmp_path / "coord" / "token-history.json"
    write(t, [rec("m1", 12)])
    TokenHistory(tmp_path / "p", cache).scan()
    t.unlink()
    h = TokenHistory(tmp_path / "p", cache); h.scan()
    assert h.snapshot()["all_time"]["output"] == 12


def test_a_restart_resumes_from_the_cache_without_recounting(tmp_path):
    t = tmp_path / "p" / "-x-alpha" / "s.jsonl"
    cache = tmp_path / "coord" / "token-history.json"
    write(t, [rec("m1", 12)])
    TokenHistory(tmp_path / "p", cache).scan()
    write(t, [rec("m1", 12), rec("m2", 3)], mode="a")    # m1 again across the restart
    h = TokenHistory(tmp_path / "p", cache); h.scan()
    assert h.snapshot()["all_time"]["output"] == 15


def test_a_replaced_file_is_recounted_not_added(tmp_path):
    t = tmp_path / "p" / "s.jsonl"
    write(t, [rec("m1", 12), rec("m2", 8)])
    h = TokenHistory(tmp_path / "p"); h.scan()
    t.unlink(); write(t, [rec("m9", 4)])
    h.scan()
    assert h.snapshot()["all_time"]["output"] == 4


def test_the_cache_holds_counts_not_content(tmp_path):
    t = tmp_path / "p" / "s.jsonl"
    secret = json.dumps({"type": "assistant", "timestamp": "2026-10-12T12:00:00Z",
                         "message": {"id": "m1", "content": [{"type": "text", "text": "SECRET-PROSE"}],
                                     "usage": {"output_tokens": 3}}})
    write(t, [secret])
    cache = tmp_path / "c.json"
    TokenHistory(tmp_path / "p", cache).scan()
    assert "SECRET-PROSE" not in cache.read_text()


def test_a_corrupt_cache_is_a_rescan_not_a_crash(tmp_path):
    cache = tmp_path / "c.json"; cache.write_text("{nope")
    write(tmp_path / "p" / "s.jsonl", [rec("m1", 2)])
    h = TokenHistory(tmp_path / "p", cache); h.scan()
    assert h.snapshot()["all_time"]["output"] == 2


def test_not_ready_until_the_first_scan(tmp_path):
    h = TokenHistory(tmp_path / "p")
    assert h.snapshot()["ready"] is False
    h.scan()
    assert h.snapshot()["ready"] is True


# --- the endpoint ----------------------------------------------------------------------------

def test_endpoint_serves_the_snapshot(tmp_path, monkeypatch):
    from conductor import main
    from conductor.settings import load_settings
    settings = load_settings(); settings.server.auth_token = ""
    monkeypatch.delenv("CONDUCTOR_AUTH_TOKEN", raising=False)
    write(tmp_path / "p" / "-x-alpha" / "s.jsonl", [rec("m1", 6)])
    th = TokenHistory(tmp_path / "p"); th.scan()
    main.app.state.cond = SimpleNamespace(token_history=th, settings=settings)
    r = TestClient(main.app).get("/api/tokens/history")
    assert r.status_code == 200
    j = r.json()
    assert j["ready"] and j["all_time"]["output"] == 6 and j["projects"][0]["name"] == "alpha"
    s = TestClient(main.app).get("/api/tokens/history?summary=1").json()
    assert s["all_time"]["output"] == 6 and "series" not in s
