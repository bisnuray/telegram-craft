# Changelog

All notable changes to Telegram Craft. Versions follow `metadata.version` in `telegram-craft/SKILL.md`.

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
