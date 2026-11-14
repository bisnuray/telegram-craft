# Hybrid Bot API and MTProto systems

Use when one product combines HTTP Bot API features with MTProto bot or user sessions. Read `mtproto-foundations.md` first. These are design patterns from the platform contracts. They have not been run against live Telegram.

## When hybrid is justified

Keep the Bot API for the user interface, and add MTProto for one named capability: large file transfer through a bot session, a raw method the Bot API lacks, or an authorized user-account function. If a local Bot API server solves the problem, prefer it, as it adds no MTProto code.

## Structure

```
Bot API process  ──┐                       ┌── MTProto worker (one per session)
(handlers, UI)     ├── queue + database ───┤   (uploads, raw calls)
Mini App backend ──┘                       └── status events back to the bot
```

- **Separate processes.** A flood wait or large transfer in the MTProto worker must not stall bot replies. Memory use also stays isolated.
- **Communicate through durable jobs**: job ID, requester, action, status, and attempt count. The bot enqueues and returns at once.
- **The worker reports status**, and the bot edits the user's status message. Keep one owner of user-facing text.
- **One writer per session.** Horizontal scaling means more sessions with a legitimate purpose, never spreading a limited workload across accounts to evade limits.

## Identity and IDs

A bot token used through HTTP and through MTProto is the same bot. Peer access differs, though. MTProto needs access hashes, while the Bot API uses plain IDs and uses the `-100` prefix for channels and supergroups. Convert explicitly, in one place. `file_id` values from the Bot API are not directly usable as MTProto file references, and the reverse. Store the file source for each, or transfer by message reference.

## Authorization

Authorize the human at the Bot API or Mini App layer, using `update.from.id` or validated init data, and again in the worker before it acts. The worker's user session must never be a way for bot users to invoke account actions they are not entitled to. Allowlist job types, and never accept a raw method name or arbitrary target from a user.

## Delivery rules

| Situation | Handling |
|---|---|
| Worker hits `FLOOD_WAIT` | Reschedule the job, and tell the user the delay if long |
| Worker hits `PEER_FLOOD` | Stop that job type, alert the operator |
| Session revoked | Mark the capability unavailable, and alert. The bot keeps working. |
| Bot API 429 | Handled in the bot process, independent of the worker |
| Job retried after crash | Idempotency key on the job and on any external effect |

The bot must keep working in degraded mode when MTProto is unavailable, and should say what is unavailable.

## Deployment

Give each component its own credentials and lifecycle:

- **Bot API process:** `BOT_TOKEN` only. It never reads a session.
- **User-account worker:** `TELEGRAM_SESSION_STRING`, `TELEGRAM_API_ID`, and `TELEGRAM_API_HASH`, loaded with `string_session_from_env()` and `connect_authorized()`. If it cannot start, it reports the capability as unavailable and the bot keeps working.
- **MTProto bot session (large files):** the same `BOT_TOKEN` with `start(bot_token=...)`, and its own session, never shared with a user account.

Each client is created, connected, and disconnected by its owner, and is testable alone with the other side faked. Only the worker can read sessions. Deploy workers stop-first. Monitor queue depth, job age, and flood wait totals. See `delivery.md` and `security.md` for the general rules.
