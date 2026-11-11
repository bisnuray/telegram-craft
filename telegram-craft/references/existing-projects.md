# Working in existing projects

Use for inspecting, debugging, redesigning, or refactoring existing code. Working behavior is the asset to protect.

## Inspect first

1. Read `README`, `AGENTS.md`, `CLAUDE.md`, and any docs on deployment.
2. Find the stack and versions: `requirements*`, `pyproject.toml`, `package.json`, lockfiles. Note the Bot API version the installed library supports.
3. Map entry points: startup, routers in registration order, middleware, webhook or polling.
4. Inventory interfaces that must not break: commands, `callback_data` formats, deep links, database schema, environment variables, locale keys, and scheduled jobs.
5. Run the existing tests and linters to get a baseline, and run `scripts/tg_audit.py .` for leads.

Do not run a bot with a production token. Use a test bot, or fake transport.

## Compatibility rules

| Asset | Why it matters |
|---|---|
| `callback_data` format | Old keyboards remain in chats forever. Keep parsing the old format, or add a migration handler that re-renders. |
| Deep links | They're in posts, ads, and QR codes |
| Commands | In users' habits and client menus |
| Database | Change with forward migrations, and don't drop columns during a refactor |
| Locale keys and placeholders | Update every language, or flag those that need translation |
| Business logic | Prices, limits, and rules stay exact |

Follow the project's naming, layout, and helpers. Do not rewrite in another framework, reformat unrelated files, or "tidy" alongside a fix.

## Debugging

Reproduce before fixing, ideally in a failing test. Then trace update → router → filter → handler → service → API call.

| Symptom | Likely causes |
|---|---|
| Button spins forever | Callback not answered on some path; exception before the answer; handler didn't match |
| Button does nothing | Filter or prefix mismatch; router registered after a catch-all; callback data format changed; `callback_query` absent from `allowed_updates`; a stale process is consuming updates |
| `message is not modified` | Same content rendered twice; harmless, catch it |
| `can't parse entities` | Unescaped dynamic text; a reserved MarkdownV2 character |
| `query is too old` | Slow work before the answer; answer first |
| `BUTTON_DATA_INVALID` | `callback_data` over 64 bytes or empty |
| 409 Conflict | Two pollers, or a poller with a webhook set |
| Bot silent in groups | Privacy mode; bot needs re-adding after a change |
| Handler only sometimes runs | An earlier router consumes it; FSM state filter; a middleware exception |
| Works, then stops after a while | Blocked event loop; unbounded task growth; memory leak; DB locked |
| Webhook not arriving | `getWebhookInfo.last_error_message`; TLS; port; secret mismatch |
| Duplicate actions | Redelivery; double tap; two instances; no conditional update |
| FSM lost on deploy | `MemoryStorage` |

For a broken callback, log the raw `callback_data` and which handler matched. Then fix the cause at the routing or data level, and add a test that sends that exact `callback_data` through the dispatcher. Also confirm that every path answers.

## Redesigning the interface

Change text and layout only:

1. List all screens, keyboards, callback data, and transitions.
2. Rewrite text in the catalog, keeping every fact and placeholder.
3. Reorganize buttons, leaving their `callback_data` unchanged unless asked.
4. If a new navigation path is needed, add a new callback rather than repurposing an old one.
5. Lint the screens and render them to check.

## Refactoring without changing behavior

1. **Characterize**: if tests are missing, write tests that record current behavior through the dispatcher with fake transport. Include the odd cases. Keep them passing unchanged throughout.
2. **Move in small steps**: extract one thing at a time (texts, keyboards, services, repositories).
3. **Don't mix** a bug fix and a move. If you find a bug, record it, and fix it separately or report it.
4. Keep public entry points working during the move: same run command and environment variables unless the task includes changing them.
5. Compare the outgoing API calls before and after for the same updates. That's the strongest cheap proof that behavior is unchanged.

```python
# characterization: record what the bot sends for a fixed update
async def test_buy_flow_unchanged(dp, bot, fake_session):
    await dp.feed_update(bot, make_callback("v1:buy:7", user_id=1))
    assert fake_session.calls == EXPECTED_CALLS
```

Report any behavior you deliberately left alone, and any defects found along the way.

## Migrating libraries

Only when requested or truly blocked: list handlers, port one feature at a time, and keep callback formats. For aiogram 2→3 or PTB 13→20+, expect structural changes (routers, async, filters). Treat it as a project of its own.
