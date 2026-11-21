"""The API lists in the references replace reading asset source, so they must match the code."""
import ast
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "telegram-craft"


def public_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            names.add(node.name)
    return names


def test_rich_html_helpers_listed_in_rich_messages_exist():
    text = (SKILL / "references/rich-messages.md").read_text()
    table = text[text.index("| Kind | Helpers |"):text.index("Show only data the product really has.")]
    documented = set(re.findall(r"`([a-z_]+)(?:\(|`)", table))
    assert documented, "helper table not found"
    assert documented <= public_names(SKILL / "assets/rich_html.py")


def test_harness_methods_listed_in_quality_gate_exist():
    text = (SKILL / "references/quality-gate.md").read_text()
    documented = set(re.findall(r"bot\.([a-z_]+)", text))
    package = SKILL / "assets/quality-gate/python/tg_quality"
    available = public_names(package / "__init__.py") | public_names(package / "aiogram_adapter.py")
    assert documented <= available, documented - available


def test_mongo_store_api_listed_in_database_exists():
    text = (SKILL / "references/database.md").read_text()
    block = text[text.index("Copy `assets/mongo_store.py`"):text.index("**Documents.**")]
    documented = set(re.findall(r"`([A-Za-z_]+)\(", block))
    assert documented <= public_names(SKILL / "assets/mongo_store.py"), documented - public_names(SKILL / "assets/mongo_store.py")
