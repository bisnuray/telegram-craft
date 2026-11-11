"""Update delivery that survives redelivery, crashes, 429s, and slow chats. Copy and adapt.

Standard library only (sqlite3, asyncio). Swap SQLite for your database; keep the shapes:

  UpdateInbox     write each update durably before acknowledging it; workers claim with a lease,
                  so a crashed worker's update is retried and a redelivered one is ignored
  Outbox          record a message in the same transaction as the state change; a worker sends it
  send_honoring_retry_after
                  on 429, wait exactly retry_after and retry the same call; never drop, never guess
  ChatLanes       one ordered lane per chat and a global concurrency cap, so a slow chat
                  delays only itself
  Broadcast       one row per recipient, so a restart resumes instead of messaging everyone twice

Money needs a domain key as well: one payment can arrive in two different updates. Use
`stars_ledger.py` (deduplicates on telegram_payment_charge_id), not update_id alone.

  python3 update_delivery.py --self-test

checks every guarantee against the correct code and against a deliberately broken variant, and
fails if a broken variant passes, so the checks are shown to detect the bug they target.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any


# Inbox ----------------------------------------------------------------------------------------------
class UpdateInbox:
    """Durable, deduplicated update intake with leased claims.

    Webhook: `receive()` and only then answer 200. Polling: `receive()` every update before
    confirming the offset. A worker loops `claim()` -> process -> `complete()`.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        conn.execute("CREATE TABLE IF NOT EXISTS update_inbox (update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, "
                     "state TEXT NOT NULL DEFAULT 'pending', lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0)")
        conn.commit()

    def receive(self, update_id: int, payload: str) -> bool:
        """True if new. A redelivery hits the primary key and changes nothing. Never SELECT then INSERT."""
        cursor = self.conn.execute("INSERT OR IGNORE INTO update_inbox (update_id, payload) VALUES (?, ?)", (update_id, payload))
        self.conn.commit()
        return cursor.rowcount == 1

    def claim(self, now: float | None = None, lease_seconds: float = 60.0) -> tuple[int, str] | None:
        """Take the oldest pending update, or one whose worker's lease ran out (that worker died)."""
        now = time.time() if now is None else now
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT update_id, payload FROM update_inbox WHERE state = 'pending' "
                                    "OR (state = 'claimed' AND lease_until < ?) ORDER BY update_id LIMIT 1", (now,)).fetchone()
            if row:
                self.conn.execute("UPDATE update_inbox SET state = 'claimed', lease_until = ?, attempts = attempts + 1 WHERE update_id = ?",
                                  (now + lease_seconds, row[0]))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return (row[0], row[1]) if row else None

    def complete(self, update_id: int) -> None:
        """Call only after the work, and its own writes, are committed."""
        self.conn.execute("UPDATE update_inbox SET state = 'done', lease_until = NULL WHERE update_id = ?", (update_id,))
        self.conn.commit()

    def pending_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM update_inbox WHERE state != 'done'").fetchone()[0]


# Outbox ---------------------------------------------------------------------------------------------
class Outbox:
    """Messages promised by a committed state change. Add inside the caller's transaction (no commit here)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        conn.execute("CREATE TABLE IF NOT EXISTS outbox (key TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, text TEXT NOT NULL, "
                     "sent INTEGER NOT NULL DEFAULT 0)")
        conn.commit()

    def add(self, key: str, chat_id: int, text: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO outbox (key, chat_id, text) VALUES (?, ?, ?)", (key, chat_id, text))

    def due(self, limit: int = 50) -> list[tuple[str, int, str]]:
        return self.conn.execute("SELECT key, chat_id, text FROM outbox WHERE sent = 0 ORDER BY rowid LIMIT ?", (limit,)).fetchall()

    def mark_sent(self, key: str) -> None:
        self.conn.execute("UPDATE outbox SET sent = 1 WHERE key = ?", (key,))
        self.conn.commit()


# 429 ------------------------------------------------------------------------------------------------
def retry_after_seconds(error: BaseException) -> float | None:
    """aiogram TelegramRetryAfter, python-telegram-bot RetryAfter (int or timedelta), or a raw 429 body."""
    value = getattr(error, "retry_after", None)
    if value is None:
        parameters = getattr(error, "parameters", None) or {}
        value = parameters.get("retry_after") if isinstance(parameters, dict) else getattr(parameters, "retry_after", None)
    if hasattr(value, "total_seconds"):
        value = value.total_seconds()
    return float(value) if isinstance(value, (int, float)) else None


async def send_honoring_retry_after(call: Callable[[], Awaitable[Any]], sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                                    max_wait: float = 300.0, max_attempts: int = 5) -> Any:
    """Retry the same call after exactly the server's wait. Longer than max_wait: raise, and reschedule the job."""
    for attempt in range(1, max_attempts + 1):
        try:
            return await call()
        except Exception as error:
            wait = retry_after_seconds(error)
            if wait is None or wait > max_wait or attempt == max_attempts:
                raise
            await sleep(wait)
    raise RuntimeError("unreachable")


