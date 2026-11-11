"""Verification for the message/keyboard gate. Everything runs sequentially."""
import asyncio
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "telegram-craft"
KIT = SKILL / "assets/quality-gate"
NODE_MODULES = os.environ.get("TG_TEST_NODE_MODULES")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = load("tg_lint_core_for_tests", SKILL / "scripts/tg_lint.py")
installer = load("install_quality_gate", SKILL / "scripts/install_quality_gate.py")
sys.path.insert(0, str(KIT / "python"))
sys.modules["tg_quality.lint_core"] = core


def ik(*rows):
    return {"inline_keyboard": [[row] if isinstance(row, dict) else list(row) for row in rows]}


def cb(text="Open", data="a"):
    return {"text": text, "callback_data": data}


M = "sendMessage"
MALFORMED = [
    (M, {"text": "a" * 4097}, "", "length"),
    (M, {"text": ""}, "", "text-empty"),
    (M, {}, "", "text-missing"),
    ("sendPhoto", {"caption": "a" * 1025}, "", "length"),
    ("sendDocument", {"caption": "<b>x", "parse_mode": "HTML"}, "", "html-balance"),
    (M, {"text": "<b>x", "parse_mode": "HTML"}, "", "html-balance"),
    (M, {"text": "<div>x</div>", "parse_mode": "HTML"}, "", "html-tag"),
    (M, {"text": "a & b", "parse_mode": "HTML"}, "", "html-escape"),
    (M, {"text": "&nbsp;", "parse_mode": "HTML"}, "", "html-entity"),
    (M, {"text": "<a>x</a>", "parse_mode": "HTML"}, "", "html-attr"),
    (M, {"text": "<blockquote><blockquote>x</blockquote></blockquote>", "parse_mode": "HTML"}, "", "html-nesting"),
    (M, {"text": "10.5", "parse_mode": "MarkdownV2"}, "", "mdv2-escape"),
    (M, {"text": "*x", "parse_mode": "MarkdownV2"}, "", "mdv2-balance"),
    (M, {"text": "x", "parse_mode": "Fancy"}, "", "parse-mode"),
    (M, {"text": "x", "entities": [{"type": "bold", "offset": 0, "length": 5}]}, "", "entity-range"),
    (M, {"text": "x", "entities": "bold"}, "", "entities-type"),
    (M, {"text": "x", "reply_markup": "oops"}, "", "markup-type"),
    (M, {"text": "x", "reply_markup": {}}, "", None),
    (M, {"text": "x", "reply_markup": {"inline_keyboard": [], "keyboard": []}}, "", "markup-kind"),
    (M, {"text": "x", "reply_markup": {"inline_keyboard": "a"}}, "", "inline-structure"),
    (M, {"text": "x", "reply_markup": {"inline_keyboard": ["a"]}}, "", "inline-structure"),
    (M, {"text": "x", "reply_markup": {"inline_keyboard": [["a"]]}}, "", "inline-structure"),
    (M, {"text": "x", "reply_markup": ik(cb(text=" "))}, "", "button-text"),
    (M, {"text": "x", "reply_markup": ik({"callback_data": "a"})}, "", "button-text"),
    (M, {"text": "x", "reply_markup": ik({"text": "A"})}, "", "button-action"),
    (M, {"text": "x", "reply_markup": ik({"text": "A", "url": "https://t.me", "callback_data": "a"})}, "", "button-action"),
    (M, {"text": "x", "reply_markup": ik(cb(data="я" * 33))}, "", "callback-bytes"),
    (M, {"text": "x", "reply_markup": ik(cb(data=""))}, "", "callback-bytes"),
    (M, {"text": "x", "reply_markup": ik({"text": "A", "url": "example.com"})}, "", "button-url"),
    (M, {"text": "x", "reply_markup": ik({"text": "A", "callback_data": "a", "style": "red"})}, "", "button-style"),
    (M, {"text": "x", "reply_markup": ik({"text": "A", "web_app": {"url": "http://x.test"}})}, "", "web-app-url"),
    (M, {"text": "x", "reply_markup": ik({"text": "A", "web_app": {"url": "https://x.test"}})}, "supergroup", "web-app-chat"),
    (M, {"text": "x", "reply_markup": ik({"text": "A", "copy_text": {"text": ""}})}, "", "copy-text"),
    (M, {"text": "x", "reply_markup": ik({"text": "A", "pay": True})}, "", "pay-method"),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 1}], "reply_markup": ik(cb(), {"text": "Pay", "pay": True})}, "", "pay-position"),
    (M, {"text": "x", "reply_markup": {"keyboard": []}}, "", "reply-structure"),
    (M, {"text": "x", "reply_markup": {"keyboard": [[{"text": ""}]]}}, "", "button-text"),
    (M, {"text": "x", "reply_markup": {"keyboard": [[{"text": "A", "callback_data": "a"}]]}}, "", "reply-button-field"),
    (M, {"text": "x", "reply_markup": {"keyboard": [[{"text": "A", "request_contact": True, "request_location": True}]]}}, "", "button-action"),
    (M, {"text": "x", "reply_markup": {"keyboard": [[{"text": "A", "request_contact": True}]]}}, "group", "reply-private-only"),
    (M, {"text": "x", "reply_markup": {"keyboard": [[{"text": "A", "web_app": {"url": "https://x.test"}}]]}}, "group", "web-app-chat"),
    (M, {"text": "x", "reply_markup": {"keyboard": [[{"text": "A"}]], "input_field_placeholder": "a" * 65}}, "", "placeholder-length"),
    (M, {"text": "x", "reply_markup": {"force_reply": False}}, "", "markup-kind"),
    ("editMessageText", {"text": "x", "reply_markup": {"keyboard": [[{"text": "A"}]]}}, "", "markup-edit"),
    ("editMessageReplyMarkup", {"reply_markup": {"remove_keyboard": True}}, "", "markup-edit"),
    ("answerCallbackQuery", {"callback_query_id": "1", "text": "a" * 201}, "", "length"),
    ("answerCallbackQuery", {"text": "ok"}, "", "callback-id"),
    ("sendMediaGroup", {"media": [{"type": "photo"}]}, "", "media-group-size"),
    ("sendMediaGroup", {"media": [{"type": "photo", "caption": "a" * 1025}, {"type": "photo"}]}, "", "length"),
    ("sendInvoice", {"title": "a" * 33, "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 1}]}, "", "invoice-title"),
    ("sendInvoice", {"title": "t", "description": "", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 1}]}, "", "invoice-description"),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "я" * 65, "currency": "XTR", "prices": [{"label": "a", "amount": 1}]}, "", "invoice-payload"),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": []}, "", "invoice-prices"),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 1}, {"label": "b", "amount": 1}]}, "", "stars-prices"),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "provider_token": "x", "prices": [{"label": "a", "amount": 1}]}, "", "stars-provider"),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 1}], "subscription_period": 2592000}, "", "subscription-method"),
    ("createInvoiceLink", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 1}], "subscription_period": 86400}, "", "subscription-period"),
    ("createInvoiceLink", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 10001}], "subscription_period": 2592000}, "", "subscription-price"),
    ("answerPreCheckoutQuery", {"pre_checkout_query_id": "1", "ok": False}, "", "precheckout-message"),
    ("sendRichMessage", {"rich_message": {"html": "a", "markdown": "b"}}, "", "rich-content"),
    ("sendRichMessage", {"rich_message": "x"}, "", "rich-type"),
    ("setMyCommands", {"commands": [{"command": "Bad-Name", "description": "x"}]}, "", "command-name"),
    ("setMyCommands", {"commands": [{"command": "ok", "description": ""}]}, "", "command-description"),
]
VALID = [
    (M, {"text": "<b>Plan</b>\nRenews on 3 March.", "parse_mode": "HTML"}, ""),
    (M, {"text": "a &lt; b &amp; c &quot;x&quot; &#128512;", "parse_mode": "HTML"}, ""),
    (M, {"text": '<a href="https://t.me/x">x</a> <tg-spoiler>y</tg-spoiler> <tg-time unix="1" format="t">t</tg-time>', "parse_mode": "HTML"}, ""),
    (M, {"text": '<pre><code class="language-python">x = 1</code></pre>', "parse_mode": "HTML"}, ""),
    (M, {"text": "<blockquote expandable>Long note</blockquote>", "parse_mode": "HTML"}, ""),
    (M, {"text": "*bold* 10\\.50 [a](https://t.me/x) `code.x`", "parse_mode": "MarkdownV2"}, ""),
    (M, {"text": "Plain 1 < 2 & done.", "entities": [{"type": "bold", "offset": 0, "length": 5}]}, ""),
    (M, {"text": "😀" * 2 + " done", "entities": [{"type": "bold", "offset": 0, "length": 4}]}, ""),
    ("sendPhoto", {"photo": "x"}, ""),
    (M, {"text": "Pick one", "reply_markup": ik(cb(data="x" * 64))}, ""),
    (M, {"text": "Pick one", "reply_markup": ik(cb("View order", "o"), {"text": "Docs", "url": "tg://resolve?domain=x"})}, ""),
    (M, {"text": "Open", "reply_markup": ik({"text": "Open app", "web_app": {"url": "https://x.test"}})}, "private"),
    (M, {"text": "Code", "reply_markup": ik({"text": "Copy code", "copy_text": {"text": "abc"}})}, ""),
    (M, {"text": "Soon", "reply_markup": ik({"text": "Unavailable", "disabled": {}})}, ""),
    (M, {"text": "Share", "reply_markup": {"keyboard": [[{"text": "Send phone", "request_contact": True}], [{"text": "Skip for now"}]], "resize_keyboard": True, "input_field_placeholder": "Choose"}}, "private"),
    (M, {"text": "Open", "reply_markup": {"keyboard": [[{"text": "Open app", "web_app": {"url": "https://x.test"}}]]}}, "private"),
    (M, {"text": "Bye", "reply_markup": {"remove_keyboard": True}}, "group"),
    (M, {"text": "Name?", "reply_markup": {"force_reply": True, "input_field_placeholder": "Your name"}}, "group"),
    ("editMessageText", {"text": "Updated", "reply_markup": ik(cb("Refresh list", "r"))}, ""),
    ("editMessageText", {"text": "Empty menu", "reply_markup": {"inline_keyboard": []}}, ""),
    ("editMessageText", {"rich_message": {"markdown": "# Title"}}, ""),
    ("answerCallbackQuery", {"callback_query_id": "1"}, ""),
    ("sendMediaGroup", {"media": [{"type": "photo", "caption": "One"}, {"type": "photo"}]}, ""),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 1}], "provider_token": "", "reply_markup": ik({"text": "Pay 1 XTR", "pay": True})}, ""),
    ("sendInvoice", {"title": "t", "description": "d", "payload": "p", "currency": "USD", "provider_token": "tok", "prices": [{"label": "a", "amount": 1}, {"label": "tax", "amount": 1}]}, ""),
    ("createInvoiceLink", {"title": "t", "description": "d", "payload": "p", "currency": "XTR", "prices": [{"label": "a", "amount": 10000}], "subscription_period": 2592000}, ""),
    ("answerPreCheckoutQuery", {"pre_checkout_query_id": "1", "ok": False, "error_message": "Sold out"}, ""),
    ("sendRichMessage", {"rich_message": {"blocks": []}}, ""),
    ("setMyCommands", {"commands": [{"command": "start_now", "description": "Start"}]}, ""),
    ("sendSomethingNew", {"text": "<", "parse_mode": "HTML"}, ""),
    (M, {"text": "Reply", "reply_markup": json.dumps(ik(cb("Open item", "o")))}, ""),
]
WARNINGS = [
    ({"text": "🚀 Launch 🔥 now 💎 today ✨"}, "emoji-heavy"),
    ({"text": "Title\n━━━━━━━━\nBody"}, "decorative-rule"),
    ({"text": "PLEASE READ THIS NOTICE"}, "all-caps"),
    ({"text": "Wow! Great! Nice!"}, "exclamations"),
    ({"text": "Something went wrong."}, "boilerplate"),
    ({"text": "word " * 120}, "poor-hierarchy"),
    ({"text": "Choose", "reply_markup": ik(cb("OK", "o"))}, "generic-label"),
    ({"text": "Choose", "reply_markup": ik(cb("Yes", "y"), cb("No", "n"))}, "generic-label"),
    ({"text": "Choose", "reply_markup": {"inline_keyboard": [[]]}}, "empty-row"),
    ({"text": "Choose", "reply_markup": ik(cb("A" * 40, "o"))}, "label-long"),
    ({"text": "x", "parse_mode": "Markdown"}, "legacy-markdown"),
    ({"text": "x", "parse_mode": "HTML", "entities": [{"type": "bold", "offset": 0, "length": 1}]}, "entities-and-parse-mode"),
]


