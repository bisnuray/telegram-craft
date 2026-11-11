"""Idempotent ledger for Telegram Stars orders (standard library only).

Adapt the schema and move to the project's database. The invariants matter more
than the SQL:

- The server creates the order, then puts only its opaque id in the invoice.
- `pre_checkout` re-validates. It never grants anything.
- `record_payment` is keyed on `telegram_payment_charge_id`, so a redelivered
  update cannot pay twice.
- Delivery is a separate claimed step, so a crash can be retried and two
  workers cannot both deliver.
"""
from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL CHECK (status IN
        ('created', 'paid', 'delivering', 'delivered', 'refunded', 'cancelled')),
    charge_id TEXT UNIQUE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    claimed_at REAL
);
"""


class OrderRejected(Exception):
    """Carries a message safe to show in answerPreCheckoutQuery."""


@dataclass(frozen=True)
class PaymentResult:
    order_id: str
    newly_recorded: bool


class StarsLedger:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.executescript(SCHEMA)

    def create_order(
        self, user_id: int, sku: str, amount: int, ttl_seconds: int = 900, now: float | None = None
    ) -> str:
        """Return the id to pass as invoice payload (limit: 128 bytes)."""
        current = time.time() if now is None else now
        order_id = secrets.token_urlsafe(16)
        with self.conn:
            self.conn.execute(
                "INSERT INTO orders (id, user_id, sku, amount, status, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, 'created', ?, ?)",
                (order_id, user_id, sku, amount, current, current + ttl_seconds),
            )
        return order_id

    def pre_checkout(
        self, order_id: str, user_id: int, currency: str, amount: int, now: float | None = None
    ) -> None:
        """Validate; raise OrderRejected. Telegram requires an answer within 10 seconds."""
        current = time.time() if now is None else now
        row = self.conn.execute(
            "SELECT user_id, amount, status, expires_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if row is None or row[0] != user_id:
            raise OrderRejected("This order is not available. Start a new purchase.")
        if currency != "XTR" or amount != row[1]:
            raise OrderRejected("The price changed. Start a new purchase.")
        if row[2] != "created":
            raise OrderRejected("This order was already completed.")
        if current > row[3]:
            raise OrderRejected("This order expired. Start a new purchase.")

    def record_payment(
        self, order_id: str, user_id: int, charge_id: str, currency: str, amount: int
    ) -> PaymentResult:
        """Record money received. Safe to call again for the same update.

        A mismatch raises instead of granting: Telegram took the money, so
        send it to manual review or refund it. Do not drop it.
        """
        with self.conn:
            existing = self.conn.execute(
                "SELECT id FROM orders WHERE charge_id = ?", (charge_id,)
            ).fetchone()
            if existing is not None:
                return PaymentResult(order_id=existing[0], newly_recorded=False)

            row = self.conn.execute(
                "SELECT user_id, amount FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
            if row is None or row[0] != user_id or currency != "XTR" or amount != row[1]:
                raise ValueError(f"payment does not match order {order_id!r}; review or refund")

            updated = self.conn.execute(
                "UPDATE orders SET status = 'paid', charge_id = ?"
                " WHERE id = ? AND status IN ('created', 'cancelled')",
                (charge_id, order_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"order {order_id!r} was already paid by another charge; refund")
        return PaymentResult(order_id=order_id, newly_recorded=True)

    def claim_delivery(
        self, order_id: str, lease_seconds: int = 300, now: float | None = None
    ) -> bool:
        """Return True for exactly one worker until the lease lapses."""
        current = time.time() if now is None else now
        with self.conn:
            claimed = self.conn.execute(
                "UPDATE orders SET status = 'delivering', claimed_at = ?"
                " WHERE id = ? AND (status = 'paid'"
                " OR (status = 'delivering' AND claimed_at < ?))",
                (current, order_id, current - lease_seconds),
            )
        return claimed.rowcount == 1

    def mark_delivered(self, order_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE orders SET status = 'delivered' WHERE id = ? AND status = 'delivering'",
                (order_id,),
            )

    def mark_refunded(self, charge_id: str) -> bool:
        """Call after refundStarPayment succeeds. False if already refunded or unknown."""
        with self.conn:
            updated = self.conn.execute(
                "UPDATE orders SET status = 'refunded' WHERE charge_id = ? AND status != 'refunded'",
                (charge_id,),
            )
        return updated.rowcount == 1
