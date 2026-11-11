"""The delivery reference: self-test, real library 429 errors, and claims across connections."""
import asyncio
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ASSET = Path(__file__).resolve().parent.parent / "telegram-craft/assets/update_delivery.py"
spec = importlib.util.spec_from_file_location("update_delivery", ASSET)
ud = importlib.util.module_from_spec(spec)
sys.modules["update_delivery"] = ud
spec.loader.exec_module(ud)


def test_self_test_verifies_every_guarantee_and_catches_every_broken_variant():
    done = subprocess.run([sys.executable, "-B", str(ASSET), "--self-test"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout
    assert f"{len(ud.CHECKS)}/{len(ud.CHECKS)} guarantees verified" in done.stdout


def test_retry_after_from_aiogram():
    pytest.importorskip("aiogram")
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage
    error = TelegramRetryAfter(method=SendMessage(chat_id=1, text="x"), message="Too Many Requests", retry_after=12)
    assert ud.retry_after_seconds(error) == 12


def test_retry_after_from_python_telegram_bot():
    pytest.importorskip("telegram")
    from telegram.error import RetryAfter
    assert ud.retry_after_seconds(RetryAfter(9)) == 9


def test_retry_after_from_a_raw_response_and_unrelated_errors():
    class Raw(Exception):
        parameters = {"retry_after": 4}
    assert ud.retry_after_seconds(Raw()) == 4
    assert ud.retry_after_seconds(ValueError("Bad Request")) is None

    class Future(Exception):  # python-telegram-bot's announced timedelta form
        retry_after = __import__("datetime").timedelta(seconds=5)
    assert ud.retry_after_seconds(Future()) == 5


def test_long_wait_is_raised_for_rescheduling_not_slept():
    sleeps = []

    async def call():
        raise ud._RetryAfter(900)

    async def sleep(seconds):
        sleeps.append(seconds)
    with pytest.raises(ud._RetryAfter):
        asyncio.run(ud.send_honoring_retry_after(call, sleep, max_wait=300))
    assert sleeps == []


def test_two_workers_on_one_database_never_claim_the_same_update(tmp_path):
    path = tmp_path / "inbox.db"
    first, second = ud.UpdateInbox(sqlite3.connect(path)), ud.UpdateInbox(sqlite3.connect(path))
    for update_id in (1, 2):
        assert first.receive(update_id, "{}")
    assert not second.receive(1, "{}")  # a concurrent webhook delivery of the same update
    claims = [first.claim(now=0), second.claim(now=0), first.claim(now=0)]
    assert sorted(c[0] for c in claims if c) == [1, 2] and claims[2] is None