@pytest.mark.parametrize("method,params,chat,code", [c for c in MALFORMED if c[3]])
def test_malformed_payload_is_an_error(method, params, chat, code):
    found = core.lint_call(method, params, "t", chat)
    assert code in {f["code"] for f in found if f["level"] == "error"}, found


@pytest.mark.parametrize("method,params,chat", VALID)
def test_correct_payload_is_not_overreported(method, params, chat):
    assert core.lint_call(method, params, "t", chat) == []


@pytest.mark.parametrize("method,params", [(M, {"text": "a" * 4096}), ("sendPhoto", {"caption": "a" * 1024}), (M, {"text": "😀" * 2048})])
def test_exact_limits_are_not_errors(method, params):
    assert not [f for f in core.lint_call(method, params, "t") if f["level"] == "error"]


def test_tag_only_text_does_not_crash_the_trace():
    item = interaction(kind="text", calls=[{"method": M, "params": {"text": "<b></b>", "parse_mode": "HTML"}}])
    assert "text-empty" in codes([item], "error")


@pytest.mark.parametrize("params,code", WARNINGS)
def test_ux_signal_is_a_warning_not_an_error(params, code):
    found = core.lint_call(M, params, "t")
    assert code in {f["code"] for f in found if f["level"] == "warning"}, found
    assert not [f for f in found if f["level"] == "error"], found


