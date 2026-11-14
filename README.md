<p align="center">
  <img src="docs/banner.svg" alt="Telegram Craft: an Agent Skill for production Telegram bots, Mini Apps, and MTProto clients" width="100%">
</p>

<p align="center">
  <img alt="Agent Skill" src="https://img.shields.io/badge/Agent%20Skill-telegram--craft-6f42c1">
  <img alt="Bot API 10.4" src="https://img.shields.io/badge/Bot%20API-10.4-26a5e4">
  <img alt="MTProto" src="https://img.shields.io/badge/MTProto-Telethon%20%7C%20Pyrogram-26a5e4">
  <img alt="Python 3 standard library tools" src="https://img.shields.io/badge/tools-Python%203%2C%20stdlib-3776ab">
  <img alt="MIT license" src="https://img.shields.io/badge/license-MIT-blue">
</p>

**Build Telegram bots, Mini Apps, and MTProto clients that hold up in production, with the checks to show it.**

```bash
npx skills add bisnuray/telegram-craft
```

Then ask: `Build an aiogram bot that sells a monthly Stars subscription.`

Telegram projects usually fail in three ways: API calls written from memory, a chat designed like a web page, and client data trusted because it looks official. Telegram Craft gives a coding agent the current API facts, the design rules for chat interfaces, and runnable checks for each of those failures. When it hands work back, it says how far the result was verified.

---

