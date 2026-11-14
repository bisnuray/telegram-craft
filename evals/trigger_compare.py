#!/usr/bin/env python3
"""Compare two skill descriptions by automatic activation, one process at a time.

Each trial runs `claude -p <prompt>` in an isolated project containing a copy of
the skill. Prompts never name the skill, so activation is automatic. Nothing in
the installed skill is modified.

Safety: one child at a time, its own process group, per-trial timeout, memory
checks before and during every trial, and an append-only state file so a stopped
run resumes without repeating finished trials.

A trial is VALID only with transcript evidence:
  activated      init event listing the skill once, then a Skill tool_use for it
                 (or a Read of its SKILL.md).
  not_activated  init event listing the skill once, then a terminal result event,
                 with no such tool_use.
Anything else (no init, skill not listed, timeout, API or usage error, memory
abort) is INVALID. Invalid trials are retried, and are never counted as misses.

Exit codes: 0 complete, 10 time budget used (resume), 11 low memory (resume later),
12 repeated invalid sessions (investigate), 2 bad input.

Adoption rule, fixed before any real trial ran:
  1. At least 90% of planned trials are valid for each description.
  2. On held-out should-trigger prompts, the revised description's true-positive
     rate is at least 15 points higher than the original's.
  3. Across all should-trigger prompts, the revised rate is higher.
  4. False positives on should-not prompts are at most 5%, and at most one trial
     more than the original.
Otherwise the original description stays.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import json
import math
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

SKILL_NAME = "telegram-craft"
ROOT = Path(__file__).resolve().parent.parent
DESCRIPTION_RE = re.compile(r'^description: "(.*)"$', re.M)
SHORT_WORDS = 16
API_ERROR_RE = re.compile(r"api error|usage limit|rate limit|limit reached|overloaded|authentication|credit", re.I)

MIN_AVAILABLE_TO_START_MB = 1100
MIN_AVAILABLE_DURING_MB = 600
LOW_MEMORY_WAIT_SECONDS = 120
MAX_ATTEMPTS = 2
MAX_CONSECUTIVE_INVALID = 3


def mem_available_mb() -> int:
    with open("/proc/meminfo", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    raise RuntimeError("MemAvailable not found")


def group_members(pgid: int) -> list[tuple[int, int]]:
    """Return (pid, rss_mb) for live, non-zombie members of a process group."""
    members = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii", errors="replace") as handle:
                after_name = handle.read().rsplit(")", 1)[1].split()
            if int(after_name[2]) == pgid and after_name[0] != "Z":
                members.append((int(entry), int(after_name[21]) * 4096 // 1048576))
        except (OSError, IndexError, ValueError):
            continue
    return members


def stop_group(process: subprocess.Popen, pgid: int) -> list[int]:
    """Stop only our child's process group. Return any pids that survived."""
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, sig)
        deadline = time.time() + wait
        while time.time() < deadline:
            process.poll()
            if not group_members(pgid):
                process.wait()
                return []
            time.sleep(0.1)
    process.poll()
    return [pid for pid, _ in group_members(pgid)]


def is_activation(tool: dict) -> bool:
    data = tool.get("input") or {}
    if tool.get("name") == "Skill":
        skill = str(data.get("skill") or data.get("command") or "")
        return skill == SKILL_NAME or skill.endswith(":" + SKILL_NAME)
    if tool.get("name") == "Read":
        return f"/.claude/skills/{SKILL_NAME}/SKILL.md" in str(data.get("file_path", ""))
    return False