def interaction(kind="callback", value="a", calls=(), **extra):
    return {"scenario": "s", "kind": kind, "value": value, "chat_type": "private", "calls": list(calls), **extra}


ANSWER = {"method": "answerCallbackQuery", "params": {"callback_query_id": "1"}}


def codes(items, level=None):
    return {f["code"] for f in core.lint_capture(items) if level is None or f["level"] == level}


class TestTrace:
    def test_unanswered_callback_is_an_error(self):
        assert "callback-unanswered" in codes([interaction(calls=[{"method": "editMessageText", "params": {"text": "x"}}])], "error")

    def test_answered_callback_is_clean(self):
        assert codes([interaction(calls=[ANSWER])]) == set()

    def test_handler_exception_is_an_error_unless_expected(self):
        assert "handler-exception" in codes([interaction(kind="text", calls=[{"method": M, "params": {"text": "x"}}], error="ValueError: x")], "error")
        assert "handler-exception" not in codes([interaction(kind="text", calls=[{"method": M, "params": {"text": "x"}}], error="ValueError: x", expected_error=True)])

    def test_silence_warning_can_be_declared_expected(self):
        assert "no-response" in codes([interaction(kind="text")], "warning")
        assert "no-response" not in codes([interaction(kind="text", expected_silence=True)])

    def test_new_menu_from_callback_is_a_warning(self):
        call = {"method": M, "params": {"text": "Menu", "reply_markup": ik(cb("Open list", "l"))}}
        assert "callback-new-message" in codes([interaction(calls=[ANSWER, call])], "warning")

    def test_repeated_text_ignores_menus_and_flags_flat_messages(self):
        flat = [interaction(kind="text", value=v, calls=[{"method": M, "params": {"text": "Your request has been received."}}]) for v in ("a", "b", "c")]
        assert "repeated-text" in codes(flat, "warning")
        menu = [interaction(value=v, calls=[ANSWER, {"method": "editMessageText", "params": {"text": "Home screen for this bot", "reply_markup": ik(cb("Open list", "l"))}}]) for v in ("a", "b", "c")]
        assert "repeated-text" not in codes(menu)

    def test_repeated_opening_counts_distinct_messages(self):
        items = [interaction(kind="text", value=str(i), calls=[{"method": M, "params": {"text": f"Hello there, friend!\nBody {i}"}}]) for i in range(3)]
        assert "repeated-opening" in codes(items, "warning")

    def test_inconsistent_back_across_screens(self):
        items = [interaction(calls=[ANSWER, {"method": "editMessageText", "params": {"text": f"s{i}", "reply_markup": ik(cb(label, "b"))}}]) for i, label in enumerate(["Back", "Go back"])]
        assert "inconsistent-back" in codes(items, "warning")

    def test_duplicates_are_collapsed(self):
        item = interaction(kind="text", calls=[{"method": M, "params": {"text": "<b>", "parse_mode": "HTML"}}])
        found = [f for f in core.lint_capture([item, item]) if f["code"] == "html-balance"]
        assert len(found) == 1

    def test_collapsed_findings_keep_every_location(self):
        bad = {"method": M, "params": {"text": "<b>", "parse_mode": "HTML"}}
        items = [interaction(kind="text", calls=[bad]), interaction(kind="command", value="/x", calls=[bad])]
        items[1]["scenario"] = "other"
        found = [f for f in core.lint_capture(items) if f["code"] == "html-balance"][0]
        assert found["count"] == 2 and len(found["screens"]) == 2
        assert "x2; also other#1:sendMessage" in core.finding_line(found)


