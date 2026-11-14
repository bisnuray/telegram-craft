"""Release metadata stays consistent across the skill and the Claude Code marketplace manifest."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKILL_MD = ROOT / "telegram-craft/SKILL.md"
MARKETPLACE = ROOT / ".claude-plugin/marketplace.json"


def skill_version():
    return re.search(r'^  version: "([^"]+)"', SKILL_MD.read_text(), re.MULTILINE).group(1)


def test_marketplace_points_at_the_skill_and_versions_match():
    data = json.loads(MARKETPLACE.read_text())
    [plugin] = data["plugins"]
    assert plugin["name"] == "telegram-craft"
    assert plugin["source"] == "./telegram-craft"
    assert (ROOT / plugin["source"] / "SKILL.md").is_file()
    assert plugin["version"] == skill_version()


def test_changelog_has_the_current_version():
    assert f"## {skill_version()} (" in (ROOT / "CHANGELOG.md").read_text()