# Per-chat lanes -------------------------------------------------------------------------------------
class ChatLanes:
    """Ordered per chat, concurrent across chats, capped overall. Feed it from the poller or the inbox worker."""

    def __init__(self, max_concurrent: int = 32) -> None:
        self._gate = asyncio.Semaphore(max_concurrent)
        self._queues: dict[int, asyncio.Queue] = {}
        self._workers: dict[int, asyncio.Task] = {}

    def submit(self, chat_id: int, job: Callable[[], Awaitable[Any]]) -> None:
        queue = self._queues.get(chat_id)
        if queue is None:
            queue = self._queues[chat_id] = asyncio.Queue()
            self._workers[chat_id] = asyncio.get_running_loop().create_task(self._run(queue))
        queue.put_nowait(job)

    async def _run(self, queue: asyncio.Queue) -> None:
        while True:
            job = await queue.get()
            try:
                async with self._gate:
                    await job()
            except Exception:  # one failed update must not stop the chat's lane; log it in real code
                pass
            finally:
                queue.task_done()

    async def drain(self) -> None:
        """Wait for queued work, for graceful shutdown. Stop feeding new updates first."""
        await asyncio.gather(*(queue.join() for queue in self._queues.values()))

    async def close(self) -> None:
        for task in self._workers.values():
            task.cancel()
        await asyncio.gather(*self._workers.values(), return_exceptions=True)


# Broadcast ------------------------------------------------------------------------------------------
class Broadcast:
    """Resumable campaign: one row per recipient. Pace sends to about 30 per second for free broadcasts."""

    def __init__(self, conn: sqlite3.Connection, campaign: str) -> None:
        self.conn, self.campaign = conn, campaign
        conn.execute("CREATE TABLE IF NOT EXISTS broadcast_recipient (campaign TEXT, chat_id INTEGER, status TEXT NOT NULL DEFAULT 'pending', "
                     "PRIMARY KEY (campaign, chat_id))")
        conn.commit()

    def add_recipients(self, chat_ids: list[int]) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO broadcast_recipient (campaign, chat_id) VALUES (?, ?)", [(self.campaign, c) for c in chat_ids])
        self.conn.commit()

    def next_batch(self, size: int = 30) -> list[int]:
        rows = self.conn.execute("SELECT chat_id FROM broadcast_recipient WHERE campaign = ? AND status = 'pending' ORDER BY chat_id LIMIT ?",
                                 (self.campaign, size)).fetchall()
        return [r[0] for r in rows]

    def mark(self, chat_id: int, status: str) -> None:
        """status: sent, blocked (403), or failed. Commit per recipient, so a crash loses at most one."""
        self.conn.execute("UPDATE broadcast_recipient SET status = ? WHERE campaign = ? AND chat_id = ?", (status, self.campaign, chat_id))
        self.conn.commit()


# Self-test ------------------------------------------------------------------------------------------
class Crash(Exception):
    """Stands in for a process dying at a chosen point."""


class _RetryAfter(Exception):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"Too Many Requests: retry after {seconds}")
        self.retry_after = seconds


def _db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