class TestWidgets:
    """Bot API 10.4 HTML widgets."""

    def codes(self, method, params, chat="private"):
        return {f["code"] for f in core.lint_call(method, params, "w", chat)}

    def test_valid_widget_is_clean(self):
        assert self.codes("sendWidget", {"chat_id": 1, "html": "<div>Score: 3</div>", "public_data": "x" * 1024}) == set()

    def test_size_and_compression_limits(self):
        import os
        assert "widget-html" in self.codes("sendWidget", {"chat_id": 1, "html": ""})
        assert "widget-html" in self.codes("sendWidget", {"chat_id": 1, "html": "a" * 32769})
        incompressible = os.urandom(12000).hex()[:20000]
        assert "widget-html-compressed" in self.codes("sendWidget", {"chat_id": 1, "html": incompressible})
        assert "widget-html-compressed" not in self.codes("sendWidget", {"chat_id": 1, "html": "<p>a</p>" * 4000})

    def test_private_chats_only_and_data_limits(self):
        assert "widget-chat" in self.codes("sendWidget", {"chat_id": -1, "html": "<p>x</p>"}, chat="supergroup")
        assert "widget-data" in self.codes("editMessageWidgetData", {"chat_id": 1, "message_id": 2, "chat_data": "é" * 513})
        assert "widget-data" in self.codes("answerWidgetQuery", {"widget_query_id": "q", "data": "x" * 1025})
        assert "widget-cache-time" in self.codes("editSharedWidgetData", {"widget_id": "w", "public_data": "", "cache_time": 4})

    def test_widget_caption_is_checked_like_any_caption(self):
        assert "length" in self.codes("sendWidget", {"chat_id": 1, "html": "<p>x</p>", "caption": "x" * 1025})


