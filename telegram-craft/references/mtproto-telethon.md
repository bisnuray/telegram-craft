# MTProto with Telethon

Use when writing or reviewing Telethon code. Read `mtproto-foundations.md` first for the authorization and session rules. Verified against Telethon 1.45.0. Copy helpers from `assets/mtproto_runtime.py`.

## Client setup

User account, the default runtime shape:

```python
import asyncio
import os
import sys

from telethon import TelegramClient

from app.mtproto_runtime import SessionUnavailable, connect_authorized, string_session_from_env


def make_client() -> TelegramClient:
    return TelegramClient(
        string_session_from_env(),
        int(os.environ["TELEGRAM_API_ID"]),
        os.environ["TELEGRAM_API_HASH"],
        flood_sleep_threshold=0,  # call_with_flood_control decides; a hidden sleep would stall the worker
        connection_retries=5,
        catch_up=False,
    )


async def run() -> None:
    client = make_client()
    await connect_authorized(client)
    try:
        register_handlers(client)
        await client.run_until_disconnected()
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except SessionUnavailable as error:
        sys.exit(f"Cannot start: {error}. Create a new session with create_session.py.")
```

- `flood_sleep_threshold`: the default of 60 silently sleeps inside a call, which can stall a whole worker. Set it deliberately.
- Do not use `async with client:` or `client.start()` for a user account at runtime. Both run `start()`, which prompts for a phone number when the session is not authorized.
- An `UnauthorizedError` (`AuthKeyUnregisteredError`, `SessionRevokedError`, `SessionExpiredError`, `UserDeactivatedError`) during the run is terminal: stop the client and exit with an alert, and do not retry or sign in again. `AuthKeyDuplicatedError` means two processes used one session; stop both and issue a new session.
- Rotation: create the new string with `create_session.py`, update the secret, restart, then end the old session under Settings > Devices.

**Bot session:** `await client.start(bot_token=os.environ["BOT_TOKEN"])`. A bot has no phone login, so `start(bot_token=...)` is safe; keep its `StringSession` or session file separate from any user session.

## Events

```python
from telethon import events

@client.on(events.NewMessage(pattern=r"^/status$", incoming=True))
async def status(event):
    if not recent.first_time((event.chat_id, event.id)):
        return
    if event.sender_id not in allowed_ids:
        return
    await event.respond("Queue is empty.")
```

- Handlers run concurrently by default. `sequential_updates=True` serializes, at the cost of throughput.
- A handler exception is logged and does not stop the client. Put business state in a database.
- `events.NewMessage` fires for your own outgoing messages unless `incoming=True`. A user-session handler without that filter can reply to itself in a loop.
- Treat message text and sender names as untrusted, as with any bot.

## Updates and recovery

Telegram orders updates using `pts`, `qts`, and `seq`, and clients fill gaps through `updates.getDifference` and `updates.getChannelDifference`. Telethon does this for you when `catch_up=True`, or when you call `await client.catch_up()`.

- `catch_up=True` replays what was missed while offline. Keep handlers idempotent with `RecentIds` or a database key.
- Decide per product whether to replay at all. A notifier usually should not replay yesterday's events.
- **`StringSession` and `MemorySession` keep update state only in memory**, so neither can catch up across a restart. If the product needs that, use `SQLiteSession` on an encrypted volume, or a custom `Session` that stores update state, and treat that store as a credential.
- Connection loss: `auto_reconnect` handles normal drops. Add a supervisor for exhausted retries, and treat authorization errors as terminal.

## Raw API methods

Prefer the high-level method, and use raw requests for what it lacks.

```python
from telethon import functions

full = await client(functions.channels.GetFullChannelRequest(channel="example"))
```

Generated classes reflect the installed library's layer. An `AttributeError` on `functions` means your layer lacks it. Upgrade instead of constructing bytes by hand. Check whether the method is user-only before using a bot session.

## Flood control

```python
from mtproto_runtime import FloodLimitExceeded, call_with_flood_control

try:
    await call_with_flood_control(lambda: client.send_message(chat, text), max_wait_seconds=120, on_wait=metric)
except FloodLimitExceeded as error:
    await queue.reschedule(job, delay=error.seconds)
```

