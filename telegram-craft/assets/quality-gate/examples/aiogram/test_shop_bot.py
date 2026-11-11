"""Each test simulates a user journey. The gate lints every captured payload."""
import asyncio

import pytest
from aiogram.client.default import DefaultBotProperties
from shop_bot import build_dispatcher
from tg_quality.aiogram_adapter import AiogramHarness


@pytest.fixture
def bot(tg_recorder):
    return AiogramHarness(build_dispatcher(), tg_recorder, default=DefaultBotProperties(parse_mode="HTML"))


def run(coroutine):
    asyncio.run(coroutine)


def test_start(bot):
    async def journey():
        with bot.scenario("start"):
            await bot.command("/start")
    run(journey())
    assert bot.sent("sendMessage")[0]["parse_mode"] == "HTML"
    assert bot.labels == ["Browse catalog", "Settings"]


def test_inline_navigation_and_pagination(bot):
    async def journey():
        with bot.scenario("catalog"):
            await bot.command("/start")
            await bot.press("Browse catalog")
            await bot.press("Next page")
            await bot.press("Previous")
            await bot.press("Next page")
            await bot.press("Next page")
            await bot.press("Template 7")
            await bot.press("Back")
            await bot.press("Back")
    run(journey())
    assert len(bot.sent("sendMessage")) == 1, "navigation must edit, not stack"
    assert "Browse catalog" in bot.labels


def test_error_messages_and_stale_buttons(bot):
    async def journey():
        with bot.scenario("errors"):
            await bot.text("hello")
            await bot.callback("item:99:0")
            await bot.callback("garbage")
    run(journey())
    assert "Send /start" in bot.sent("sendMessage")[0]["text"]
    assert bot.sent("answerCallbackQuery")[0]["text"] == "This item is no longer available."


def test_unmodified_edit_is_tolerated(bot):
    async def journey():
        with bot.scenario("double-tap"):
            await bot.command("/start")
            await bot.press("Settings")
            bot.fail_next("editMessageText", "Bad Request: message is not modified")
            await bot.callback("settings")
    run(journey())


def test_media_processing(bot):
    async def journey():
        with bot.scenario("media"):
            await bot.media("document", {"file_name": "a<b>.txt", "file_size": 9})
            await bot.media("document", {"file_name": "big.bin", "file_size": 30_000_000})
    run(journey())
    assert bot.sent("sendMessage")[0]["text"] == "Converting a&lt;b&gt;.txt…"
    assert len(bot.sent("sendDocument")) == 1
    assert "too large" in bot.sent("sendMessage")[1]["text"]


def test_payment_states(bot):
    async def journey():
        with bot.scenario("payment"):
            await bot.command("/start")
            await bot.press("Browse catalog")
            await bot.press("Template 1")
            await bot.press("Buy for 11 Stars")
            await bot.pre_checkout("order-1", 5)
            await bot.pre_checkout("order-1", 11)
            await bot.successful_payment("order-1", 11)
    run(journey())
    assert bot.sent("sendInvoice")[0]["currency"] == "XTR"
    answers = bot.sent("answerPreCheckoutQuery")
    assert [a["ok"] for a in answers] == [False, True]
    assert "Receipt" in bot.sent("sendMessage")[-1]["text"]


def test_settings_and_confirmation(bot):
    async def journey():
        with bot.scenario("settings"):
            await bot.command("/start")
            await bot.press("Settings")
            await bot.press("Turn alerts off")
            await bot.press("Reset settings")
            await bot.press("Keep settings")
            await bot.press("Reset settings")
            await bot.press("Reset settings now")
            await bot.press("Back")
    run(journey())
    assert "Alerts: On" in bot.sent("editMessageText")[-2]["text"]
