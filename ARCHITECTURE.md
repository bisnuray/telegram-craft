# Architecture

`telegram-craft` is one skill with one router file, 20 topic references, 4 tools, 6 copyable assets, and a quality-gate kit. Design choices come from a review of Telegram's official documentation and of published Telegram agent skills, and from measured activation and agent-behavior tests.

## Layout

```
telegram-craft/
├── SKILL.md              Router: job sizing, surface choice, ranked rules, routing, tools, proof levels
├── LICENSE               MIT
├── agents/openai.yaml    Codex display metadata
├── references/           Loaded only when the routing table's condition applies
│   ├── product-journeys.md   Screen maps, /start, onboarding, multilingual
│   ├── messages.md           Copy by message job, before and after
│   ├── keyboards.md          Labels, callbacks, navigation, stale actions
│   ├── formatting.md         HTML, MarkdownV2, rich messages, streaming
│   ├── backend.md            Structure by size, data, state, jobs, retries, shutdown
│   ├── delivery.md           Polling, webhooks, containers, rate limits, broadcasts
│   ├── frameworks.md         Bot API vs MTProto, library choice and traps
│   ├── media.md              Limits, FFmpeg safety, caching, progress
│   ├── payments.md           Stars, subscriptions, refunds, marketplaces
│   ├── mini-apps.md          Launch, init data, viewport, native controls
│   ├── mini-app-design.md    Visual quality, accessibility, states
│   ├── security.md           Trust boundaries, authz, privacy, abuse
│   ├── groups-automation.md  Moderation, inline, ephemeral, AI, bot-to-bot
│   ├── existing-projects.md  Inspection, debugging, safe refactors
│   ├── quality.md            Journey tests, review rubric
│   ├── platform-facts.md     Dated limits and recent API changes
│   ├── quality-gate.md       Automatic payload checks
│   ├── mtproto-foundations.md  API choice, sign-in, sessions, restrictions
│   ├── mtproto-telethon.md   Telethon runtime, flood waits, media, tests
│   └── hybrid-architecture.md  Bot API plus MTProto systems
├── scripts/
│   ├── tgdocs.py         Live official docs lookup
│   ├── tg_lint.py        Validation core (screens and captured traffic)
│   ├── install_quality_gate.py  Adds the gate to a project
│   └── tg_audit.py       Static project scan (leads only)
└── assets/
    ├── init_data.py, init_data.mjs   Server-side Mini App validation
    ├── stars_ledger.py               Idempotent payment ledger
    ├── media_job.py                  Safe subprocess and temp handling
    ├── mtproto_runtime.py            Bounded flood control, session store, lifecycle
    ├── webapp_mock.js                Mini App browser preview
    └── quality-gate/                 Adapters, test gates, CI templates, examples
```

Reports, tests, fixtures, and eval results sit outside the skill so that they are not installed or loaded at runtime.

## Decisions and tradeoffs

| Decision | Reason | Tradeoff |
|---|---|---|
| One skill, not a family | A single listing costs less discovery budget than the 16 listings of `using-aiogram` and its siblings; a hybrid product needs bot and Mini App guidance together | Broader description has to discriminate well |
| Router `SKILL.md` around 2,400 tokens | Spec recommends under 5,000 and every activation pays for it | Some rules appear only in references, so routing must work |
| Rules ranked by cost of failure | Pattern taken from Vercel's priority model; the agent should get security and money right first | Ordering is a judgment call |
| Job-sizing table | Avoids imposing full workflows on small fixes, an anti-pattern seen in several skills | Agents must classify correctly |
| Dated facts plus live lookup | The API changed parameter names within one release | The snapshot will age; `tgdocs.py` and the maintenance procedure offset this |
| Facts fetched, instructions not | Unlike remote-instruction skills, fetched pages are labeled as data | Requires network for freshness; exit code 3 signals offline |
| Standard-library scripts | Must run in any project language | The Python AST audit is deeper than the regex-based JS checks |
| Lint warnings separated from errors | UX signals are heuristics. Hard failures should only be contract violations. | Some warnings will be false positives |
| Audit outputs are "leads" | Adopted from the audit skill's principle. Static scans miss context. | Takes a human or agent read to confirm |
| Evidence levels L0–L3 | Offline tests and mock previews must not read as Telegram verification | Reports are longer |
| Copyable assets, no starter template | A full template would impose one structure on every bot, so only the fragile parts are provided | New projects still write their own scaffolding |
| Media gets its own reference | `ffmpeg` appeared in no Markdown file across the 8 Telegram repositories grepped | Adds a file most tasks won't load |
| English body with a short Russian trigger line | Portable, while still activating for a large share of the Telegram developer community | Trigger coverage for other languages isn't tested |
| Security rules can't be waived | A competitor told agents not to warn about pasted secrets. Rule 4 handles tokens without lecturing and without ignoring risk. | Some users may find the rotation note unnecessary |

## Quality gate design

One validation core (`tg_lint.py`, standard library) reads a JSON capture format. Adapters replace only each framework's HTTP boundary, so real routers and handlers run: aiogram through a session, python-telegram-bot through a request class, and grammY through an API transformer. The Node gate calls the same Python core instead of duplicating its rules. Installing copies the core and one adapter into the project, so routine test runs check payloads without anyone remembering a command. MTProto references are separate files, so Bot API tasks do not load them.

## Context cost

| Layer | Loaded | Size |
|---|---|---|
| Name and description | Every session | 807-character description |
| `SKILL.md` body | On activation | About 2,400 tokens (estimate at 4 characters per token) |
| One reference | When its trigger applies | About 60–140 lines each |
| Scripts | Executed; source is not loaded unless needed | None |

A typical task loads `SKILL.md` and 2–3 references.
## Boundaries

In scope: developing, reviewing, and operating Telegram bots and Mini Apps. Out of scope: acting as a Telegram user, one-off message sending, simple alert wiring, and other messengers. MTProto is covered only for choosing when it is justified.

## Maintenance model

See `README.md`. In short: when a new Bot API release lands, update `platform-facts.md`, re-verify library statuses, run `pytest` and `tests/validate_skill.py`, and rerun evals whose behavior depends on what changed.
