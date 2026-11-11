# Contributing

Thanks for helping improve Telegram Craft.

## Before you change anything

- **Facts come from the official docs.** Check every Bot API or MTProto claim with `python3 telegram-craft/scripts/tgdocs.py` or core.telegram.org, and every library claim against the installed or released package. Do not write facts from memory.
- **Keep the skill lean.** `SKILL.md` stays under 500 lines; a reference over 300 lines gets split or a table of contents. Add guidance when an agent repeats a mistake, and remove guidance that no longer changes behavior.
- **Write your own text.** Do not copy content from other skills.

## Making a change

1. Edit the files under `telegram-craft/` and add or update tests in `tests/`.
2. Run the checks:
   ```bash
   pip install -r requirements-dev.txt
   python3 tests/validate_skill.py
   pytest -q
   ```
   Set `TG_TEST_NODE_MODULES` to a `node_modules` folder with grammY to include the grammY tests.
3. If you change the skill's `description`, test activation with `evals/trigger_compare.py`. It runs one process at a time; never run evaluations in parallel.
4. For a release, bump `metadata.version` in `SKILL.md` and `version` in `.claude-plugin/marketplace.json`, and add a `CHANGELOG.md` entry.

## Rules for tests

- No real Telegram connections, tokens, or sessions in tests. Use fakes; live checks follow `LIVE_TEST_PLAN.md` and need the owner's approval.
- A warning about style never fails CI by default; only invalid payloads are errors.

## Pull requests

Describe what changed, why, and how you verified it. Say which evidence level (L0 to L3) your verification reached.
