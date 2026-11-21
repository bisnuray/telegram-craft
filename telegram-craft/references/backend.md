# Backend architecture

Use for structure, data, state, background work, and operations. Size infrastructure (queues, Redis, extra processes) to the problem, but always organize the code.

## Project layout

Organize by role, at the size the product needs. A utility bot (one or two commands, no storage) is a small package:

```
splitbot/
  splitbot/
    __main__.py      # handlers and startup
    money.py         # the logic, testable without Telegram
  tests/
  .env.example  .gitignore  requirements.txt  README.md
```

A product bot (several flows, storage, payments, workers) uses the full layout below. Grow into it when the second flow or the storage arrives; do not create empty packages ahead of need. A single file is acceptable only for a throwaway script the user asked for as one file.

```
notes-bot/                 # project root, named after the bot
  notes_bot/               # the package: the bot's name in snake_case
    __main__.py            # wiring and startup only: config, clients, routers, run
    config.py              # typed settings from the environment, fail fast
    handlers/              # one module per feature: parse update, call service, render
      start.py
      settings.py
    keyboards/             # keyboard builders and callback_data schemas
    screens/               # every user-visible message: wording and rich layout, one function per screen
    services/              # business rules and authorization, no Telegram types
    database/              # database client, indexes, and queries
    workers/               # background jobs (media, broadcasts), only if any
    middlewares/           # aiogram middlewares (throttling, injection), only if any
  tools/                   # one-off operator tools, e.g. create_session.py for an MTProto session
  tests/                   # mirrors the package: test_handlers_*, test_services_*
  .env.example             # every variable with a comment, no real values
  .gitignore               # .env, data/, *.session, caches
  requirements.txt         # or pyproject.toml, with pinned framework versions
  README.md                # what it does, setup, BotFather/my.telegram.org steps, run, test
```

Name the package after the bot in lowercase snake_case (`notes_bot`, `shop_bot`, `price_alerts`) and run it with `python -m notes_bot`. Never use a generic name such as `app`, `bot`, `src`, `main`, or `telegram_bot`: `bot` also collides with the `Bot` object every handler receives. A multi-language bot keeps its translated strings in `locales/`, and `screens/` reads from them.

For grammY or Telegraf, use the same roles under `src/` (`src/handlers`, `src/keyboards`, `src/screens`, `src/services`, `src/database`).

**Hybrid Bot API + MTProto, or a bot plus a user client:** keep each client in its own package and share only services and the database.

```
watch_relay/
  control_bot/    # control bot: handlers/, keyboards/, screens/
  user_client/    # MTProto client: client.py (start, reconnect), listeners/, relay/
  services/       # shared rules, used by both
  database/
  __main__.py     # starts both clients under one supervisor
tools/create_session.py  # one-time sign-in from assets/create_session.py, never run by the service
```

Register handlers so they stay testable and the router stays fresh for each dispatcher (aiogram refuses to attach one `Router` to two dispatchers, and tests build several):

```python
# notes_bot/handlers/notes.py
async def show_note(callback: CallbackQuery, callback_data: NoteAction, store: NoteStore) -> None:
    ...


def build_router() -> Router:
    router = Router(name="notes")
    router.callback_query.register(show_note, NoteAction.filter(F.action == "show"))
    return router
```

Handler functions live at module level, one feature per module. `build_router()` only registers them. Never define handlers inside a builder function: that turns a feature into one long closure that cannot be imported or tested alone.

Rules that hold at every size:

- **One responsibility per module.** Message wording and screen rendering live in `screens/`, buttons in `keyboards/`, update handling in `handlers/`. A module that mixes them gets split.
- **Split a module past about 300 lines.**
- **Dependencies point inward:** handlers call services; services do not import Telegram types, so business rules are testable without a bot.
- **No runtime files in the project.** Logs go to stdout, where systemd or Docker collects them. Application data goes to the database, the MTProto session to `TELEGRAM_SESSION_STRING`, media the bot sends again to its `file_id`, and files being processed to `tempfile.TemporaryDirectory()`. Create a `data/` directory only when the bot must keep files on its own disk (downloads it keeps, a SQLite file, a file session): read its path from `DATA_DIR` (default `./data`) and git-ignore it.
- **Ship the setup files:** `.env.example`, `.gitignore`, a requirements file, and a README with the exact run and test commands.
- In an existing project, keep its layout; only move code when the user asks for a refactor.

Do not create the `Bot` or start polling at import time.

## Handlers

Handlers should validate, call a service, render, and return. Register more specific routers first, and end with fallbacks for unknown commands and callbacks. Handle wrong-content-type input inside a flow. Inject dependencies through the framework (aiogram workflow data or middleware, python-telegram-bot `bot_data`, grammY context), not module globals.

## Data