class TestCoverage:
    def items(self):
        keyboard = ik(cb("Open", "open:12"), cb("Open", "open:13"), cb("Settings", "settings"))
        return [interaction(kind="command", value="/start go", calls=[{"method": M, "params": {"text": "Home", "reply_markup": keyboard}}]),
                interaction(value="open:99", calls=[ANSWER])]

    def test_routes_group_digits_and_list_unpressed(self):
        report = core.coverage_report(self.items())
        assert report["buttons_offered"] == 2 and report["buttons_pressed"] == 1
        assert report["offered_never_pressed"] == ["settings"]
        assert report["commands"] == ["/start"] and report["button_coverage"] == 0.5

    def test_reports_what_it_cannot_cover(self):
        assert "not checked" in core.coverage_report(self.items())["note"]

    def test_no_buttons_is_not_full_coverage(self):
        assert core.coverage_report([interaction(kind="text")])["button_coverage"] is None


def write_capture(path, items):
    path.write_text(json.dumps({"framework": "x", "interactions": items}))


class TestCli:
    def test_exit_codes(self, tmp_path):
        directory = tmp_path / "c"
        directory.mkdir()
        write_capture(directory / "capture-1.json", [interaction(calls=[ANSWER])])
        write_capture(directory / "capture-2.json", [interaction(kind="text", calls=[{"method": M, "params": {"text": "Oops, try again."}}])])
        report = tmp_path / "out.json"
        assert core.main(["--capture", str(directory), "--report", str(report)]) == 0
        assert json.loads(report.read_text())["coverage"]["interactions"] == 2
        assert core.main(["--capture", str(directory), "--strict"]) == 1
        bad = tmp_path / "bad.json"
        write_capture(bad, [interaction(calls=[])])
        assert core.main(["--capture", str(bad)]) == 1

    def test_minimum_coverage(self, tmp_path):
        file = tmp_path / "c.json"
        write_capture(file, TestCoverage().items())
        assert core.main(["--capture", str(file), "--min-button-coverage", "0.4"]) == 0
        assert core.main(["--capture", str(file), "--min-button-coverage", "0.9"]) == 1

    def test_bad_input(self, tmp_path, capsys):
        assert core.main([]) == 2
        file = tmp_path / "x.json"
        file.write_text("{")
        assert core.main(["--capture", str(file)]) == 2


