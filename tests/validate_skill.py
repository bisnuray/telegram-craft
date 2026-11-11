#!/usr/bin/env python3
"""Structural validation of the skill against the Agent Skills specification.

The name, description, compatibility, and allowed-field rules mirror
agentskills/agentskills skills-ref (read from source; re-implemented here).
The remaining checks are project budgets and reference integrity.

  python3 tests/validate_skill.py [SKILL_DIR]
"""
import re
import sys
import unicodedata
from pathlib import Path

ALLOWED = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000  # spec recommendation; estimated at 4 chars per token
MAX_REFERENCE_LINES = 300


def parse_frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not match:
        return None, text
    fields = {}
    current = None
    for line in match.group(1).splitlines():
        top = re.match(r"([A-Za-z-]+):\s*(.*)", line)
        if top:
            current = top.group(1)
            value = top.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1].replace('\\"', '"')
            fields[current] = value
    return fields, match.group(2)


def validate(root):
    errors, notes = [], []
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        return [f"missing {skill_md}"], notes
    fields, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    if fields is None:
        return ["SKILL.md has no YAML frontmatter"], notes

    unknown = set(fields) - ALLOWED
    if unknown:
        errors.append(f"unexpected frontmatter fields: {sorted(unknown)}")

    name = unicodedata.normalize("NFKC", fields.get("name", ""))
    if not name:
        errors.append("name is required")
    if len(name) > 64 or name != name.lower():
        errors.append("name must be at most 64 lowercase characters")
    if name.startswith("-") or name.endswith("-") or "--" in name:
        errors.append("name has misplaced hyphens")
    if not all(c.isalnum() or c == "-" for c in name):
        errors.append("name has invalid characters")
    if name != root.resolve().name:
        errors.append(f"name {name!r} must match directory {root.resolve().name!r}")

    description = fields.get("description", "")
    if not description or len(description) > 1024:
        errors.append(f"description must be 1-1024 characters (got {len(description)})")
    if "compatibility" in fields and len(fields["compatibility"]) > 500:
        errors.append("compatibility over 500 characters")

    lines = body.count("\n")
    tokens = len(body) // 4
    if lines > MAX_BODY_LINES:
        errors.append(f"SKILL.md body is {lines} lines (limit {MAX_BODY_LINES})")
    if tokens > MAX_BODY_TOKENS:
        errors.append(f"SKILL.md body is about {tokens} tokens (recommended limit {MAX_BODY_TOKENS})")
    notes.append(f"body: {lines} lines, about {tokens} tokens; description: {len(description)} characters")

    references = sorted((root / "references").glob("*.md"))
    all_text = {skill_md: body}
    for ref in references:
        all_text[ref] = ref.read_text(encoding="utf-8")
        count = all_text[ref].count("\n")
        if count > MAX_REFERENCE_LINES:
            errors.append(f"{ref.name} is {count} lines; split it or add a table of contents")

    mentioned = set(re.findall(r"`([a-z-]+\.md)`", body))
    for ref in references:
        if ref.name not in mentioned:
            errors.append(f"orphan reference: {ref.name} is not routed from SKILL.md")
    for name_ in sorted(mentioned):
        if not (root / "references" / name_).is_file():
            errors.append(f"SKILL.md routes to a missing reference: {name_}")

    for path, text in all_text.items():
        if text.count("```") % 2:
            errors.append(f"{path.name}: unbalanced code fences")
        for script in re.findall(r"`?(scripts/[\w.-]+|assets/[\w.-]+)`?", text):
            if not (root / script).is_file():
                errors.append(f"{path.name}: references missing file {script}")
        for link in re.findall(r"`([a-z-]+\.md)`", text):
            if not (root / "references" / link).is_file():
                errors.append(f"{path.name}: references missing {link}")

    for bad in root.rglob("*"):
        if bad.is_dir() and bad.name in ("__pycache__", "node_modules", ".pytest_cache"):
            errors.append(f"stray directory in skill: {bad.relative_to(root)}")
        if bad.is_file() and bad.suffix in (".pyc", ".log"):
            errors.append(f"stray file in skill: {bad.relative_to(root)}")
    notes.append(f"{len(references)} references; total {sum(t.count(chr(10)) for t in all_text.values())} lines")
    return errors, notes


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "telegram-craft"
    errors, notes = validate(target)
    for note in notes:
        print("note:", note)
    for error in errors:
        print("error:", error)
    print("VALID" if not errors else f"INVALID ({len(errors)} errors)")
    sys.exit(1 if errors else 0)
