# Frameworks and APIs

Use when choosing or using a library. Versions were checked on 2026-11-08. Confirm with the package registry for new work, and preserve the existing stack unless there is a concrete reason to change it.

## API layers

| | Bot API | Mini Apps | MTProto |
|---|---|---|---|
| Identity | Bot token | Telegram user, proven by signed init data | User or bot session |
| Transport | HTTPS | Web page plus JS bridge | Binary protocol |
| Can | Everything bots are allowed | Rich UI inside Telegram | Client features, history |
| Cannot | Read chats it isn't in, or history before joining; download over 20 MB on the cloud server | Do anything server-side on its own | Be risk-free: user accounts can be limited or banned |
| Libraries | aiogram, PTB, grammY, Telegraf | `telegram-web-app.js`, `@tma.js/sdk` | Telethon, TDLib, Pyrogram forks |

A Telethon session is equal to full account access, so protect it like a password. Do not suggest user accounts for mass messaging, scraping others, or evading limits. For larger files, a local Bot API server is usually better than MTProto.

## Selection

| Situation | Default | Notes |
|---|---|---|
| New Python bot | aiogram 3 | 3.31.0 declares Bot API 10.3 |
| Existing PTB project | Stay on PTB | 22.8 declares 10.0. No rich or ephemeral methods; use `do_api_request` in one adapter. |
| New TypeScript bot | grammY | 1.46.0; plugin ecosystem; runs on serverless |
| Existing Telegraf project | Stay on Telegraf | 4.16.3; maintained but slower to add API |
| Mini App | Plain script for simple apps; `@tma.js/sdk` 3.x for larger ones | `@twa-dev/sdk` and `@telegram-apps/sdk` have no recent releases |
| Authorized user-account work, MTProto bots | Telethon 1.45 | See `mtproto-foundations.md`. Upstream Pyrogram's repository is archived. |

Migrate only if the current stack blocks a real requirement, and do it as a separate step.

## Checking the installed version

```bash
pip show aiogram; npm ls grammy
python -c "import aiogram; print(aiogram.__api_version__)"
python -c "import telegram; print(telegram.__bot_api_version__)"
grep -rl "send_rich_message" .venv/lib/python*/site-packages/aiogram | head -1
```

If the library lags, prefer a release that has the feature. Otherwise make a raw call through one small adapter.

## aiogram 3

- Use `Router` and `Dispatcher`; `aiogram.contrib`, `executor`, and `message_handler` are 2.x.
- Pass defaults with `Bot(token, default=DefaultBotProperties(parse_mode="HTML"))`.
- Test server: `AiohttpSession(api=aiogram.client.telegram.TEST)`.
- `start_polling(bot, allowed_updates=dp.resolve_used_update_types())`.
- `handle_as_tasks=True` has no concurrency cap unless `tasks_concurrency_limit` is set.
- Handler exceptions are logged and the update counts as processed. There is no retry.
- Exceptions: `TelegramRetryAfter`, `TelegramForbiddenError`, `TelegramBadRequest`, `TelegramMigrateToChat`, `TelegramNetworkError`, `TelegramServerError`.
- `safe_parse_webapp_init_data` checks the signature, not age. Use `assets/init_data.py` or add an `auth_date` check.
- There is no `aiogram.html` module. Use the standard library's `html.escape`.
- Dialog-heavy projects may already use `aiogram-dialog`; follow it if so.

## python-telegram-bot

- `ApplicationBuilder` and `async` handlers since v20. `Updater(use_context=True)` and `Filters` are older.
- Sequential by default; `concurrent_updates()` opts in.
- `helpers.escape_markdown` handles MarkdownV2. Use `html.escape` for HTML. There is no init data helper, so use `assets/init_data.py`.
- Persistence: `PicklePersistence` for small bots. Use a database for business state.
- Extras are optional installs, such as `python-telegram-bot[rate-limiter,webhooks,job-queue]`.
- Library file limits use decimal megabytes (`50_000_000`).

## grammY

- Use the context flavors pattern. `bot.catch` handles errors.
- `@grammyjs/runner` for concurrent long polling, with `sequentialize`.
- `webhookCallback(bot, adapter, { secretToken })` for webhooks.
- Plugins: `conversations`, `menu`, `session`, `auto-retry`, `transformer-throttler`, `i18n`, `parse-mode`.
- `conversations` replays the function on each update, so outside calls must go through `conversation.external`.
- Call `ctx.answerCallbackQuery()` on every callback path.

## Telegraf

Uses `ctx.answerCbQuery()`, `Scenes`, and `Telegraf.action`. Handlers time out after 90 seconds by default, unless `handlerTimeout` is changed.

## Telethon (only where MTProto is justified)

See `mtproto-foundations.md` and `mtproto-telethon.md` for full guidance.

Handle `FloodWaitError` by sleeping for `.seconds`. Keep session files out of Git, with restricted permissions.

## Mini App SDKs

The plain script exposes `window.Telegram.WebApp` and is enough for many apps. Check methods with `isVersionAtLeast`. `@tma.js/sdk` adds typed, feature-detected wrappers and init data parsing. Use its server package, or the bundled validators, on the backend. See `mini-apps.md`.