def check_redelivery_processed_once(inbox_cls) -> bool:
    inbox, done = inbox_cls(_db()), []

    def drain():
        while (item := inbox.claim(now=0)) is not None:
            done.append(item[0])
            inbox.complete(item[0])
    inbox.receive(1, "{}")
    inbox.receive(1, "{}")  # retried while still queued
    drain()
    inbox.receive(1, "{}")  # retried after it was handled: the acknowledgement was slow
    inbox.receive(2, "{}")
    drain()
    return done == [1, 2]


def check_crash_before_work_is_retried(inbox_cls) -> bool:
    inbox = inbox_cls(_db())
    inbox.receive(7, "{}")
    claimed = inbox.claim(now=0, lease_seconds=60)  # worker takes it, then the process dies
    retried = inbox.claim(now=61, lease_seconds=60)  # after the lease, another worker gets it
    return claimed is not None and retried is not None and retried[0] == 7


def check_live_lease_is_not_stolen(inbox_cls) -> bool:
    inbox = inbox_cls(_db())
    inbox.receive(8, "{}")
    inbox.claim(now=0, lease_seconds=60)
    return inbox.claim(now=30, lease_seconds=60) is None  # still owned by a live worker


def check_outbox_survives_crash_after_commit(use_outbox: bool) -> bool:
    conn, sent = _db(), []
    outbox = Outbox(conn)
    conn.execute("CREATE TABLE grants (user_id INTEGER PRIMARY KEY)")
    try:
        conn.execute("BEGIN")
        conn.execute("INSERT INTO grants VALUES (1)")
        if use_outbox:
            outbox.add("grant:1", 1, "Your access is active.")
            conn.commit()
            raise Crash  # dies before the sender runs
        sent.append("Your access is active.")  # broken: message first, commit later
        raise Crash
    except Crash:
        if conn.in_transaction:
            conn.rollback()
    for key, chat_id, text in outbox.due():  # restart: the sender worker drains the outbox
        sent.append(text)
        outbox.mark_sent(key)
    granted = conn.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 1
    return granted == bool(sent)  # a message is sent if and only if the grant committed


def check_payment_dedup_on_charge_id(key: str) -> bool:
    """One payment can reach the bot in two updates. Only the charge id identifies it."""
    conn = _db()
    conn.execute("CREATE TABLE grants (key TEXT PRIMARY KEY, credits INTEGER)")
    deliveries = [{"update_id": 10, "charge": "ch-1"}, {"update_id": 11, "charge": "ch-1"}]
    for event in deliveries:
        conn.execute("INSERT OR IGNORE INTO grants VALUES (?, 100)", (str(event[key]),))
    return conn.execute("SELECT SUM(credits) FROM grants").fetchone()[0] == 100


def check_retry_after(broken: bool) -> bool:
    sleeps, calls = [], []

    async def call():
        calls.append(1)
        if len(calls) == 1:
            raise _RetryAfter(7)
        return "ok"

    async def sleep(seconds):
        sleeps.append(seconds)

    async def broken_send():
        try:
            return await call()
        except _RetryAfter:
            await sleep(1)  # guessed backoff, then gives up
            return None

    result = asyncio.run(broken_send() if broken else send_honoring_retry_after(call, sleep))
    return result == "ok" and sleeps == [7] and len(calls) == 2


def check_slow_chat_does_not_block_others(lanes_cls) -> bool:
    async def scenario() -> bool:
        lanes, order, release = lanes_cls(max_concurrent=4), [], asyncio.Event()

        async def slow():
            await release.wait()
            order.append("A1")

        async def make(name):
            order.append(name)

        lanes.submit(1, slow)
        lanes.submit(1, lambda: make("A2"))
        lanes.submit(2, lambda: make("B1"))
        for _ in range(20):
            await asyncio.sleep(0)
        other_chat_served = order == ["B1"]
        release.set()
        await asyncio.wait_for(lanes.drain(), 2)
        await lanes.close()
        return other_chat_served and order == ["B1", "A1", "A2"]
    try:
        return asyncio.run(scenario())
    except asyncio.TimeoutError:
        return False


