"""assets/mongo_store.py against a real MongoDB. Set MONGODB_TEST_URI (CI runs a mongo service); otherwise skipped."""
import ast
import asyncio
import importlib.util
import os
import sys
import time
import uuid

import pytest
import pytest_asyncio
from test_quality_gate import SKILL

URI = os.environ.get("MONGODB_TEST_URI")
SOURCE = (SKILL / "assets/mongo_store.py").read_text()


def load_store():
    if "mongo_store" not in sys.modules:
        spec = importlib.util.spec_from_file_location("mongo_store", SKILL / "assets/mongo_store.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["mongo_store"] = module  # dataclasses resolve their module through sys.modules
        spec.loader.exec_module(module)
    return sys.modules["mongo_store"]


def test_uses_the_maintained_async_driver_with_timeouts():
    imports = {n.module for n in ast.walk(ast.parse(SOURCE)) if isinstance(n, ast.ImportFrom)}
    assert "motor" not in " ".join(filter(None, imports)) and "motor" not in SOURCE.split('"""', 2)[2]
    assert "AsyncMongoClient" in SOURCE
    assert "serverSelectionTimeoutMS" in SOURCE and "timeoutMS" in SOURCE


needs_mongo = pytest.mark.skipif(URI is None, reason="set MONGODB_TEST_URI to run MongoDB integration tests")


@pytest_asyncio.fixture
async def db():
    store = load_store()
    client = store.connect(URI)
    database = client[f"tgcraft_test_{uuid.uuid4().hex[:10]}"]
    await store.ensure_indexes(database)
    try:
        yield store, database
    finally:
        await client.drop_database(database.name)
        await client.close()


@needs_mongo
@pytest.mark.asyncio
class TestMongoStore:
    async def test_indexes_are_idempotent_and_charge_id_is_unique(self, db):
        store, database = db
        await store.ensure_indexes(database)
        indexes = await database.orders.index_information()
        charge = next(v for v in indexes.values() if v["key"] == [("charge_id", 1)])
        assert charge["unique"] is True

    async def test_settings_upsert_and_partial_update(self, db):
        store, database = db
        users = store.UserSettings(database)
        assert await users.get(42) == {}
        assert await users.update(42, language="en") == {"language": "en"}
        assert await users.update(42, alerts=True) == {"language": "en", "alerts": True}
        assert await database.users.count_documents({}) == 1

    async def test_order_flow_and_redelivered_payment(self, db):
        store, database = db
        ledger = store.MongoStarsLedger(database)
        order = await ledger.create_order(7, "pro", 250)
        await ledger.pre_checkout(order, 7, "XTR", 250)
        first = await ledger.record_payment(order, 7, "charge-1", "XTR", 250)
        again = await ledger.record_payment(order, 7, "charge-1", "XTR", 250)
        assert first.newly_recorded and not again.newly_recorded and again.order_id == order
        with pytest.raises(store.OrderRejected):
            await ledger.pre_checkout(order, 7, "XTR", 250)

    async def test_concurrent_deliveries_of_one_payment_record_it_once(self, db):
        store, database = db
        ledger = store.MongoStarsLedger(database)
        order = await ledger.create_order(7, "pro", 250)
        results = await asyncio.gather(*(ledger.record_payment(order, 7, "charge-x", "XTR", 250) for _ in range(8)))
        assert sum(r.newly_recorded for r in results) == 1
        assert {r.order_id for r in results} == {order}

    async def test_mismatch_and_second_charge_raise_instead_of_granting(self, db):
        store, database = db
        ledger = store.MongoStarsLedger(database)
        order = await ledger.create_order(7, "pro", 250)
        with pytest.raises(ValueError):
            await ledger.record_payment(order, 7, "charge-a", "XTR", 1)
        with pytest.raises(store.OrderRejected):
            await ledger.pre_checkout(order, 8, "XTR", 250)
        await ledger.record_payment(order, 7, "charge-b", "XTR", 250)
        with pytest.raises(ValueError, match="another charge"):
            await ledger.record_payment(order, 7, "charge-c", "XTR", 250)

    async def test_one_worker_claims_delivery_until_the_lease_lapses(self, db):
        store, database = db
        ledger = store.MongoStarsLedger(database)
        order = await ledger.create_order(7, "pro", 250)
        await ledger.record_payment(order, 7, "charge-1", "XTR", 250)
        claims = await asyncio.gather(*(ledger.claim_delivery(order) for _ in range(6)))
        assert claims.count(True) == 1
        await database.orders.update_one({"_id": order}, {"$set": {"claimed_at": time.time() - 600}})
        assert await ledger.claim_delivery(order) is True
        await ledger.mark_delivered(order)
        assert (await database.orders.find_one({"_id": order}))["status"] == "delivered"

    async def test_refund_once_and_paginate(self, db):
        store, database = db
        ledger = store.MongoStarsLedger(database)
        ids = [await ledger.create_order(9, "pack", 10) for _ in range(5)]
        await ledger.record_payment(ids[0], 9, "charge-r", "XTR", 10)
        assert await ledger.mark_refunded("charge-r") is True
        assert await ledger.mark_refunded("charge-r") is False
        first = await ledger.orders_for(9, limit=3)
        rest = await ledger.orders_for(9, after=first[-1]["_id"], limit=3)
        assert [o["_id"] for o in first + rest] == sorted(ids)


def test_selection_policy_is_routed_and_balanced():
    skill = (SKILL / "SKILL.md").read_text()
    rule = next(line for line in skill.splitlines() if line.startswith("19. "))
    for needle in ("existing project's database", "MongoDB", "AsyncMongoClient", "PostgreSQL", "SQLite", "Redis", "database.md"):
        assert needle in rule, needle
    guide = (SKILL / "references/database.md").read_text()
    assert "Never migrate" in guide and "Redis, beside the primary database" in guide
    assert "never an application document" in guide  # MTProto sessions stay in secret configuration


def test_no_reference_recommends_motor_or_its_aiogram_storage():
    for path in (SKILL / "references").glob("*.md"):
        text = path.read_text()
        for line in text.splitlines():
            if "Motor" in line or "MongoStorage" in line.replace("PyMongoStorage", ""):
                assert "deprecated" in line or "not `MongoStorage`" in line or "never `MongoStorage`" in line, (path.name, line)