def parse_event(line: str, seen: dict) -> bool:
    """Fold one stream-json line into `seen`. Return True once activation is proven."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return False
    if not isinstance(event, dict):
        return False
    if event.get("type") == "system" and event.get("subtype") == "init":
        skills = [str(s) for s in event.get("skills", [])]
        seen["init"] = True
        seen["session_id"] = event.get("session_id")
        seen["skills_total"] = len(skills)
        seen["skill_listed"] = skills.count(SKILL_NAME)
    elif event.get("type") == "result":
        seen["result"] = {
            "subtype": event.get("subtype"),
            "is_error": bool(event.get("is_error")),
            "num_turns": event.get("num_turns"),
            "text": str(event.get("result", ""))[:300],
        }
    elif event.get("type") == "assistant":
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                seen["tools"].append({"name": block.get("name"), "input": json.dumps(block.get("input"))[:160]})
                if is_activation(block) and seen.get("init"):
                    seen["activated"] = True
                    return True
    return False


def classify(seen: dict) -> tuple[str, str]:
    """Return (outcome, reason). Outcome is activated, not_activated, or invalid."""
    if seen.get("abort"):
        return "invalid", seen["abort"]
    if not seen.get("init"):
        return "invalid", "no init event"
    if seen.get("skill_listed") != 1:
        return "invalid", f"skill listed {seen.get('skill_listed')} times"
    if seen.get("activated"):
        return "activated", "Skill tool_use in transcript"
    result = seen.get("result")
    if not result:
        return "invalid", "no terminal result event"
    if result["subtype"] not in ("success", "error_max_turns"):
        return "invalid", f"result subtype {result['subtype']}"
    if result["is_error"] and (result["subtype"] != "error_max_turns" or API_ERROR_RE.search(result["text"])):
        return "invalid", "result reported an error"
    if result["subtype"] == "success" and API_ERROR_RE.search(result["text"]) and result.get("num_turns") in (0, 1):
        return "invalid", "result looks like an API or usage error"
    return "not_activated", "terminal result with no activation"


def run_trial(prompt: str, cwd: Path, args, raw_path: Path) -> dict:
    command = [
        args.claude_bin, "-p", prompt, "--output-format", "stream-json", "--verbose",
        "--model", args.model, "--max-turns", str(args.max_turns),
        "--disallowedTools", "Bash", "Write", "Edit", "NotebookEdit",
    ]
    if not args.with_mcp:  # MCP servers add child processes and memory
        command += ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    available_start = mem_available_mb()
    started = time.time()
    process = subprocess.Popen(
        command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    pgid = process.pid
    seen: dict = {"tools": []}
    raw: list[str] = []
    buffer = b""
    peak_rss = 0
    min_available = available_start
    last_sample = 0.0
    fd = process.stdout.fileno()
    while True:
        now = time.time()
        if now - last_sample >= 1:
            last_sample = now
            min_available = min(min_available, mem_available_mb())
            peak_rss = max(peak_rss, sum(rss for _, rss in group_members(pgid)))
            if min_available < args.min_during:
                seen["abort"] = f"memory abort: {min_available} MB available"
                break
        if now - started > args.timeout:
            seen["abort"] = f"timeout after {args.timeout}s"
            break
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            if process.poll() is not None:
                break
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buffer += chunk
        proven = False
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            text = line.decode("utf-8", "replace")
            raw.append(text)
            proven = parse_event(text, seen) or proven
        if proven:
            break  # activation proven: stop early to save tokens and memory
    survivors = stop_group(process, pgid)
    process.stdout.close()
    if survivors:
        seen.setdefault("abort", f"processes survived: {survivors}")
    outcome, reason = classify(seen)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(raw))
    return {
        "outcome": outcome,
        "reason": reason,
        "session_id": seen.get("session_id"),
        "skills_total": seen.get("skills_total"),
        "tools": seen["tools"][:6],
        "result_subtype": (seen.get("result") or {}).get("subtype"),
        "exit_code": process.returncode,
        "seconds": round(time.time() - started, 1),
        "peak_rss_mb": peak_rss,
        "available_start_mb": available_start,
        "available_min_mb": min_available,
        "survivors": survivors,
    }


def read_description(skill: Path) -> str:
    match = DESCRIPTION_RE.search((skill / "SKILL.md").read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("description line not found in SKILL.md")
    return match.group(1).replace('\\"', '"')


def prepare_variant(skill: Path, description: str, directory: Path) -> str:
    """Build the isolated project and return a hash of the SKILL.md it contains."""
    target = directory / ".claude/skills" / SKILL_NAME
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(skill, target, ignore=shutil.ignore_patterns("__pycache__"))
    skill_md = target / "SKILL.md"
    escaped = description.replace('"', '\\"')
    text, count = DESCRIPTION_RE.subn(lambda _: f'description: "{escaped}"', skill_md.read_text(encoding="utf-8"), count=1)
    if count != 1:
        raise SystemExit("could not set description")
    skill_md.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def load_cases(paths: list[str]) -> list[dict]:
    cases = []
    for path in paths:
        tag = next((t for t in ("holdout", "ambiguous", "mtproto") if t in Path(path).name), "train")
        for index, item in enumerate(json.loads(Path(path).read_text(encoding="utf-8"))):
            prompt = item["query"]
            if re.search(rf"{SKILL_NAME}|\bskill\b", prompt, re.I):
                raise SystemExit(f"prompt names the skill, so it would not test automatic activation: {prompt[:60]}")
            cases.append({"id": f"{tag}-{index:02d}", "set": tag, "prompt": prompt, "should_trigger": item["should_trigger"],
                          "short": len(prompt.split()) <= SHORT_WORDS, "category": item.get("category", "")})
    return cases


def plan_trials(cases: list[dict], repeats: int, seed: int) -> list[dict]:
    """Shuffle prompts within each repeat, and alternate which description goes first."""
    rng = random.Random(seed)
    trials = []
    for repeat in range(repeats):
        order = cases[:]
        rng.shuffle(order)
        for position, case in enumerate(order):
            variants = ["v1", "v2"] if (position + repeat) % 2 == 0 else ["v2", "v1"]
            trials += [{"trial": f"{v}|{case['id']}|{repeat}", "variant": v, "case": case} for v in variants]
    return trials


def read_state(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a line torn by an abrupt stop
    return records


def append_state(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def run(args) -> int:
    cases = load_cases(args.sets)
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    skill = Path(args.skill)
    variants = {"v1": read_description(skill), "v2": Path(args.candidate).read_text(encoding="utf-8").strip()}
    work = Path(args.work)
    hashes = {name: prepare_variant(skill, text, work / name) for name, text in variants.items()}
    state = Path(args.state)
    state.parent.mkdir(parents=True, exist_ok=True)
    trials = plan_trials(cases, args.repeats, args.seed)
    if args.limit:
        trials = trials[: args.limit]
    records = read_state(state)
    done = {r["trial"] for r in records if r["outcome"] != "invalid"}
    attempts: dict[str, int] = {}
    for record in records:
        attempts[record["trial"]] = attempts.get(record["trial"], 0) + 1

    started = time.time()
    consecutive_invalid = 0
    ran = 0
    for trial in trials:
        if trial["trial"] in done or attempts.get(trial["trial"], 0) >= MAX_ATTEMPTS:
            continue
        if time.time() - started > args.max_seconds:
            print(f"time budget used after {ran} trials; run again to resume")
            return 10
        waited = 0
        while mem_available_mb() < args.min_start:
            if waited >= LOW_MEMORY_WAIT_SECONDS:
                print(f"low memory: {mem_available_mb()} MB available; stopped safely, run again to resume")
                return 11
            time.sleep(15)
            waited += 15
        raw_name = trial["trial"].replace("|", "_") + f"_a{attempts.get(trial['trial'], 0)}.jsonl.gz"
        result = run_trial(trial["case"]["prompt"], work / trial["variant"], args, Path(args.raw) / raw_name)
        append_state(state, {
            "trial": trial["trial"], "variant": trial["variant"], "case": trial["case"]["id"],
            "set": trial["case"]["set"], "should_trigger": trial["case"]["should_trigger"],
            "short": trial["case"]["short"], "category": trial["case"]["category"], "skill_md_hash": hashes[trial["variant"]], "model": args.model,
            "at": datetime.now(UTC).isoformat(timespec="seconds"), **result,
        })
        ran += 1
        attempts[trial["trial"]] = attempts.get(trial["trial"], 0) + 1
        print(f"{ran:3} {trial['trial']:22} {result['outcome']:13} {result['seconds']:6}s rss {result['peak_rss_mb']:4}MB "
              f"avail-min {result['available_min_mb']}MB {result['reason'] if result['outcome'] == 'invalid' else ''}", flush=True)
        if result["reason"].startswith("memory abort"):
            print("stopped safely: memory fell below the floor; run again to resume")
            return 11
        consecutive_invalid = consecutive_invalid + 1 if result["outcome"] == "invalid" else 0
        if consecutive_invalid >= MAX_CONSECUTIVE_INVALID:
            print("stopped: repeated invalid sessions; investigate before resuming")
            return 12
    print(f"complete: {ran} trials run in this invocation")
    return 0


def wilson(hits: int, total: int) -> tuple[float, float]:
    if not total:
        return 0.0, 0.0
    z, p = 1.96, hits / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator)


def rate(records: list[dict]) -> tuple[int, int]:
    return sum(r["outcome"] == "activated" for r in records), len(records)


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n)


def fmt(hits: int, total: int) -> str:
    if not total:
        return "n/a"
    low, high = wilson(hits, total)
    return f"{hits}/{total} ({hits / total:.0%}, CI {low:.0%}-{high:.0%})"


def report(args) -> int:
    records = read_state(Path(args.state))
    # Latest valid record per trial. Invalid attempts stay in the file for the failure count.
    valid = {r["trial"]: r for r in records if r["outcome"] != "invalid"}
    rows = list(valid.values())
    planned = len(plan_trials(load_cases(args.sets), args.repeats, args.seed))
    summary: dict = {"planned_trials": planned, "valid_trials": len(rows), "attempts": len(records),
                     "invalid_attempts": sum(r["outcome"] == "invalid" for r in records)}
    print(f"planned {planned}; valid {len(rows)}; attempts {len(records)}; invalid attempts {summary['invalid_attempts']}")
    for record in records:
        if record["outcome"] == "invalid":
            print("  invalid:", record["trial"], record["reason"])
    def pick(variant, **kw):
        return [r for r in rows if r["variant"] == variant and all(r[k] == v for k, v in kw.items())]
    segments = [
        ("Should trigger, all", dict(should_trigger=True)),
        ("Should trigger, held-out", dict(should_trigger=True, set="holdout")),
        ("Should trigger, original set", dict(should_trigger=True, set="train")),
        (f"Should trigger, short (<= {SHORT_WORDS} words)", dict(should_trigger=True, short=True)),
        ("Should not trigger, all", dict(should_trigger=False)),
        ("Should not trigger, held-out", dict(should_trigger=False, set="holdout")),
    ]
    print("\n| Segment | Original | Revised |\n|---|---|---|")
    for label, filters in segments:
        print(f"| {label} | {fmt(*rate(pick('v1', **filters)))} | {fmt(*rate(pick('v2', **filters)))} |")
        summary[label] = {v: rate(pick(v, **filters)) for v in ("v1", "v2")}

    print("\n| Case | Expected | Words | Original | Revised | Prompt |\n|---|---|---|---|---|---|")
    wins = losses = 0
    for case in load_cases(args.sets):
        v1 = rate([r for r in pick("v1") if r["case"] == case["id"]])
        v2 = rate([r for r in pick("v2") if r["case"] == case["id"]])
        print(f"| {case['id']} | {'yes' if case['should_trigger'] else 'no'} | {len(case['prompt'].split())} | {v1[0]}/{v1[1]} | {v2[0]}/{v2[1]} | {case['prompt'][:46]} |")
        if case["should_trigger"] and v1[1] and v2[1]:
            difference = v2[0] / v2[1] - v1[0] / v1[1]
            wins += difference > 0
            losses += difference < 0
    print(f"\nShould-trigger prompts where revised was higher: {wins}; lower: {losses}; sign test p={sign_test(wins, losses):.3f}")

    if rows:
        seconds = sorted(r["seconds"] for r in rows)
        rss = sorted(r["peak_rss_mb"] for r in rows)
        print(f"seconds median {seconds[len(seconds)//2]} max {seconds[-1]}; peak RSS median {rss[len(rss)//2]} MB max {rss[-1]} MB; "
              f"lowest MemAvailable {min(r['available_min_mb'] for r in records)} MB; survivors {sum(len(r['survivors']) for r in records)}")
    print("hashes:", {r["variant"]: r["skill_md_hash"] for r in rows})

    v1p, v2p = rate(pick("v1", should_trigger=True)), rate(pick("v2", should_trigger=True))
    v1h, v2h = rate(pick("v1", should_trigger=True, set="holdout")), rate(pick("v2", should_trigger=True, set="holdout"))
    v1n, v2n = rate(pick("v1", should_trigger=False)), rate(pick("v2", should_trigger=False))
    def tp(pair):
        return pair[0] / pair[1] if pair[1] else 0.0
    per_variant = planned / 2
    checks = {
        "1 valid >= 90% for each": min(len(pick("v1")), len(pick("v2"))) >= 0.9 * per_variant,
        "2 held-out TPR up >= 15 points": tp(v2h) - tp(v1h) >= 0.15,
        "3 overall TPR higher": tp(v2p) > tp(v1p),
        "4 FP <= 5% and <= original + 1": tp(v2n) <= 0.05 and v2n[0] <= v1n[0] + 1,
    }
    print("\nAdoption rule:")
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")
    print("DECISION:", "adopt revised" if all(checks.values()) else "retain original")
    summary["checks"] = checks
    Path(args.state).with_suffix(".summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skill", default=str(ROOT / SKILL_NAME))
    parser.add_argument("--candidate", default=str(ROOT / "evals/description_mtproto.txt"), help="file with the candidate description")
    parser.add_argument("--sets", nargs="+", default=[str(ROOT / "evals/trigger_set.json"), str(ROOT / "evals/trigger_holdout.json")])
    parser.add_argument("--work", required=True, help="isolated scratch directory")
    parser.add_argument("--state", required=True, help="append-only JSONL results")
    parser.add_argument("--raw", required=True, help="directory for gzipped transcripts")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261108)
    parser.add_argument("--limit", type=int, default=0, help="run only the first N planned trials")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--model", default="claude-sonnet-5-5")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-seconds", type=int, default=520, help="stop starting trials after this long")
    parser.add_argument("--min-start", type=int, default=MIN_AVAILABLE_TO_START_MB)
    parser.add_argument("--min-during", type=int, default=MIN_AVAILABLE_DURING_MB)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--with-mcp", action="store_true", help="also start configured MCP servers (uses more memory)")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)
    return report(args) if args.report else run(args)


if __name__ == "__main__":
    sys.exit(main())
