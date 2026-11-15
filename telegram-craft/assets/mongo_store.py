"""MongoDB storage for a Telegram bot with PyMongo's async API (pymongo>=4.13, AsyncMongoClient).

Copy and adapt. One client per process, created at startup and closed at shutdown:

    client = connect()                      # reads MONGODB_URI
    db = client.get_default_database()      # the database named in the URI
    await ensure_indexes(db)
    users, ledger = UserSettings(db), MongoStarsLedger(db)
    ...
    await client.close()

Every write below is a single-document atomic operation, so none needs a replica set or a
transaction. Order invariants match stars_ledger.py: the server creates the order, pre-checkout
only validates, a payment is recorded once per telegram_payment_charge_id, and delivery is a
claimed step that one worker wins.
"""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from pymongo import ASCENDING, AsyncMongoClient, IndexModel, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

ORDER_STATUSES = ("created", "paid", "delivering", "delivered", "refunded", "cancelled")


def connect(uri: str | None = None) -> AsyncMongoClient:
    """Create the process-wide client. It connects lazily; the first operation fails fast if the server is unreachable."""
    return AsyncMongoClient(
        uri or os.environ["MONGODB_URI"],
        appname="telegram-bot",
        serverSelectionTimeoutMS=5_000,
        timeoutMS=10_000,  # client-side limit for every operation, retries included
        tz_aware=True,
    )


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Idempotent; run at startup. Unique indexes are what make redelivered updates harmless."""
    await db.orders.create_indexes([
        IndexModel([("charge_id", ASCENDING)], unique=True, partialFilterExpression={"charge_id": {"$type": "string"}}),
        IndexModel([("user_id", ASCENDING), ("_id", ASCENDING)]),
    ])


class UserSettings:
    """Per-user preferences, one document per Telegram user id."""

    def __init__(self, db: AsyncDatabase) -> None:
        self.users = db.users

    async def get(self, user_id: int) -> dict[str, Any]:
        document = await self.users.find_one({"_id": user_id}, {"settings": 1})
        return (document or {}).get("settings", {})

    async def update(self, user_id: int, **changes: Any) -> dict[str, Any]:
        """Set only the given keys, creating the user on first use."""
        document = await self.users.find_one_and_update(
            {"_id": user_id},
            {"$set": {f"settings.{key}": value for key, value in changes.items()},
             "$setOnInsert": {"created_at": time.time()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return document["settings"]


class OrderRejected(Exception):
    """Carries a message safe to show in answerPreCheckoutQuery."""


@dataclass(frozen=True)
class PaymentResult:
    order_id: str
    newly_recorded: bool


class MongoStarsLedger:
    def __init__(self, db: AsyncDatabase) -> None:
        self.orders = db.orders

    async def create_order(self, user_id: int, sku: str, amount: int, ttl_seconds: int = 900) -> str:
        """Return the id to pass as invoice payload (limit: 128 bytes)."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        order_id, now = secrets.token_urlsafe(16), time.time()
        await self.orders.insert_one({"_id": order_id, "user_id": user_id, "sku": sku, "amount": amount,
                                      "status": "created", "created_at": now, "expires_at": now + ttl_seconds})
        return order_id

    async def pre_checkout(self, order_id: str, user_id: int, currency: str, amount: int) -> None:
        """Validate; raise OrderRejected. Telegram requires an answer within 10 seconds."""
        order = await self.orders.find_one({"_id": order_id})
        if order is None or order["user_id"] != user_id:
            raise OrderRejected("This order is not available. Start a new purchase.")
        if currency != "XTR" or amount != order["amount"]:
            raise OrderRejected("The price changed. Start a new purchase.")
        if order["status"] != "created":
            raise OrderRejected("This order was already completed.")
        if time.time() > order["expires_at"]:
            raise OrderRejected("This order expired. Start a new purchase.")

    async def record_payment(self, order_id: str, user_id: int, charge_id: str, currency: str, amount: int) -> PaymentResult:
        """Record money received. Safe to call again for the same update.

        A mismatch raises instead of granting: Telegram took the money, so send it
        to manual review or refund it. Do not drop it.
        """
        if (existing := await self.orders.find_one({"charge_id": charge_id}, {"_id": 1})) is not None:
            return PaymentResult(existing["_id"], newly_recorded=False)
        if currency != "XTR":
            raise ValueError(f"payment for order {order_id!r} is not in Stars; review or refund")
        try:
            paid = await self.orders.find_one_and_update(
                {"_id": order_id, "user_id": user_id, "amount": amount, "status": {"$in": ["created", "cancelled"]}},
                {"$set": {"status": "paid", "charge_id": charge_id, "paid_at": time.time()}},
            )
        except DuplicateKeyError:
            # A concurrent delivery of the same update recorded it first.
            existing = await self.orders.find_one({"charge_id": charge_id}, {"_id": 1})
            return PaymentResult(existing["_id"], newly_recorded=False)
        if paid is None:
            if (existing := await self.orders.find_one({"charge_id": charge_id}, {"_id": 1})) is not None:
                return PaymentResult(existing["_id"], newly_recorded=False)
            raise ValueError(f"payment does not match order {order_id!r}, or it was paid by another charge; review or refund")
        return PaymentResult(order_id, newly_recorded=True)

    async def claim_delivery(self, order_id: str, lease_seconds: int = 300) -> bool:
        """Return True for exactly one worker until the lease lapses."""
        now = time.time()
        claimed = await self.orders.find_one_and_update(
            {"_id": order_id, "$or": [{"status": "paid"}, {"status": "delivering", "claimed_at": {"$lt": now - lease_seconds}}]},
            {"$set": {"status": "delivering", "claimed_at": now}},
        )
        return claimed is not None

    async def mark_delivered(self, order_id: str) -> None:
        await self.orders.update_one({"_id": order_id, "status": "delivering"}, {"$set": {"status": "delivered"}})

    async def mark_refunded(self, charge_id: str) -> bool:
        """Call after refundStarPayment succeeds. False if already refunded or unknown."""
        result = await self.orders.update_one({"charge_id": charge_id, "status": {"$ne": "refunded"}},
                                              {"$set": {"status": "refunded", "refunded_at": time.time()}})
        return result.modified_count == 1

    async def orders_for(self, user_id: int, after: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """One page of a user's orders, using the (user_id, _id) index; pass the last _id as `after`."""
        query: dict[str, Any] = {"user_id": user_id}
        if after is not None:
            query["_id"] = {"$gt": after}
        return await self.orders.find(query).sort("_id", ASCENDING).limit(limit).to_list()