def check_concurrency_cap(lanes_cls) -> bool:
    async def scenario() -> bool:
        lanes, active, peak = lanes_cls(max_concurrent=2), [0], [0]

        async def job():
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.001)
            active[0] -= 1

        for chat in range(6):
            lanes.submit(chat, job)
        await asyncio.wait_for(lanes.drain(), 2)
        await lanes.close()
        return peak[0] <= 2
    return asyncio.run(scenario())


def check_broadcast_resumes(resume: bool) -> bool:
    conn, delivered = _db(), []
    job = Broadcast(conn, "news")
    job.add_recipients(list(range(1, 11)))
    for chat_id in job.next_batch(10)[:6]:  # crashes after six sends
        delivered.append(chat_id)
        job.mark(chat_id, "sent")
    if not resume:  # broken: restarts from the full list
        conn.execute("UPDATE broadcast_recipient SET status = 'pending'")
    restarted = Broadcast(conn, "news")
    while batch := restarted.next_batch(3):
        for chat_id in batch:
            delivered.append(chat_id)
            restarted.mark(chat_id, "sent")
    return sorted(delivered) == list(range(1, 11))


class _NoDedupInbox(UpdateInbox):
    def receive(self, update_id, payload):
        self.conn.execute("INSERT INTO update_inbox (update_id, payload) VALUES (?, ?) ON CONFLICT(update_id) DO UPDATE SET state = 'pending'", (update_id, payload))
        self.conn.commit()
        return True


class _DoneOnClaimInbox(UpdateInbox):
    def claim(self, now=None, lease_seconds=60.0):
        item = super().claim(now, lease_seconds)
        if item:
            self.complete(item[0])  # broken: marks done before the work happens
        return item


class _StealingInbox(UpdateInbox):
    def claim(self, now=None, lease_seconds=60.0):
        return super().claim(now=now, lease_seconds=0)  # broken: no lease, so any worker re-takes in-flight work


class _GlobalQueue(ChatLanes):
    def submit(self, chat_id, job):
        super().submit(0, job)  # broken: every chat shares one lane


class _UncappedLanes(ChatLanes):
    def __init__(self, max_concurrent=32):
        super().__init__(max_concurrent=10_000)


CHECKS: list[tuple[str, Callable[[], bool], Callable[[], bool]]] = [
    ("a redelivered update is processed once", lambda: check_redelivery_processed_once(UpdateInbox), lambda: check_redelivery_processed_once(_NoDedupInbox)),
    ("a crash after claiming is retried after the lease", lambda: check_crash_before_work_is_retried(UpdateInbox), lambda: check_crash_before_work_is_retried(_DoneOnClaimInbox)),
    ("a live worker's lease is not stolen", lambda: check_live_lease_is_not_stolen(UpdateInbox), lambda: check_live_lease_is_not_stolen(_StealingInbox)),
    ("a message is sent if and only if its state change committed", lambda: check_outbox_survives_crash_after_commit(True), lambda: check_outbox_survives_crash_after_commit(False)),
    ("one payment in two updates is granted once", lambda: check_payment_dedup_on_charge_id("charge"), lambda: check_payment_dedup_on_charge_id("update_id")),
    ("429 waits exactly retry_after and resends", lambda: check_retry_after(False), lambda: check_retry_after(True)),
    ("a slow chat delays only itself, in order", lambda: check_slow_chat_does_not_block_others(ChatLanes), lambda: check_slow_chat_does_not_block_others(_GlobalQueue)),
    ("the global concurrency cap holds", lambda: check_concurrency_cap(ChatLanes), lambda: check_concurrency_cap(_UncappedLanes)),
    ("a broadcast resumes without repeats", lambda: check_broadcast_resumes(True), lambda: check_broadcast_resumes(False)),
]


def self_test() -> int:
    failures = 0
    for name, correct, broken in CHECKS:
        good, caught = correct(), not broken()
        failures += not (good and caught)
        print(f"{'ok  ' if good and caught else 'FAIL'} {name}: correct {'passes' if good else 'FAILS'}, broken variant {'caught' if caught else 'NOT caught'}")
    print(f"{len(CHECKS) - failures}/{len(CHECKS)} guarantees verified")
    return 1 if failures else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
