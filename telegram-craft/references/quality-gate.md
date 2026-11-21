# Automatic message and keyboard checks

Use when adding or running automated checks on a bot's messages and keyboards, or when `.tg-lint` output appears. Install it once, and every later test run checks real outgoing payloads with no separate screen file to maintain.

## Install

```bash
python3 scripts/install_quality_gate.py PROJECT --framework aiogram   # or ptb, grammy
```

It copies the validation core and adapter, and enables the test integration. It adds a CI workflow only with `--with-ci` or when `.github/workflows` already exists, and a pre-commit hook only when `.pre-commit-config.yaml` already exists. Each run overwrites `.tg-lint/capture.json` and `report.json`, so the folder never grows. It keeps existing files unless `--force` is given, and installs nothing if the project already has a gate elsewhere; reuse that one. `--with-example` adds a working example bot and tests.

Run the tests with `TG_LINT_REQUIRE_INTERACTIONS=1` before you report. The output ends with a `Telegram quality gate` section. Quote its coverage line (`N interactions, ...; pressed X/Y offered button routes`) in the handoff. If it reports errors, fix the bot, not the gate.

## Write journeys, not fixtures

The adapter replaces only the HTTP layer, so real routers, filters, and handlers run.

```python
def test_catalog(tg_recorder):
    bot = AiogramHarness(build_dispatcher(), tg_recorder)
    async def journey():
        with bot.scenario("catalog"):
            await bot.command("/start")
            await bot.press("Browse catalog")   # fails if the button is not on screen
            await bot.callback("item:99:0")     # stale or forged data
    asyncio.run(journey())
```

Bound every wait in a journey, for example `await asyncio.wait_for(started.wait(), 2)`. An unbounded wait turns a broken payload into a hung test run, and the gate cannot report on a run that never ends.

The harness API, complete. Use it from this list; do not read the vendored `tg_quality` source.

```python
AiogramHarness(dispatcher, tg_recorder, default=None, workflow_data=None, user_id=1000, chat_id=None, chat_type="private")
PTBHarness(register, tg_recorder, user_id=1000, ...)  # register(app) adds the handlers
# workflow_data reaches handlers as keyword arguments: workflow_data={"store": store}
with bot.scenario("name"): ...                      # groups a journey in the report
await bot.command("/start", expected_silence=False, expected_error=False)
await bot.text("hello", expected_silence=False, expected_error=False)
await bot.press("Label")                            # fails if no button with that label is on screen
await bot.callback("data", expected_error=False, user_id=None)   # raw or forged callback_data
await bot.media("photo", attachment_dict, caption=None)
await bot.pre_checkout(payload, total, currency="XTR")
await bot.successful_payment(payload, total, charge_id="charge-1", currency="XTR")
await bot.raw_update(update_dict, kind="update")
bot.fail_next(method, description, error_code=400, retry_after=None)  # next call to method fails
bot.respond(method, result)                         # custom result for method
bot.sent("sendMessage") -> list[dict]               # params of each call
bot.last_text -> str | None                         # last text the bot sent
bot.labels -> list[str]                             # buttons on the current keyboard
```

The simulated user is id `1000`; the bot is id `999`. grammY uses the same names in camelCase. Install the gate from `tg_quality.mjs` with `installLintGate(recorder)`.

The Node gate needs Python 3 on the path, because all three frameworks share one validation core.

## What fails, and what does not

**Errors fail the run.** Examples: text over limits, invalid HTML or MarkdownV2, empty labels, `callback_data` over 64 bytes, invalid keyboard structures, reply-keyboard misuse, Mini App buttons without HTTPS or outside private chats, invalid Stars invoices, rich messages without exactly one of `html`, `markdown`, `blocks` or over 32,768 characters, rich HTML that Telegram would reject (an unsupported tag such as `<thead>` or `<span>`, wrong nesting such as `<td>` outside `<tr>`, unclosed tags, named entities other than the 13 allowed, bad `tg-time` or button attributes, `tg://` media missing from `media`, more than 500 blocks, 50 media, 16 levels, or 20 columns, `<tg-thinking>` outside drafts), unanswered callbacks, and handler exceptions. Rich screens (`sendRichMessage`, and `editMessageText` with `rich_message`) get the same keyboard checks and coverage as text screens, including `<tg-button>` callbacks inside the content.

**Warnings are reported only.** Examples: emoji overload, decorative separators, weak hierarchy, generic labels, repeated wording, callbacks that stack new menus, and the rich style warnings (`rich-emoji`, `rich-table-unbordered`, `rich-empty-cell`, `rich-repeats-keyboard`, `rich-divider`, `rich-busy`, `rich-parse-mode`). Use judgment.

To tighten it, use `TG_LINT_STRICT=1` and `TG_LINT_MIN_BUTTON_COVERAGE=0.8`. `TG_LINT_REQUIRE_INTERACTIONS=1`, set in the CI template, fails a run that captured nothing.

## Reading the coverage section

`pressed 8/8 offered button routes` counts callback patterns that appeared on captured keyboards and were pressed. Digits are grouped, so `open:12` and `open:13` count as one route. Full button coverage only means every button that *appeared* was pressed. A screen that never appeared is not counted.

The next lines separate what is known from what is guessed:

- **`coverage gap:` (confirmed).** Either of two cases:
  - A handler registered with aiogram or python-telegram-bot, including `ConversationHandler` states, never ran.
  - A route the bot's source builds was only ever sent with `bot.callback(...)`; no captured screen offered it. That usually means the test never reached the screen, often because the test user was refused.

  Stale or forged data stays legitimate: `product:abc` beside a shown `product:12`, or junk the bot never builds, is listed as information, not as a gap.
- **`possible gap (static, unverified):`** `callback_data` that the source builds but no captured keyboard showed, or that is built from a variable. The scan reads literals, f-string prefixes, grammY `.text(label, data)`, and aiogram `CallbackData` prefixes. It may point at dead code.
- grammY has no handler inspection, and the report says so.

Close each confirmed gap on a screen you changed: drive the journey to that screen with `press`, as a user allowed to see it. A handler that ran may have taken only its refusal branch, so check which reply came back. Explain any gap you leave. `TG_LINT_REQUIRE_COVERAGE=1` fails the run on confirmed gaps; static findings never fail it. `report.json` lists each interaction path: trigger, handlers run, buttons offered.

A clean run does not prove navigation is correct, or how a message looks in a client. Report it as L2 evidence.

When a warning fires on purpose, or a screen needs review, read `messages.md` or `keyboards.md`.
