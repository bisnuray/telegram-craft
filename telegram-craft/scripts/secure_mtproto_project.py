#!/usr/bin/env python3
"""Protect MTProto credentials in a project (Python 3.9+, standard library).

  secure_mtproto_project.py PROJECT [--check] [--ci] [--json]

Without --check, appends any missing credential rules to .gitignore: Telethon
.session files and their SQLite sidecars (-journal, -wal, -shm), encrypted session
files, .env files (keeping .env.example), and Telegram Desktop tdata/ exports.
Existing rules are never changed or reordered.

Then it reports, and never fixes:
  - session files tracked by git, or present and not ignored
  - session strings in source, and sessions passed to print or log calls
  - hard-coded api_hash values

--ci also writes .github/workflows/telegram-credentials.yml (never over an existing
file): a self-contained job that fails when a session file is tracked or a session
string appears in tracked files, so the protection does not depend on anyone
remembering to run this script.

It never deletes, untracks, or revokes a session. Ending a leaked session is the
account owner's decision; see references/mtproto-foundations.md.
Exit codes: 0 clean, 1 problems found (or rules missing with --check), 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tg_audit import SESSION_FILE_SUFFIXES, SESSION_IGNORE_RULES, collect, credential_leads, ignore_rules, session_ignored  # noqa: E402

HEADER = "# Telegram MTProto credentials (added by telegram-craft)"
WORKFLOW = """name: telegram-credentials
on: [push, pull_request]
jobs:
  telegram-credentials:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: No MTProto session files or session strings in the repository
        run: |
          status=0
          if git ls-files | grep -E '[.]session(-journal|-wal|-shm|[.]enc)?$'; then
            echo "::error::session files are tracked; untrack them and have the owner end those sessions"; status=1
          fi
          if git grep -nIE '(^|[^A-Za-z0-9_+/-])1[A-Za-z0-9_+/-]{300,}={0,2}' -- . ':!*.lock' ':!*.svg'; then
            echo "::error::possible Telethon session string in a tracked file"; status=1
          fi
          exit $status
"""
EXAMPLES = {"*.session": "a.session", "*.session-journal": "a.session-journal", "*.session-wal": "a.session-wal",
            "*.session-shm": "a.session-shm", "*.session.enc": "a.session.enc", ".env": ".env", ".env.*": ".env.production",
            "tdata/": "tdata/key_datas"}


def missing_rules(root: Path) -> list[str]:
    """Rules not already present or covered. The .env.example exception is added only with our own .env.* rule."""
    present = ignore_rules(root)
    missing = [rule for rule in SESSION_IGNORE_RULES if rule in EXAMPLES and rule not in present and not session_ignored(EXAMPLES[rule], present)]
    if ".env.*" in missing and "!.env.example" not in present:
        missing.append("!.env.example")
    return missing


def append_rules(root: Path, rules: list[str]) -> None:
    file = root / ".gitignore"
    existing = file.read_text(encoding="utf-8") if file.exists() else ""
    block = ("" if not existing or existing.endswith("\n") else "\n") + ("\n" if existing else "") + HEADER + "\n" + "\n".join(rules) + "\n"
    with file.open("a", encoding="utf-8") as handle:
        handle.write(block)


def git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


def tracked_session_files(root: Path) -> list[str] | None:
    """Session files already in git's index. None when this is not a git checkout or git is missing."""
    if not (root / ".git").exists():
        return None
    done = git(root, "ls-files", "-z")
    if done is None or done.returncode != 0:
        return None
    return sorted(name for name in done.stdout.split("\0") if name.endswith(SESSION_FILE_SUFFIXES))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--check", action="store_true", help="report only; exit 1 if rules are missing")
    parser.add_argument("--ci", action="store_true", help="also add a CI workflow that fails on tracked sessions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.project)
    if not root.is_dir():
        print(f"bad input: {root} is not a directory", file=sys.stderr)
        return 2
    missing = missing_rules(root)
    added: list[str] = []
    if missing and not args.check:
        append_rules(root, missing)
        added, missing = missing, []
    workflow_note = ""
    if args.ci:
        workflow = root / ".github/workflows/telegram-credentials.yml"
        if workflow.exists():
            workflow_note = f"kept existing {workflow.relative_to(root)}"
        else:
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text(WORKFLOW, encoding="utf-8")
            workflow_note = f"wrote {workflow.relative_to(root)}"
    leads = credential_leads(root, collect(root))
    tracked = tracked_session_files(root)
    problems = [f"{lead.path}:{lead.line} [{lead.rule}] {lead.message}" for lead in leads if lead.severity == "high"]
    for name in tracked or []:
        problems.append(f"{name} [session-file-tracked] is tracked by git. Untrack it with `git rm --cached {name}`, "
                        "then have the owner end that session; it stays in git history until the history is rewritten")
    result = {"added_rules": added, "missing_rules": missing, "problems": problems, "ci": workflow_note,
              "git": "not a git repository or git unavailable" if tracked is None else "checked"}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if added:
            print(f"appended to .gitignore: {' '.join(added)}")
        if workflow_note:
            print(workflow_note)
        if missing:
            print(f"missing from .gitignore: {' '.join(missing)}")
        for problem in problems:
            print(f"problem: {problem}")
        if tracked is None:
            print("note: not a git repository (or git unavailable), so tracked files were not checked")
        if not (added or missing or problems):
            print("MTProto credential rules present; no exposed session found")
    return 1 if problems or missing else 0


if __name__ == "__main__":
    sys.exit(main())
