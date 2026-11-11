"""Each test simulates a user journey. The gate lints every captured payload."""
import asyncio

from shop_bot import register
from tg_quality.ptb_adapter import PTBHarness


def journey(recorder, name, body):
    async def main():
        async with PTBHarness(register, recorder) as bot:
            with bot.scenario(name):
                await body(bot)
            return bot
    return asyncio.run(main())


def test_start(tg_recorder):
    async def body(bot):
        await bot.command("/start")
    bot = journey(tg_recorder, "start", body)
    assert bot.labels == ["Browse catalog", "Settings"]


def test_inline_navigation_and_pagination(tg_recorder):
    async def body(bot):
        await bot.command("/start")
        await bot.press("Browse catalog")
        await bot.press("Next page")
        await bot.press("Previous")
        await bot.press("Next page")
        await bot.press("Next page")
        await bot.press("Template 7")
        await bot.press("Back")
        await bot.press("Back")
    bot = journey(tg_recorder, "catalog", body)
    assert len(bot.sent("sendMessage")) == 1, "navigation must edit, not stack"


def test_error_messages_and_stale_buttons(tg_recorder):
    async def body(bot):
        await bot.text("hello")
        await bot.callback("item:99:0")
        await bot.callback("garbage")
    bot = journey(tg_recorder, "errors", body)
    assert "Send /start" in bot.sent("sendMessage")[0]["text"]


def test_unmodified_edit_is_tolerated(tg_recorder):
    async def body(bot):
        await bot.command("/start")
        await bot.press("Settings")
        bot.fail_next("editMessageText", "Bad Request: message is not modified")
        await bot.callback("settings")
    journey(tg_recorder, "double-tap", body)


def test_media_processing(tg_recorder):
    async def body(bot):
        await bot.media("document", {"file_name": "a<b>.txt", "file_size": 9})
        await bot.media("document", {"file_name": "big.bin", "file_size": 30_000_000})
    bot = journey(tg_recorder, "media", body)
    assert bot.sent("sendMessage")[0]["text"] == "Converting a&lt;b&gt;.txt…"
    assert len(bot.sent("sendDocument")) == 1


def test_payment_states(tg_recorder):
    async def body(bot):
        await bot.command("/start")
        await bot.press("Browse catalog")
        await bot.press("Template 1")
        await bot.press("Buy for 11 Stars")
        await bot.pre_checkout("order-1", 5)
        await bot.pre_checkout("order-1", 11)
        await bot.successful_payment("order-1", 11)
    bot = journey(tg_recorder, "payment", body)
    assert bot.sent("sendInvoice")[0]["currency"] == "XTR"
    assert [a["ok"] for a in bot.sent("answerPreCheckoutQuery")] == [False, True]


def test_settings_and_confirmation(tg_recorder):
    async def body(bot):
        await bot.command("/start")
        await bot.press("Settings")
        await bot.press("Turn alerts off")
        await bot.press("Reset settings")
        await bot.press("Keep settings")
        await bot.press("Reset settings")
        await bot.press("Reset settings now")
        await bot.press("Back")
    journey(tg_recorder, "settings", body)
