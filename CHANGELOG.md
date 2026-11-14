# Changelog

All notable changes to Telegram Craft. Versions follow `metadata.version` in `telegram-craft/SKILL.md`.

## 1.2.0 (2026-11-14)

### Added
- **Code-quality standard** (`references/code-quality.md`), loaded for Python code work. It covers:
  - design sized to the product, with no one-implementation abstractions, placeholders, or dead code;
  - names, and review signals instead of hard limits;
  - comments that explain why, never narrate, with Telegram-specific examples; existing context comments are kept;
  - narrow error handling with one error boundary, and no swallowed cancellation or fake success;
  - async lifecycle: owned tasks, timeouts, bounded retries, and shutdown order;
  - logging without secrets;
  - a review checklist and a table of rationalizations to reject.
- **Curated Ruff config** (`assets/ruff.template.toml`) with an explicit rule list mapped to defect classes.
- **StringSession-first MTProto runtime**:
  - `string_session_from_env()` refuses missing, empty, or malformed sessions instead of starting a new login;
  - `connect_authorized()` connects, verifies authorization, and never prompts;
  - `assets/create_session.py` is the one-time sign-in the owner runs, writing a mode-0600 file;
  - guidance for revocation, `AUTH_KEY_DUPLICATED`, and rotation.
- **`tg_audit.py` leads**: `swallowed-cancellation`, `empty-string-session`, `user-client-start`, `log-out`, and `secret-in-image` (Dockerfile `ENV`/`ARG`). `secure_mtproto_project.py` also reports a real `.env` tracked by git.
- **Mini App frontend code** guidance in `mini-apps.md`: strict TypeScript, validated responses, effect cleanup, and request states.

- `LIVE_TEST_PLAN.md` stage 5 validates the StringSession runtime: one-time sign-in, prompt-free restart, and a clean exit after the session is ended.

### Changed
- New bots get a layout sized to the product: a small package for a utility bot, the full layout for a product bot. SKILL.md rules 16 to 18 cover code quality, error and task ownership, and MTProto sessions.
- The repository lints itself with the same Ruff rules in CI. Fixed:
  - a silent `except Exception: pass` in `assets/update_delivery.py`, which now logs;
  - an unused loop variable;
  - ambiguous names;
  - regex call style.
- Copy-and-adapt assets keep `asyncio.TimeoutError` and `timezone.utc`, so they still run on Python 3.10.

## 1.1.0 (2026-11-11)

### Added
- **Standard style for rich message screens** (`references/rich-messages.md`): plain titles without emoji, bordered tables, one divider between summary and body, no text that repeats the keyboard, no internal IDs.
- **Screen recipes** (`references/rich-recipes.md`) for home, picker, detail, data list, settings, help, receipt, report, problem, confirmation, and progress, with a messy-versus-standard example.
- **`assets/rich_html.py`**: a standard-library builder for rich HTML. It escapes all user text, makes tables bordered, never emits empty (hidden) cells, and checks the limits.
- **Rich HTML validation** in `tg_lint.py` and the quality gate. Errors for what Telegram rejects: unsupported tags, wrong nesting, unclosed tags, unsupported named entities, bad attributes, unknown `tg://` media, and limits. Style warnings for emoji, borderless tables, empty cells, repeated keyboard items, misplaced dividers, busy screens, and `parse_mode` sent with `rich_message`.
- **Library coverage**: pyTelegramBotAPI 4.37.1 and kurigram 2.2.27 rich messages; the aiogram `parse_mode=None` rule for rich edits.
- **Fallback ladder** for rich messages, classified by failure type, with no silent fallback for money or legal screens.
- **Rich screen review** stage (1b) in `LIVE_TEST_PLAN.md`: only real client screenshots count as visual proof.
- **Standard project layout** for new bots (`references/backend.md`).
- **Install** with `npx skills add bisnuray/telegram-craft` or as a Claude Code plugin (`.claude-plugin/marketplace.json`).

### Changed
- Every bot screen is a rich message by default; formatted HTML text is the fallback.

## 1.0.0 (2026-11-10)

- Initial release: Bot API 10.4 facts, message and keyboard design, quality gate for aiogram, python-telegram-bot, and grammY, coverage report, update delivery, Mini App `initData` validation, Stars ledger, media jobs, and MTProto session security.