- Always use the server's number, and never retry forever or shorten the wait.
- For long waits, return the job to a queue instead of holding a worker.
- `PeerFloodError` has no wait value and means stop. So do `UserPrivacyRestrictedError` and `ChatWriteForbiddenError`, for that target.
- A flood wait applies to that account and method family, so more concurrency does not help. Never spread load across accounts to get around limits. That is restriction evasion.
- Throttle up front. Use small, paced batches for reads like `iter_messages` with reasonable `wait_time`, and do not page more history than the feature needs.
- For a user exporting their own data in bulk, use `async with client.takeout(...) as takeout:`. Takeout is Telegram's sanctioned export path and waives some limits, and it requires the account owner's choice of what to export.

## Entities and peers

- Every user, chat, and channel call needs that peer's `access_hash`, which the account learns only by seeing the peer. `PEER_ID_INVALID` with an ID you stored usually means this session never met that peer, not that the ID is wrong.
- Persist the IDs and access hashes Telethon gives you, or keep a `SQLiteSession` entity cache, and reuse `InputPeer` objects. Resolve usernames once.
- `get_entity` on a username is a network call. Calling it in a loop is a common cause of unexplained flood waits.

## Media

```python
uploaded = await client.upload_file(path, part_size_kb=512, progress_callback=report)
await client.send_file(chat, uploaded, caption=caption)
async for chunk in client.iter_download(message.media, request_size=524288):
    sink.write(chunk)
```

- Apply the same safety as `media.md`: size limits, server-chosen names, temp cleanup, and bounded concurrency.
- Stream with `iter_download` for large files so that memory stays flat. Avoid `download_media(bytes)` for them.
- Optional `cryptg` speeds up encryption and is worthwhile for heavy transfer. It needs Python 3.11 or later in its current release.
- Throttle progress callbacks before editing a status message.
- Refetch the message on `FileReferenceExpiredError`. Do not cache media objects indefinitely.

## Permissions

Catch and map these to user-facing or operator outcomes: `ChatAdminRequiredError`, `ChatWriteForbiddenError`, `UserNotParticipantError`, `ChannelPrivateError`, and `BotMethodInvalidError` (a user-only method called from a bot). Entities need access hashes, so a bare numeric ID may fail until the client has seen that peer. Persist sessions, or resolve through a dialog or username.

## Several clients

- One client, one session, one event loop. Use `ClientRegistry` to refuse duplicate starts and to stop them in order.
- Limit how many connect at once. A restart storm looks like abuse.
- Each client holds memory and sockets. Measure before running many in a process.
- Use separate limits per account and keep logs per client ID, never the phone number.
- Stop with `await client.disconnect()` on SIGTERM, and do not `log_out()` on a normal shutdown, or the session is destroyed.

## Deployment and observability

- Run one instance per session. Use stop-first deploys so that old and new never overlap.
- Mount encrypted sessions read/write from a restricted volume, and inject the key separately.
- Log flood wait seconds per method, reconnects, authorization failures, and handler errors. Never log phone numbers, codes, 2FA passwords, session strings, or message bodies by default.
- Alert on authorization errors, repeated `PeerFloodError`, and growing update lag.
- Disable Telethon's debug logging in production, as it can include request contents.

## Testing with mocks

Never run tests against a real account. Mock the boundary.

```python
from unittest.mock import AsyncMock

client = TelegramClient(StringSession(), 1, "test-hash")
client.connect = AsyncMock()
client.is_user_authorized = AsyncMock(return_value=True)
client.send_message = AsyncMock()
```

Test bounded flood handling with the real `FloodWaitError(request=None, capture=5)`, with `sleep` injected. Also test duplicate-start refusal, terminal authorization errors, replay deduplication, and that session strings never reach logs. Use Telegram's [test servers](https://core.telegram.org/api/auth#test-accounts) only with dedicated test accounts. Mocks prove your logic, not server behavior, so label them L2.
