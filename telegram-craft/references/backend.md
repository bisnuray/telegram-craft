# Backend architecture

Use for structure, data, state, background work, and operations. Size infrastructure (queues, Redis, extra processes) to the problem, but always organize the code.

## Project layout

Every new bot uses a package organized by role. A single file is acceptable only for a throwaway script under about 150 lines that the user asked for as one file.

```
mybot/                     # project root
  app/                     # the package (name it after the product)
    __main__.py            # wiring and startup only: config, clients, routers, run
    config.py              # typed settings from the environment, fail fast
    handlers/              # one module per feature: parse update, call service, render
      start.py
      settings.py
    keyboards/             # keyboard builders and callback_data schemas
    texts/                 # every user-visible string and screen renderer (texts/en.py)
    services/              # business rules and authorization, no Telegram types
    storage/               # database access and migrations
    workers/               # background jobs (media, broadcasts), if any
  tools/                   # one-off operator tools, e.g. login.py for an MTProto session
  tests/                   # mirrors app/: test_handlers_*, test_services_*
  var/                     # runtime data: sessions/, downloads/, db, logs (git-ignored)
  .env.example             # every variable with a comment, no real values
  .gitignore               # .env, var/, *.session, caches
  requirements.txt         # or pyproject.toml, with pinned framework versions
  README.md                # what it does, setup, BotFather/my.telegram.org steps, run, test
```

For grammY or Telegraf, use the same roles under `src/` (`src/handlers`, `src/keyboards`, `src/texts`, `src/services`, `src/storage`).

**Hybrid Bot API + MTProto, or a bot plus a user client:** keep each client in its own package and share only services and storage.

```
app/
  bot/            # control bot: handlers/, keyboards/, texts/
  userclient/     # MTProto client: client.py (start, reconnect), listeners/, relay/
  services/       # shared rules, used by both
  storage/
  __main__.py     # starts both clients under one supervisor
tools/login.py    # interactive session creation, never run by the service
```

Rules that hold at every size:

- **One responsibility per module.** Text and screen rendering live in `texts/`, buttons in `keyboards/`, update handling in `handlers/`. A module that mixes them gets split.
- **Split a module past about 300 lines.**
- **Dependencies point inward:** handlers call services; services do not import Telegram types, so business rules are testable without a bot.
- **Nothing runtime in the code tree.** Sessions, downloads, databases, and logs go under `var/` (or a configured path), never beside source files or in the project root.
- **Ship the setup files:** `.env.example`, `.gitignore`, a requirements file, and a README with the exact run and test commands.
- In an existing project, keep its layout; only move code when the user asks for a refactor.

Do not create the `Bot` or start polling at import time.

## Handlers

Handlers should validate, call a service, render, and return. Register more specific routers first, and end with fallbacks for unknown commands and callbacks. Handle wrong-content-type input inside a flow. Inject dependencies through the framework (aiogram workflow data or middleware, python-telegram-bot `bot_data`, grammY context), not module globals.

## Data

- **SQLite** suits one process with modest writes. Enable WAL mode and a busy timeout. **PostgreSQL** is for concurrent writers or several processes. Use a real async driver, and run blocking drivers off the event loop.
- Use migrations (Alembic or the stack's equivalent) once data matters.
- `chat_id` and `user_id` can exceed 32 bits. Use `BIGINT`.
- Handle concurrent transitions with conditional updates (`UPDATE ... WHERE status = 'pending'`) and unique constraints. A read-then-write in separate steps races under double taps.
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

`assets/update_delivery.py` implements these shapes with SQLite: an update inbox with leased claims, an outbox, 429 handling, per-chat lanes, and resumable broadcasts. `python3 assets/update_delivery.py --self-test` checks each guarantee against a deliberately broken variant. Copy the pieces the bot needs, not all of them: a small bot needs only idempotent handlers.

## Conversation state

| Store | Use |
|---|---|
| FSM memory | Single-process development |
| FSM on Redis or database | Production flows that should survive restarts |
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