- **Which database:** keep an existing project's database. A new project that needs persistent data uses **MongoDB** by default, with PyMongo's `AsyncMongoClient`. Use **PostgreSQL** when money moves between users or the data is strongly relational, **SQLite** only when the owner wants local-only, single-process storage, and **Redis** for temporary state beside the primary database. Selection rules, document design, indexes, and MongoDB practice: `database.md`.
- **SQLite**, when chosen: enable WAL mode and a busy timeout, one writing process. **PostgreSQL**: a real async driver (asyncpg, psycopg 3). Run any blocking driver off the event loop.
- Use migrations once data matters: Alembic or the stack's equivalent for SQL, versioned documents and scripts for MongoDB.
- `chat_id` and `user_id` can exceed 32 bits: `BIGINT` in SQL; MongoDB stores Python ints as 64-bit.
- Handle concurrent transitions with conditional updates (`UPDATE ... WHERE status = 'pending'`, or `find_one_and_update` with the status in the filter) and unique constraints or indexes. A read-then-write in separate steps races under double taps.
- Keep transactions short, and do not hold one across a Telegram call or other network I/O.

## Update idempotency

Delivery is at-least-once: webhook retries and restarts redeliver. Choose a level per effect:

| Effect | Protection |
|---|---|
| Read-only reply | None needed |
| Idempotent state change | Conditional update |
| Non-repeatable effect such as money, external API, or job creation | Dedupe on a domain key, in the same transaction as the change |
| High-value or must-not-lose work | Inbox table written before acknowledging, processed by a worker |

`update_id` identifies redelivery, but it is not a clock: after a week without updates the next one is chosen at random. A domain key such as `telegram_payment_charge_id` is stronger, because one business event can arrive in different updates.

Telegram and your database are not atomic. To guarantee a send after commit, write an outbox row in the transaction and have a worker send it, accepting a possible duplicate after a crash.

`assets/update_delivery.py` implements these shapes with SQLite so its self-test needs no server; port the same logic to the project's database: an update inbox with leased claims, an outbox, 429 handling, per-chat lanes, and resumable broadcasts. `python3 assets/update_delivery.py --self-test` checks each guarantee against a deliberately broken variant. Copy the pieces the bot needs, not all of them: a small bot needs only idempotent handlers.

## Conversation state

| Store | Use |
|---|---|
| FSM memory | Single-process development |
| FSM on the primary database or Redis (aiogram `PyMongoStorage` or `RedisStorage`; never `MongoStorage`, which needs the deprecated Motor) | Production flows that should survive restarts |
| Your database | Anything of business value |

Define timeouts for abandoned flows. In groups, pick the state key deliberately: aiogram's default `USER_IN_CHAT` is usually right. Clearing FSM state does not remove old keyboards.

Serialize per user when ordering matters: aiogram `events_isolation`, or grammY's `sequentialize` from the runner. With aiogram polling, `handle_as_tasks=True` runs updates concurrently without a limit by default. Set `tasks_concurrency_limit`. python-telegram-bot is sequential unless `concurrent_updates` is set.

## Slow work

If it takes over a second or two, it does not belong inline.

| Need | Use |
|---|---|
| Light tasks that may be lost on restart | `asyncio.create_task`, retain a reference, bound with a semaphore |
| CPU-heavy work | `asyncio.to_thread` or a process pool, or a subprocess |
| Must survive restarts, or several workers | Persistent queue: arq, Celery, RQ, BullMQ, or a database table with `FOR UPDATE SKIP LOCKED` |

Jobs need a status, an owner, retries with a cap, a timeout, and a stale-claim sweep. Workers re-check that the job is still wanted before delivering, and a late result must not overwrite newer navigation.

## Errors and retries

Register a global error handler that logs with context and tells the user something when a reply is possible.

| Failure | Action |
|---|---|
| 429 | Wait `retry_after`, then retry |
| Network timeout, 5xx | Retry with capped exponential backoff and jitter. A timed-out send may have been delivered. |
| 403 `bot was blocked` / `user is deactivated` | Mark the user inactive and stop sending |
| 400 `chat not found`, `message is not modified`, parse errors | Not retryable. Handle or fix. |
| `migrate_to_chat_id` | Group became a supergroup; update the stored ID and resend |
| Unknown | Bounded retry, then alert |

Match error descriptions by substring.

## Configuration

Use typed settings loaded from the environment, and fail at startup with a clear message if required values are missing, without printing them. Commit `.env.example` and git-ignore `.env`. Pin dependencies with a lockfile.

## Logging and observability

Use structured logs with `update_id`, a hashed or numeric user ID, handler name, and duration. Never log tokens, Bot API URLs, payment details, or full message bodies by default. Lower the HTTP client's logger level so that request URLs with tokens are not written.

Track update lag, handler errors, 429 count, queue depth, job failure rate, and payment mismatches. For a small bot, an error alert to an admin chat may be sufficient.

## Graceful shutdown

On SIGTERM: stop receiving updates, finish or requeue in-flight work within a deadline, flush outgoing queues, and close HTTP sessions and database pools. aiogram handles signals in `start_polling`, and cleanup can go in `dp.shutdown.register`. Long jobs must be resumable, because a deadline will sometimes pass. Kill and reap subprocesses.
