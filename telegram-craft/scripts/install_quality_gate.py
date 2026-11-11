#!/usr/bin/env python3
"""Add the Telegram quality gate to a bot project (Python 3.9+, standard library).

  install_quality_gate.py PROJECT --framework aiogram|ptb|grammy [--tests-dir tests]
                          [--with-example] [--no-ci] [--force]

Copies the validation core and one framework adapter into the project, enables
the test integration, and adds a CI workflow and an optional pre-commit snippet.
Existing files are left alone unless --force is given. If the project already has
a gate somewhere else, nothing is installed and its location is printed.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
KIT = SKILL / "assets/quality-gate"
CORE = SKILL / "scripts/tg_lint.py"
ADAPTERS = {"aiogram": "aiogram_adapter.py", "ptb": "ptb_adapter.py"}
CONFTEST_LINE = "from tg_quality.pytest_plugin import *  # noqa: F401,F403\n"
SKIP_DIRS = {".git", ".claude", ".agents", "node_modules", ".venv", "venv", "site-packages", ".tox"}


def existing_gates(project: Path, package: Path) -> list[Path]:
    """Gate packages already in the project, other than the one this run would write."""
    found = []
    for core in project.rglob("lint_core.py"):
        relative = core.relative_to(project).parts
        if SKIP_DIRS.intersection(relative) or core.parent.resolve() == package.resolve():
            continue
        if (core.parent / "pytest_plugin.py").exists() or (core.parent / "tg_quality.mjs").exists():
            found.append(core.parent)
    return sorted(found)


def copy(source: Path, target: Path, force: bool, log: list[str]) -> None:
    if target.exists() and not force:
        log.append(f"kept existing {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    log.append(f"wrote {target}")


def write(text: str, target: Path, force: bool, log: list[str]) -> None:
    if target.exists() and not force:
        log.append(f"kept existing {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    log.append(f"wrote {target}")


def install(project: Path, framework: str, tests_dir: str | None, with_example: bool, no_ci: bool, force: bool) -> list[str]:
    log: list[str] = []
    node = framework == "grammy"
    tests = project / (tests_dir or ("test" if node else "tests"))
    # `node --test` executes everything under test/, so the Node kit stays outside it.
    package = project / "tg_quality" if node else tests / "tg_quality"
    others = existing_gates(project, package)
    if others and not force:
        return [f"found an existing gate at {other}; reuse it (nothing installed, --force installs a second copy)" for other in others]
    if node:
        copy(KIT / "node/tg_quality.mjs", package / "tg_quality.mjs", force, log)
        copy(CORE, package / "lint_core.py", force, log)
    else:
        copy(KIT / "python/tg_quality/__init__.py", package / "__init__.py", force, log)
        copy(KIT / "python/tg_quality/pytest_plugin.py", package / "pytest_plugin.py", force, log)
        copy(KIT / "python/tg_quality" / ADAPTERS[framework], package / ADAPTERS[framework], force, log)
        copy(CORE, package / "lint_core.py", force, log)
        conftest = tests / "conftest.py"
        if conftest.exists():
            if "tg_quality.pytest_plugin" not in conftest.read_text(encoding="utf-8"):
                with conftest.open("a", encoding="utf-8") as handle:
                    handle.write("\n" + CONFTEST_LINE)
                log.append(f"enabled the gate in {conftest}")
        else:
            write(CONFTEST_LINE, conftest, force, log)
    if with_example:
        for source in sorted((KIT / "examples" / framework).iterdir()):
            copy(source, tests / source.name, force, log)
    if not no_ci:
        name = "telegram-quality-node.yml" if node else "telegram-quality-python.yml"
        copy(KIT / "ci" / name, project / ".github/workflows/telegram-quality.yml", force, log)
        snippet = (KIT / "ci/pre-commit-telegram.yaml").read_text(encoding="utf-8").replace("__TEST_COMMAND__", "node --test" if node else "pytest -q")
        write(snippet, project / ".pre-commit-telegram.yaml", force, log)
    ignore = project / ".gitignore"
    text = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if ".tg-lint" not in text:
        with ignore.open("a", encoding="utf-8") as handle:
            handle.write(".tg-lint/\n")
        log.append("added .tg-lint/ to .gitignore")
    return log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--framework", required=True, choices=["aiogram", "ptb", "grammy"])
    parser.add_argument("--tests-dir")
    parser.add_argument("--with-example", action="store_true")
    parser.add_argument("--no-ci", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    project = Path(args.project)
    if not project.is_dir():
        print(f"bad input: {project} is not a directory", file=sys.stderr)
        return 2
    for line in install(project, args.framework, args.tests_dir, args.with_example, args.no_ci, args.force):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