- [What it covers](#what-it-covers)
- [Runnable, not just described](#runnable-not-just-described)
- [Install](#install)
- [Usage](#usage)
- [Tools](#tools)
- [Testing](#testing)
- [Scope and safety](#scope-and-safety)
- [Repository](#repository)
- [Maintenance](#maintenance)

## What it covers

| Surface | The agent gets |
|---|---|
| **Bot API bots** (aiogram, python-telegram-bot, pyTelegramBotAPI, grammY, Telegraf, raw API) | Messages and `/start` flows, rich message screens in one standard style (bordered tables, no emoji clutter, a recipe per screen type), inline keyboards and navigation, button styles, widgets (10.4), FSM, webhooks, rate limits, broadcasts, groups and moderation |
| **Telegram Stars** | Invoices, subscriptions, refunds, granting on `successful_payment` exactly once |
| **Mini Apps** | Server-side `initData` validation, theme, safe areas, native buttons, loading states, accessibility |
| **MTProto clients** (Telethon, Pyrogram forks such as kurigram) | User accounts run from an existing `StringSession` (no login prompts at startup, clear failure when it is missing or revoked), one-time sign-in script, bot sessions, `FloodWait`, reconnects, entity caching, session security, authorization boundaries |
| **Hybrid apps** | Bot API interface with an MTProto worker for large files or history, kept separate |
| **Media** | ffmpeg jobs, size limits, `file_id` caching, progress, cleanup |
| **Code quality** | Design sized to the product, comments that explain why (never narration), narrow error handling, owned async tasks with timeouts and clean shutdown, and a curated Ruff config |

It sizes the process to the job. A one-line fix stays a one-line fix. A new bot starts with a screen map and one working flow.

## Runnable, not just described

| Component | What it does |
|---|---|
| **Quality gate** | Plugs into your tests at the HTTP layer of aiogram, python-telegram-bot, or grammY. Every real outgoing message and keyboard is checked: limits, HTML and MarkdownV2, rich message HTML (tags, nesting, entities, media, limits), `callback_data` bytes, keyboard structure, invoices, widgets, unanswered callbacks. Invalid payloads fail CI. Interface warnings never do. |
| **Coverage report** | Separates *confirmed* gaps (a registered handler that never ran, a button the code builds but no test ever showed) from *possible* ones found by a source scan. It never claims full coverage because every visible button was pressed. |
| **`update_delivery.py`** | Inbox with leased claims, outbox, 429 handling, per-chat lanes, resumable broadcasts. `--self-test` checks 9 guarantees, each against a deliberately broken variant. |
| **`secure_mtproto_project.py`** | Adds missing `.gitignore` rules for `.session` files and `.env`, adds a CI job that fails on a committed session, and reports leaked session strings. It never deletes or revokes anything. |
| **`tg_audit.py` and Ruff** | Ruff (`assets/ruff.template.toml`) catches unused and dead code, blind or empty `except`, dropped tasks, and blocking calls in async code. `tg_audit.py` adds what Ruff cannot see: swallowed cancellation, a user client started with `start()` or logged out at runtime, `StringSession` from a possibly empty variable, and secrets baked into a Dockerfile. |
| **`tgdocs.py`** | Reads the current official Bot API and MTProto docs, so facts are looked up, not recalled. |
| **Assets** | Copy-and-adapt code: `rich_html.py` (rich screens, escaped by construction), `mtproto_runtime.py` (StringSession loading and authorized connect), `create_session.py` (one-time sign-in), `initData` validation (Python and JS), a Stars ledger, media jobs, MTProto runtime helpers with log redaction, a Mini App browser mock |

## Install

**Any Agent Skills client** (Claude Code, Codex, OpenCode, Cursor, and others), with the [skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add bisnuray/telegram-craft
```

**Claude Code plugin**:

```text
/plugin install telegram-craft --marketplace bisnuray/telegram-craft
```

On Claude Code older than 2.1.275, add the marketplace first: `/plugin marketplace add bisnuray/telegram-craft`, then `/plugin install telegram-craft@telegram-craft`.

**Manual copy**: copy `telegram-craft/` into your client's skills directory:

| Client | Personal | Project |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.agents/skills/` | `.agents/skills/` |
| Other [Agent Skills](https://agentskills.io) clients | the client's skills directory | the client's project directory |

```bash
cp -r telegram-craft ~/.claude/skills/        # Claude Code, all projects
cp -r telegram-craft .claude/skills/          # Claude Code, this project only
```

The tools need only Python 3. The quality gate's grammY adapter also needs Node.js.

## Usage

The skill activates on its own for Telegram development work, including Telethon and MTProto requests. You can also name it:

```text
Use telegram-craft to build a bot that converts audio to voice messages.
Use telegram-craft to redesign the messages in bot.py without changing behavior.
Use telegram-craft to add a monthly Stars subscription.
Use telegram-craft to download files over 20 MB with a Telethon bot session.
Use telegram-craft to audit this bot and Mini App before launch.
```

In Codex, use `$telegram-craft`.

Every handoff ends with what you can now do, the files changed, how to run it, what you must set up in BotFather, and what was verified at which level:

| Level | Evidence | May claim |
|---|---|---|
| L0 | Docs or code read | "Should work per the docs" |
| L1 | Linters, `tg_lint.py`, `tg_audit.py` | "Passes static checks" |
| L2 | Tests with the real dispatcher and a fake Telegram | "Works locally against a fake Telegram" |
| L3 | A test bot in a real Telegram client | "Works in Telegram" |

## Tools

```bash
python3 telegram-craft/scripts/tgdocs.py version                       # current Bot API version
python3 telegram-craft/scripts/tgdocs.py method sendMessage             # one method's official contract
python3 telegram-craft/scripts/tg_lint.py screens.json                  # check messages and keyboards
python3 telegram-craft/scripts/tg_audit.py path/to/project              # static leads for Telegram, MTProto, and async defects
ruff check path/to/project                                              # with the project's config, or assets/ruff.template.toml
python3 telegram-craft/scripts/install_quality_gate.py path/to/project --framework aiogram   # or ptb, grammy
python3 telegram-craft/scripts/secure_mtproto_project.py path/to/project --ci               # protect MTProto sessions
python3 telegram-craft/assets/update_delivery.py --self-test           # verify the delivery guarantees
```

Quality gate settings: `TG_LINT_REQUIRE_INTERACTIONS=1` fails a run that captured nothing (set in the CI template). `TG_LINT_REQUIRE_COVERAGE=1` fails on confirmed coverage gaps only. `TG_LINT_STRICT=1` also fails on warnings.

## Testing

The tools and the quality gate have their own test suite, run in CI on every push:

```bash
pip install -r requirements-dev.txt
python3 tests/validate_skill.py
ruff check .
pytest -q
```

`evals/trigger_compare.py` checks whether the skill activates on the right requests and stays quiet on the wrong ones. Live Telegram validation has not been run yet; see [`LIVE_TEST_PLAN.md`](LIVE_TEST_PLAN.md).

Agent behavior varies by model, client, and project. Test the skill in your own environment before relying on it for critical work.

## Scope and safety

- **For building Telegram software.** It does not operate your account, send one-off messages, or wire a single alert into a script.
- **MTProto only with authorization.** User-account automation is for accounts you own or are allowed to operate. It will not help with spam, mass messaging, or evading Telegram's limits.
- **Credentials stay out of code and logs.** Tokens stay on the server, and sessions are encrypted and git-ignored. The tools never revoke a session; that is the account owner's call.
- **Nothing live by default.** It does not start a production bot, change a webhook, broadcast, or spend Stars unless asked.

## Repository

| Path | Contents |
|---|---|
| [`telegram-craft/`](telegram-craft/) | The skill. This is all you install. |
| [`LIVE_TEST_PLAN.md`](LIVE_TEST_PLAN.md) | Staged plan for live Telegram validation (not yet run) |
| [`API_COVERAGE.md`](API_COVERAGE.md) | Bot API, MTProto, and Mini App coverage matrix |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Design decisions |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history |
| [`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md) | How to contribute; how to report a vulnerability |
| `.claude-plugin/` | Claude Code marketplace manifest |
| `docs/` | Banner and logo |
| `tests/` | Tests for the tools and the quality gate |
| `evals/` | Activation test harness (`evals/trigger_compare.py`), prompt sets, and sample bots |

## Maintenance

When a new Bot API version ships (`tgdocs.py version` reports newer than 10.4):

1. Run `tgdocs.py changes --since 10.4`.
2. Update `references/platform-facts.md` and any affected reference, then `bot-api-snapshot` and `verified` in `SKILL.md`. A test fails until every version reference agrees.
3. Re-check library versions in `references/frameworks.md`.
4. Run `python3 tests/validate_skill.py` and `pytest` (see `requirements-dev.txt`; set `TG_TEST_NODE_MODULES` to include the grammY tests).
5. Update the Bot API badge at the top of this README. The banner shows no version, so it needs no change.
6. Re-run the evals affected by the change, each in its own temporary directory.
7. To test a description change, use `evals/trigger_compare.py`. It runs one Claude process at a time, resumes after a stop, and has memory guards. Do not run evaluations in parallel on a small host.

For every release, bump `metadata.version` in `SKILL.md` and `version` in `.claude-plugin/marketplace.json` together (a test checks they match), and add a `CHANGELOG.md` entry.

Test every change before relying on it. Add a gotcha when an agent repeats a mistake, and remove guidance that no longer changes behavior.

## License

[MIT](LICENSE). The guidance and artwork are original. Third-party skills were studied but not copied.

Telegram Craft is an independent project, not affiliated with or endorsed by Telegram. "Telegram" is a trademark of its owner. The logo is original; the banner uses a generic paper-plane motif, not Telegram's logo.