# Adapters, in process -------------------------------------------------------
from tg_quality import Recorder  # noqa: E402


class TestAiogramAdapter:
    def harness(self, recorder=None):
        pytest.importorskip("aiogram")
        from aiogram import Dispatcher, F
        from aiogram.client.default import DefaultBotProperties
        from aiogram.filters import CommandStart
        from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
        from tg_quality.aiogram_adapter import AiogramHarness

        dispatcher = Dispatcher()

        @dispatcher.message(CommandStart())
        async def start(message):
            await message.answer("<b>Home</b>", reply_markup=K(inline_keyboard=[[B(text="Open list", callback_data="list")]]))

        @dispatcher.callback_query(F.data == "list")
        async def listing(callback):
            await callback.answer()
            await callback.message.edit_text("List")

        @dispatcher.callback_query(F.data == "boom")
        async def boom(callback):
            raise ValueError("kaput")

        return AiogramHarness(dispatcher, recorder or Recorder(), default=DefaultBotProperties(parse_mode="HTML"))

    def test_captures_real_payload_and_resolves_defaults(self):
        bot = self.harness()

        async def go():
            await bot.command("/start")
            await bot.press("Open list")
        asyncio.run(go())
        sent = bot.sent(M)[0]
        assert sent["parse_mode"] == "HTML" and sent["chat_id"] == 1000
        assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "list"
        assert bot.recorder.interactions[1]["kind"] == "callback"
        assert core.lint_capture(bot.recorder.interactions) == []

    def test_press_refuses_absent_buttons(self):
        bot = self.harness()
        asyncio.run(bot.command("/start"))
        with pytest.raises(AssertionError, match="no button"):
            asyncio.run(bot.press("Nope"))

    def test_exception_is_recorded_and_raised(self):
        bot = self.harness()
        with pytest.raises(ValueError):
            asyncio.run(bot.callback("boom"))
        assert "kaput" in bot.recorder.interactions[0]["error"]
        assert "handler-exception" in codes(bot.recorder.interactions, "error")

    def test_simulated_api_errors_reach_the_bot_typed(self):
        from aiogram.exceptions import TelegramRetryAfter

        bot = self.harness()
        bot.fail_next(M, "Too Many Requests: retry after 3", 429, retry_after=3)
        with pytest.raises(TelegramRetryAfter) as info:
            asyncio.run(bot.command("/start"))
        assert info.value.retry_after == 3

    def test_requires_no_network(self):
        bot = self.harness()
        assert type(bot.bot.session).__name__ == "_CaptureSession"

    def test_real_project_fixture(self):
        fixture = load("redesign_fixture", ROOT / "evals/fixtures/redesign/bot.py")
        from tg_quality.aiogram_adapter import AiogramHarness

        recorder = Recorder()
        bot = AiogramHarness(fixture.dp, recorder)

        async def go():
            await bot.command("/start")
            await bot.text("hello")
            await bot.press("📚 Courses 📚")
        asyncio.run(go())
        found = core.lint_capture(recorder.interactions)
        assert not [f for f in found if f["level"] == "error"], found
        assert {"emoji-heavy", "decorative-rule", "boilerplate", "callback-new-message"} & {f["code"] for f in found}


class TestPTBAdapter:
    def test_captures_real_payload(self):
        pytest.importorskip("telegram")
        from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
        from telegram.ext import CallbackQueryHandler, CommandHandler
        from tg_quality.ptb_adapter import PTBHarness

        async def start(update, context):
            await update.message.reply_text("<b>Home</b>", parse_mode="HTML", reply_markup=K([[B("Open list", callback_data="list")]]))

        async def on_cb(update, context):
            await update.callback_query.answer()
            if update.callback_query.data == "boom":
                raise ValueError("kaput")
            await update.callback_query.edit_message_text("List")

        def register(app):
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CallbackQueryHandler(on_cb))

        recorder = Recorder()

        async def go():
            async with PTBHarness(register, recorder) as bot:
                await bot.command("/start")
                await bot.press("Open list")
                await bot.callback("boom")
                return bot
        bot = asyncio.run(go())
        markup = bot.sent(M)[0]["reply_markup"]
        assert markup["inline_keyboard"][0][0]["callback_data"] == "list" if isinstance(markup, dict) else "list" in markup
        assert bot.sent("editMessageText")[0]["text"] == "List"
        assert "handler-exception" in codes(recorder.interactions, "error")


