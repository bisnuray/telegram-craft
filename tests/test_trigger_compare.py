"""Tests for the sequential trigger runner, using a fake `claude` binary."""
import importlib.util
import json
import stat
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("trigger_compare", ROOT / "evals/trigger_compare.py")
tc = importlib.util.module_from_spec(spec)
sys.modules["trigger_compare"] = tc
spec.loader.exec_module(tc)

NAME = tc.SKILL_NAME
INIT = json.dumps({"type": "system", "subtype": "init", "session_id": "s", "skills": ["other", NAME]})
RESULT = json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "result": "ok"})


def use(name, **data):
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": data}]}})


def fold(*lines):
    seen = {"tools": []}
    for line in lines:
        tc.parse_event(line, seen)
    return tc.classify(seen)[0]


def test_activation_needs_init_and_tool_use():
    assert fold(INIT, use("Skill", skill=NAME)) == "activated"
    assert fold(use("Skill", skill=NAME)) == "invalid"


def test_plugin_prefixed_and_read_count_as_activation():
    assert fold(INIT, use("Skill", skill=f"x:{NAME}")) == "activated"
    assert fold(INIT, use("Read", file_path=f"/w/.claude/skills/{NAME}/SKILL.md")) == "activated"


def test_other_skill_is_a_valid_non_activation():
    assert fold(INIT, use("Skill", skill="superpowers:brainstorming"), RESULT) == "not_activated"


def test_similar_names_do_not_count():
    assert fold(INIT, use("Skill", skill=NAME + "-old"), RESULT) == "not_activated"


def test_missing_terminal_result_is_invalid():
    assert fold(INIT) == "invalid"


def test_skill_not_listed_is_invalid():
    no_skill = json.dumps({"type": "system", "subtype": "init", "skills": ["other"]})
    assert fold(no_skill, RESULT) == "invalid"


def test_duplicate_listing_is_invalid():
    twice = json.dumps({"type": "system", "subtype": "init", "skills": [NAME, NAME]})
    assert fold(twice, RESULT) == "invalid"


def test_api_error_is_invalid_not_a_miss():
    bad = json.dumps({"type": "result", "subtype": "success", "is_error": True, "num_turns": 0, "result": "API Error: 529 overloaded"})
    assert fold(INIT, bad) == "invalid"


def test_max_turns_without_activation_is_valid():
    capped = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 3, "result": ""})
    assert fold(INIT, capped) == "not_activated"


def test_prompts_naming_the_skill_are_refused(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps([{"query": f"use {NAME} please", "should_trigger": True}]))
    with pytest.raises(SystemExit):
        tc.load_cases([str(path)])


def test_plan_balances_variants():
    cases = [{"id": str(i)} for i in range(6)]
    trials = tc.plan_trials(cases, 2, 1)
    assert len(trials) == 24
    assert sum(t["variant"] == "v1" for t in trials[::2]) == 6


def test_description_override_leaves_the_source_untouched(tmp_path):
    source = ROOT / NAME / "SKILL.md"
    before = source.read_bytes()
    original = tc.read_description(ROOT / NAME)
    assert 'can\'t parse entities' in original and '\\"' not in original
    tc.prepare_variant(ROOT / NAME, 'New "quoted" text', tmp_path)
    copied = (tmp_path / ".claude/skills" / NAME / "SKILL.md").read_text()
    assert 'description: "New \\"quoted\\" text"' in copied
    assert source.read_bytes() == before


FAKE = """#!/usr/bin/env python3
import json, os, subprocess, sys, time
prompt = sys.argv[2]
open(os.environ["FAKE_LOG"], "a").write(f"{os.getpid()} {time.time()} start\\n")
def out(o):
    print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "session_id": "s", "skills": ["telegram-craft"]})
if "hang" in prompt:
    subprocess.Popen(["sleep", "300"])
    time.sleep(300)
if "noinit" in prompt:
    pass
if "yes" in prompt:
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "telegram-craft"}}]}})
    subprocess.Popen(["sleep", "300"])
    time.sleep(300)
out({"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "result": "plain"})
open(os.environ["FAKE_LOG"], "a").write(f"{os.getpid()} {time.time()} end\\n")
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log"
    log.write_text("")
    monkeypatch.setenv("FAKE_LOG", str(log))
    prompts = tmp_path / "p.json"
    prompts.write_text(json.dumps([
        {"query": "yes build", "should_trigger": True},
        {"query": "plain thing", "should_trigger": False},
    ]))
    base = ["--claude-bin", str(fake), "--sets", str(prompts), "--work", str(tmp_path / "w"), "--state", str(tmp_path / "state.jsonl"),
            "--raw", str(tmp_path / "raw"), "--repeats", "1", "--min-start", "1", "--min-during", "1"]
    return tmp_path, base, log, prompts


def test_runs_sequentially_records_evidence_and_leaves_no_children(env):
    tmp_path, base, log, _ = env
    assert tc.main(base + ["--timeout", "20"]) == 0
    records = tc.read_state(tmp_path / "state.jsonl")
    assert len(records) == 4
    assert {r["outcome"] for r in records} == {"activated", "not_activated"}
    assert all(not r["survivors"] for r in records)
    assert all(r["outcome"] == ("activated" if r["should_trigger"] else "not_activated") for r in records)
    assert list((tmp_path / "raw").glob("*.gz"))


def test_resume_skips_completed_trials(env):
    tmp_path, base, log, _ = env
    assert tc.main(base + ["--limit", "2", "--timeout", "20"]) == 0
    first = len(log.read_text().splitlines())
    assert tc.main(base + ["--timeout", "20"]) == 0
    records = tc.read_state(tmp_path / "state.jsonl")
    assert len(records) == 4 and len({r["trial"] for r in records}) == 4
    assert first > 0


def test_timeout_is_invalid_and_kills_the_group(env):
    tmp_path, base, log, prompts = env
    prompts.write_text(json.dumps([{"query": "hang here", "should_trigger": True}]))
    started = time.time()
    code = tc.main(base + ["--timeout", "2"])
    assert time.time() - started < 45
    records = tc.read_state(tmp_path / "state.jsonl")
    assert records and all(r["outcome"] == "invalid" and "timeout" in r["reason"] and not r["survivors"] for r in records)
    assert code in (0, 12)


def test_low_memory_stops_without_starting(env, monkeypatch):
    tmp_path, base, log, _ = env
    monkeypatch.setattr(tc, "LOW_MEMORY_WAIT_SECONDS", 0)
    args = [a for a in base]
    args[args.index("--min-start") + 1] = "99999999"
    assert tc.main(args) == 11
    assert log.read_text() == ""
    assert tc.read_state(tmp_path / "state.jsonl") == []


def test_memory_floor_aborts_and_stops(env):
    tmp_path, base, log, _ = env
    args = [a for a in base]
    args[args.index("--min-during") + 1] = "99999999"
    assert tc.main(args + ["--timeout", "20"]) == 11
    records = tc.read_state(tmp_path / "state.jsonl")
    assert len(records) == 1 and records[0]["outcome"] == "invalid" and "memory abort" in records[0]["reason"]


def test_torn_state_line_is_tolerated(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text('{"trial": "a", "outcome": "activated"}\n{"trial": "b", "outc')
    assert len(tc.read_state(path)) == 1
