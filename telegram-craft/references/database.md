# Databases

Use when a project needs persistent storage: choosing a database, designing documents or tables, FSM storage, payments data, or media references. Verified against PyMongo 4.20, aiogram 3.31, and the MongoDB Node driver 7.9.

## Contents

- [Choose the database](#choose-the-database)
- [What goes where](#what-goes-where)
- [MongoDB in a Telegram project](#mongodb-in-a-telegram-project)
- [Payments and entitlements](#payments-and-entitlements)
- [Operations](#operations)

## Choose the database

**Existing project: keep its database.** Never migrate SQLite, PostgreSQL, or anything else to MongoDB as a side effect. A migration is its own task, with backups, a data check, and a rollback plan, done only when the owner asks.

**New project that needs persistent application data: MongoDB by default.** It fits typical bot data well (users, settings, subscriptions, orders, catalogs, activity) because each record is one document keyed by a Telegram id. Schemas evolve without migrations, and every write the bot needs is a single-document atomic update. Choose something else only when a requirement says so:

| Requirement | Choose |
|---|---|
| The user or the task names a database | That database |
| Money moves between users (wallets, balances, payouts, double-entry accounting), or reports join many entities | PostgreSQL. Multi-row transactions and constraints are the point |
| The owner explicitly wants local-only storage with no database server: a personal tool on their own machine, or they asked for SQLite | SQLite (WAL mode, busy timeout). Running as one process on a VPS is not such a case |
| The platform dictates it: Cloudflare Workers (D1), Supabase, Firebase | The platform's database |
| Temporary state, caches, rate limits, locks, queues | Redis, beside the primary database, never instead of it |

Say the choice in one sentence before building: "MongoDB, because the bot stores per-user settings and orders as documents; PostgreSQL would fit better if it needed balances moving between users." When the requirements make the choice genuinely uncertain and the user is reachable, ask once. When the task must finish autonomously, go with the default and note the alternative in the handoff. Do not ask again once the user has chosen.

A bot that only replies, or keeps nothing that must survive a restart, needs no database.

**No local server is not a reason to switch.** If MongoDB or PostgreSQL is the right choice but none is running where you work, still build for it:
- put integration tests behind `MONGODB_TEST_URI` or `DATABASE_URL`, so they run in CI or a local container and skip otherwise;
- test the pure logic without the server;
- say in the handoff which tests did not run.

Never ship SQLite because it was the only database you could start.

## What goes where

| Data | Store |
|---|---|
| Users, settings, subscriptions, orders, catalog, admin records, history | The primary database |
| FSM and conversation state | Memory in development; for production, the primary database (aiogram `PyMongoStorage`, grammY `@grammyjs/storage-mongodb`) or Redis when many instances share hot state. Keep the FSM state small and the business data in the primary database |
| MTProto `StringSession` | Secret configuration (`TELEGRAM_SESSION_STRING`), never an application document. Session rules: `mtproto-foundations.md` |
| Media | Telegram `file_id` for files the bot sends again; object storage (S3-compatible) or disk for files you must keep. Store only metadata and the reference in the database. GridFS only when nothing else exists and files are small and few |
| Idempotency keys (update ids, charge ids) | The primary database, with a unique index |

## MongoDB in a Telegram project

**Driver.**
- **Python:** PyMongo's async API, `AsyncMongoClient` (`pymongo>=4.13`). Motor is deprecated (May 2026, critical fixes only until May 2027); do not start new projects on it. In aiogram use `aiogram.fsm.storage.pymongo.PyMongoStorage`, not `MongoStorage`, which imports Motor.
- **TypeScript:** the official `mongodb` driver.
- Never call synchronous `MongoClient` from async handlers.

**Client lifecycle.** One client per process:
- create it at startup and close it on shutdown (`await client.close()`, in the dispatcher's shutdown hook or a `finally:`);
- inject it through the framework (aiogram workflow data, python-telegram-bot `bot_data`);
- never connect inside a handler.

The URI comes from `MONGODB_URI`, a secret. Set `serverSelectionTimeoutMS` and `timeoutMS` so a lost server fails fast instead of hanging a handler. `assets/mongo_store.py` has the shape.

**Documents.**
- Key users by their Telegram id: `{"_id": user_id}`. Python ints map to 64-bit integers, which fits Telegram ids.
- Embed what is read together and bounded (settings, a profile). Reference what grows without bound (orders, messages, history) in its own collection with the user id indexed.
- Keep one shape per collection, and add a `schema_version` field when a shape changes. Migrate lazily on read, or with a script.
- Use `$jsonSchema` validation on collections where bad data is costly (orders, payments).

**Indexes.** Create every index the queries need at startup with `create_indexes` (idempotent):
- a unique index on each natural key (`charge_id`, an update id, a username you look up);
- a compound index matching each frequent query and sort (`user_id, _id`).

An unindexed query on a growing collection is a defect.

**Writes.** Use atomic single-document operations instead of read-then-write:
- `find_one_and_update` with the expected state in the filter (`{"_id": id, "status": "paid"}`) for state transitions;
- `$set` with `upsert=True` for settings;
- `$inc` for counters;
- `DuplicateKeyError` from a unique index means "already done".

Multi-document transactions need a replica set (Atlas or a single-node replica set). Use them only when one change must touch several documents atomically.

**Reads.** Project only the fields you use. Paginate by range (`{"_id": {"$gt": last_id}}` with a sort and `limit`), not by `skip` on large collections. Never load a whole collection.

**Errors.**
- Handle `DuplicateKeyError` where it means a duplicate.
- Let `ServerSelectionTimeoutError` and other `ConnectionFailure` errors reach the error boundary, which logs them and tells the user to try again.
- Never swallow database errors (`code-quality.md`).

**Tests.** Run integration tests against a real `mongod`, such as a CI service container or a local container, using a throwaway database dropped after each test. In-memory mocks do not implement `AsyncMongoClient` or unique-index behavior faithfully.

## Payments and entitlements

The invariants are the same in any database (`payments.md`):
- the server creates the order;
- pre-checkout only validates;
- a payment is recorded once per `telegram_payment_charge_id` (unique);
- the entitlement changes atomically with that record;
- delivery is a claimed step that one worker wins;
- refunds are recorded once.

- **MongoDB:** `assets/mongo_store.py` (`MongoStarsLedger`). The order and its payment are one document, so every step is a single atomic update and needs no transaction.
- **SQL:** `assets/stars_ledger.py`, for SQLite or PostgreSQL projects.
- **Marketplaces where Stars move between buyer, seller, and platform balances:** PostgreSQL, or MongoDB transactions on a replica set with a durable append-only ledger collection. Do not update two balances with two separate writes.

## Operations

- **Hosting:** MongoDB Atlas (managed backups and a replica set), or a self-hosted replica set. Never expose `27017` publicly; require authentication and TLS.
- **Backups:**
  - use Atlas backups or `mongodump` on a schedule;
  - test a restore before launch;
  - keep at least one copy off the host.
- **Credentials:** a dedicated database user with read and write on the bot's database only. Rotate the user's password like any secret.
- **Several bot instances** share one MongoDB without extra work. Unique indexes and conditional updates keep them correct; in-process caches do not.