# Installed gate, end to end (one subprocess at a time) -----------------------
PY = sys.executable
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
ENV.pop("TG_LINT_STRICT", None)


def pytest_in(project, **env):
    return subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"], cwd=project, capture_output=True, text=True, timeout=120, env={**ENV, **env})


BAD_AIOGRAM = '''
import asyncio
from aiogram import Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_quality.aiogram_adapter import AiogramHarness
dp = Dispatcher()
@dp.message(CommandStart())
async def start(m):
    await m.answer("Menu", reply_markup=K(inline_keyboard=[[B(text="Open list", callback_data="x" * 70)]]))
@dp.callback_query(F.data == "spin")
async def spin(c):
    await c.message.edit_text("no answer")
def test_journey(tg_recorder):
    bot = AiogramHarness(dp, tg_recorder)
    async def go():
        await bot.callback("spin")
    asyncio.run(go())
'''
EMPTY_TEST = "def test_nothing():\n    assert True\n"


@pytest.mark.parametrize("framework,package", [("aiogram", "aiogram"), ("ptb", "telegram")])
def test_installed_gate_passes_the_example(tmp_path, framework, package):
    pytest.importorskip(package)
    installer.install(tmp_path, framework, None, True, False, False)
    run = pytest_in(tmp_path, TG_LINT_REQUIRE_INTERACTIONS="1", TG_LINT_MIN_BUTTON_COVERAGE="1")
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Telegram quality gate" in run.stdout and "8/8 offered button routes" in run.stdout
    report = json.loads((tmp_path / ".tg-lint/report.json").read_text())
    assert report["errors"] == 0 and report["coverage"]["scenarios"] == sorted(["catalog", "double-tap", "errors", "media", "payment", "settings", "start"])


def test_gate_fails_a_run_whose_tests_pass_but_payloads_do_not(tmp_path):
    pytest.importorskip("aiogram")
    installer.install(tmp_path, "aiogram", None, False, True, False)
    (tmp_path / "tests/test_bad.py").write_text(BAD_AIOGRAM)
    run = pytest_in(tmp_path)
    assert run.returncode == 1, run.stdout
    assert "1 passed" in run.stdout and "callback-unanswered" in run.stdout and "GATE FAILED" in run.stdout


def test_ci_setting_fails_when_nothing_was_captured(tmp_path):
    pytest.importorskip("aiogram")
    installer.install(tmp_path, "aiogram", None, False, True, False)
    (tmp_path / "tests/test_none.py").write_text(EMPTY_TEST)
    assert pytest_in(tmp_path).returncode == 0
    run = pytest_in(tmp_path, TG_LINT_REQUIRE_INTERACTIONS="1")
    assert run.returncode == 1 and "no Telegram interactions" in run.stdout


def test_warnings_do_not_fail_by_default_but_strict_does(tmp_path):
    pytest.importorskip("aiogram")
    installer.install(tmp_path, "aiogram", None, False, True, False)
    (tmp_path / "tests/test_w.py").write_text(textwrap.dedent('''
        import asyncio
        from aiogram import Dispatcher
        from aiogram.filters import CommandStart
        from tg_quality.aiogram_adapter import AiogramHarness
        dp = Dispatcher()
        @dp.message(CommandStart())
        async def start(m):
            await m.answer("Something went wrong. Please wait.")
        def test_x(tg_recorder):
            asyncio.run(AiogramHarness(dp, tg_recorder).command("/start"))
    '''))
    assert pytest_in(tmp_path).returncode == 0
    assert pytest_in(tmp_path, TG_LINT_STRICT="1").returncode == 1


