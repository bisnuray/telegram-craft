"""Fail the pytest run when captured Telegram traffic is invalid.

Enable from tests/conftest.py:  from tg_quality.pytest_plugin import *

Environment:
  TG_LINT_STRICT=1                 warnings also fail
  TG_LINT_MIN_BUTTON_COVERAGE=0.8  fail if fewer offered buttons were pressed
  TG_LINT_REQUIRE_INTERACTIONS=1   fail if no test captured anything (set this in CI)
  TG_LINT_REQUIRE_COVERAGE=1       fail on confirmed coverage gaps: a registered handler
                                   that never ran, or a callback sent without its screen
  TG_LINT_SOURCE=0                 skip the static callback_data scan of the project
  TG_LINT_DIR=.tg-lint             output directory
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from . import SESSION_STRING, Recorder
from .lint_core import coverage_lines, finding_line, coverage_report, lint_capture, source_callbacks

_recorder = Recorder()
_result: dict = {}


@pytest.fixture(scope="session")
def tg_recorder() -> Recorder:
    return _recorder


def pytest_sessionfinish(session, exitstatus) -> None:
    directory = Path(os.environ.get("TG_LINT_DIR", ".tg-lint"))
    interactions = _recorder.interactions
    findings = lint_capture(interactions)
    handlers = list(_recorder.handlers.values()) if _recorder.handlers is not None else None
    sources = None
    if interactions and os.environ.get("TG_LINT_SOURCE", "1") != "0":
        sources = source_callbacks(Path(str(session.config.rootpath)))
    coverage = coverage_report(interactions, handlers, sources)
    errors = sum(f["level"] == "error" for f in findings)
    _result.update(findings=findings, coverage=coverage, errors=errors, warnings=len(findings) - errors)
    if interactions:
        _recorder.save(directory)
        report = SESSION_STRING.sub("<session string>", json.dumps(_result, ensure_ascii=False, indent=2))
        (directory / "report.json").write_text(report, encoding="utf-8")
    minimum = float(os.environ.get("TG_LINT_MIN_BUTTON_COVERAGE", "0") or 0)
    reasons = []
    if errors:
        reasons.append(f"{errors} Telegram payload error(s)")
    if os.environ.get("TG_LINT_STRICT") == "1" and _result["warnings"]:
        reasons.append(f"{_result['warnings']} warning(s) in strict mode")
    if coverage["button_coverage"] is not None and coverage["button_coverage"] < minimum:
        reasons.append(f"button coverage {coverage['button_coverage']} below {minimum}")
    if interactions and os.environ.get("TG_LINT_REQUIRE_COVERAGE") == "1" and coverage["confirmed_gaps"]:
        reasons.append(f"{len(coverage['confirmed_gaps'])} confirmed coverage gap(s)")
    if not interactions and os.environ.get("TG_LINT_REQUIRE_INTERACTIONS") == "1":
        reasons.append("no Telegram interactions were captured")
    _result["reasons"] = reasons
    if reasons and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter) -> None:
    if not _result or (not _recorder.interactions and not _result.get("reasons")):
        return
    tr = terminalreporter
    tr.section("Telegram quality gate")
    for finding in sorted(_result["findings"], key=lambda item: item["level"]):
        tr.write_line(finding_line(finding))
    for line in coverage_lines(_result["coverage"]):
        tr.write_line(line)
    for reason in _result.get("reasons", []):
        tr.write_line(f"GATE FAILED: {reason}", red=True)