@pytest.mark.skipif(not NODE_MODULES or not shutil.which("node"), reason="set TG_TEST_NODE_MODULES to a directory with grammy")
class TestGrammy:
    def project(self, tmp_path, example=True):
        installer.install(tmp_path, "grammy", None, example, True, False)
        os.symlink(NODE_MODULES, tmp_path / "node_modules")

    def node(self, tmp_path, **env):
        return subprocess.run(["node", "--test"], cwd=tmp_path, capture_output=True, text=True, timeout=120, env={**ENV, "PYTHON": PY, **env})

    def test_example_passes(self, tmp_path):
        self.project(tmp_path)
        run = self.node(tmp_path, TG_LINT_REQUIRE_INTERACTIONS="1", TG_LINT_MIN_BUTTON_COVERAGE="1")
        assert run.returncode == 0, run.stdout[-3000:]
        reports = list((tmp_path / ".tg-lint").glob("report-*.json"))
        data = json.loads(reports[0].read_text())
        assert data["errors"] == 0 and data["coverage"]["buttons_pressed"] == 8

    def test_gate_fails_on_bad_payload(self, tmp_path):
        self.project(tmp_path, example=False)
        (tmp_path / "test").mkdir(exist_ok=True)
        (tmp_path / "test/bad.test.mjs").write_text(textwrap.dedent('''
            import { test } from "node:test";
            import { Bot, InlineKeyboard } from "grammy";
            import { GrammyHarness, installLintGate, Recorder } from "../tg_quality/tg_quality.mjs";
            const recorder = new Recorder();
            installLintGate(recorder);
            test("journey", async () => {
              const bot = new Bot("1:A");
              bot.command("start", (ctx) => ctx.reply("Menu", { reply_markup: new InlineKeyboard().text("Open list", "x".repeat(70)) }));
              bot.callbackQuery("spin", (ctx) => ctx.editMessageText("no answer"));
              const h = new GrammyHarness(bot, recorder);
              await h.command("/start");
              await h.callback("spin");
            });
        '''))
        run = self.node(tmp_path)
        assert run.returncode != 0
        assert "callback-bytes" in run.stdout and "callback-unanswered" in run.stdout


# Installer and templates -----------------------------------------------------
class TestInstaller:
    def test_keeps_existing_files_and_appends_conftest(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests/conftest.py").write_text("X = 1\n")
        workflow = tmp_path / ".github/workflows/telegram-quality.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("mine")
        installer.install(tmp_path, "aiogram", None, False, False, False)
        assert workflow.read_text() == "mine"
        text = (tmp_path / "tests/conftest.py").read_text()
        assert text.startswith("X = 1") and "tg_quality.pytest_plugin" in text
        installer.install(tmp_path, "aiogram", None, False, False, False)
        assert (tmp_path / "tests/conftest.py").read_text().count("tg_quality.pytest_plugin") == 1
        assert (tmp_path / ".gitignore").read_text().count(".tg-lint") == 1

    def test_copies_only_the_chosen_adapter(self, tmp_path):
        installer.install(tmp_path, "ptb", None, False, True, False)
        names = {p.name for p in (tmp_path / "tests/tg_quality").iterdir()}
        assert "ptb_adapter.py" in names and "aiogram_adapter.py" not in names

    def test_core_is_the_same_file_everywhere(self, tmp_path):
        installer.install(tmp_path, "aiogram", None, False, True, False)
        assert (tmp_path / "tests/tg_quality/lint_core.py").read_bytes() == (SKILL / "scripts/tg_lint.py").read_bytes()

    @pytest.mark.parametrize("name", ["telegram-quality-python.yml", "telegram-quality-node.yml", "pre-commit-telegram.yaml"])
    def test_templates_are_valid_yaml(self, name):
        yaml = pytest.importorskip("yaml")
        data = yaml.safe_load((KIT / "ci" / name).read_text())
        assert data

    def test_ci_requires_captured_interactions(self):
        yaml = pytest.importorskip("yaml")
        data = yaml.safe_load((KIT / "ci/telegram-quality-python.yml").read_text())
        assert data["jobs"]["telegram-quality"]["env"]["TG_LINT_REQUIRE_INTERACTIONS"] == "1"

    def test_reuses_a_gate_installed_elsewhere(self, tmp_path):
        installer.install(tmp_path, "ptb", "test_suite", False, True, False)
        log = installer.install(tmp_path, "ptb", None, False, False, False)
        assert any("existing gate" in line and "test_suite" in line for line in log)
        assert not (tmp_path / "tests").exists() and not (tmp_path / ".github").exists()

    def test_bad_project_path(self, tmp_path):
        assert installer.main([str(tmp_path / "nope"), "--framework", "ptb"]) == 2


def test_activation_description_is_the_adopted_one():
    """Changed only through a measured activation comparison (evals/trigger_compare.py)."""
    pattern = re.compile(r'^description: "(.*)"$', re.M)
    current = pattern.search((SKILL / "SKILL.md").read_text()).group(1).replace('\\"', '"')
    assert current == (ROOT / "evals/description_mtproto.txt").read_text().strip()
    assert len(current) <= 1024
    original = (ROOT / "evals/description_original.txt").read_text().strip()
    assert original.endswith("or other messengers.") and current.endswith("or other messengers.")
