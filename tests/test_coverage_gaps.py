"""Coverage reporting: confirmed gaps from the framework registry and the capture, uncertain ones from the source.

Reproduces the T3 run in which tests used a user outside the allowlist, so the transfer
screen carrying the Cancel button never appeared, yet every observed button was pressed.
"""
import asyncio
import json
import subprocess
import sys
import textwrap

import pytest
from test_quality_gate import ENV, KIT, PY, core, installer, load  # noqa: F401  (shares the loaded core)

sys.path.insert(0, str(KIT / "python"))
from tg_quality import Recorder  # noqa: E402

TRANSFER_BOT = textwrap.dedent('''
    import asyncio
    from aiogram import Dispatcher, F, Router
    from aiogram.filters import Command
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


    def cancel_keyboard(job):
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Cancel", callback_data=f"cancel:{job}")]])


    def build_dispatcher(allowed):
        router = Router()
        jobs = {}

        @router.message(Command("fetch"))
        async def fetch(message):
            if message.from_user.id not in allowed:
                await message.answer("Not allowed.")
                return
            jobs[1] = await message.answer("Downloading...", reply_markup=cancel_keyboard(1))

        @router.callback_query(F.data.startswith("cancel:"))
        async def cancel(query):
            if query.from_user.id not in allowed:
                await query.answer("Not allowed.")
                return
            await query.answer("Cancelling")
            await query.message.edit_text("Cancelled.")

        @router.message(Command("help"))
        async def help_(message):
            await message.answer("Use /fetch")

        dp = Dispatcher()
        dp.include_router(router)
        return dp
''')

WRONG_USER_TEST = textwrap.dedent('''
    import asyncio
    from app import build_dispatcher
    from tg_quality.aiogram_adapter import AiogramHarness


    def test_journey(tg_recorder):
        bot = AiogramHarness(build_dispatcher({777}), tg_recorder)  # default user 1000 is not allowed
        async def go():
            await bot.command("/fetch")
            await bot.callback("cancel:1")
            await bot.command("/help")
        asyncio.run(go())
''')

RIGHT_USER_TEST = WRONG_USER_TEST.replace("tg_recorder)  # default user 1000 is not allowed", "tg_recorder, user_id=777)").replace(
    'await bot.callback("cancel:1")', 'await bot.press("Cancel")')


def transfer_module(tmp_path):
    (tmp_path / "app.py").write_text(TRANSFER_BOT)
    return load(f"transfer_bot_{abs(hash(str(tmp_path)))}", tmp_path / "app.py")


def run_journey(module, user_id, press):
    pytest.importorskip("aiogram")
    from tg_quality.aiogram_adapter import AiogramHarness

    recorder = Recorder()
    bot = AiogramHarness(module.build_dispatcher({777}), recorder, user_id=user_id)

    async def go():
        await bot.command("/fetch")
        await (bot.press("Cancel") if press else bot.callback("cancel:1"))
    asyncio.run(go())
    return recorder


class TestMissingScreen:
    def test_wrong_user_reports_confirmed_and_static_gaps(self, tmp_path):
        recorder = run_journey(transfer_module(tmp_path), user_id=1000, press=False)
        report = core.coverage_report(recorder.interactions, list(recorder.handlers.values()), core.source_callbacks(tmp_path))
        assert report["pressed_never_offered"] == ["cancel:#"]
        assert any("cancel:#" in gap and "no captured screen offered it" in gap and "app.py:" in gap for gap in report["confirmed_gaps"])
        assert any("help_" in gap and "never ran" in gap for gap in report["confirmed_gaps"])
        assert [s["pattern"] for s in report["static"]["never_captured"]] == ["cancel:"]
        assert all("static" not in gap for gap in report["confirmed_gaps"])
        assert report["button_coverage"] is None  # nothing offered, so no claim of full coverage

    def test_reached_screen_has_no_cancel_gap(self, tmp_path):
        recorder = run_journey(transfer_module(tmp_path), user_id=777, press=True)
        report = core.coverage_report(recorder.interactions, list(recorder.handlers.values()), core.source_callbacks(tmp_path))
        assert report["pressed_never_offered"] == [] and report["static"]["never_captured"] == []
        assert report["button_coverage"] == 1.0
        assert [gap for gap in report["confirmed_gaps"] if "help_" not in gap] == []

    def test_full_button_coverage_still_warns_about_branches(self, tmp_path):
        recorder = run_journey(transfer_module(tmp_path), user_id=777, press=True)
        report = core.coverage_report(recorder.interactions, list(recorder.handlers.values()))
        assert "does not prove every screen" in report["note"] and "one branch" in report["note"]

    def test_handlers_are_named_with_filters_and_counted(self, tmp_path):
        recorder = run_journey(transfer_module(tmp_path), user_id=777, press=True)
        handlers = {h["key"].split(":", 1)[1]: h for h in recorder.handlers.values()}
        assert handlers["fetch/message"]["detail"] == "Command(fetch)" and handlers["fetch/message"]["runs"] == 1
        assert handlers["cancel/callback_query"]["detail"] == "F.data.startswith('cancel:')"
        assert handlers["help_/message"]["runs"] == 0
        assert recorder.interactions[0]["handlers"][0].endswith("fetch/message")

    def test_instrumenting_twice_does_not_double_count(self, tmp_path):
        pytest.importorskip("aiogram")
        from tg_quality.aiogram_adapter import AiogramHarness

        module = transfer_module(tmp_path)
        dispatcher = module.build_dispatcher({777})
        recorder = Recorder()
        AiogramHarness(dispatcher, recorder, user_id=777)
        bot = AiogramHarness(dispatcher, recorder, user_id=777)
        asyncio.run(bot.command("/help"))
        assert sum(h["runs"] for h in recorder.handlers.values()) == 1


class TestForgedCallbacks:
    """Stale and forged callbacks are a legitimate test pattern and must not read as unreached screens."""

    def capture(self, *pressed):
        menu = {"method": "sendMessage", "params": {"chat_id": 1, "text": "Menu", "reply_markup": {"inline_keyboard": [
            [{"text": "Socks", "callback_data": "product:12"}]]}}}
        return [{"kind": "command", "value": "/start", "calls": [menu]}] + [{"kind": "callback", "value": p, "calls": []} for p in pressed]

    def test_stale_variant_of_a_shown_route_is_not_a_gap(self, tmp_path):
        (tmp_path / "bot.py").write_text('b = Button("x", callback_data=f"product:{pid}")\n')
        report = core.coverage_report(self.capture("product:abc", "product:999", "product:"), None, core.source_callbacks(tmp_path))
        assert report["pressed_never_offered"] == [] and report["confirmed_gaps"] == []

    def test_junk_data_the_bot_never_builds_is_informational(self, tmp_path):
        (tmp_path / "bot.py").write_text('b = Button("x", callback_data=f"product:{pid}")\n')
        report = core.coverage_report(self.capture("garbage"), None, core.source_callbacks(tmp_path))
        assert report["confirmed_gaps"] == [] and report["sent_directly_only"] == ["garbage"]
        assert any("stale or forged" in gap for gap in report["uncertain_gaps"])

    def test_route_the_bot_builds_but_tests_never_showed_is_confirmed(self, tmp_path):
        (tmp_path / "bot.py").write_text('a = Button("x", callback_data=f"product:{pid}")\nb = Button("Retry", callback_data=f"retry:{job}")\n')
        report = core.coverage_report(self.capture("retry:7"), None, core.source_callbacks(tmp_path))
        assert len(report["confirmed_gaps"]) == 1 and "bot.py:2" in report["confirmed_gaps"][0]

    def test_without_a_source_scan_nothing_is_confirmed_from_forged_data(self):
        report = core.coverage_report(self.capture("retry:7"), None, None)
        assert report["confirmed_gaps"] == [] and report["sent_directly_only"] == ["retry:#"]


class TestPTBRegistry:
    def test_conversation_states_and_patterns_are_listed(self):
        pytest.importorskip("telegram")
        from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters
        from tg_quality.ptb_adapter import PTBHarness

        async def start(update, context):
            await update.message.reply_text("Name?")
            return 1

        async def name(update, context):
            await update.message.reply_text("Thanks")
            return ConversationHandler.END

        async def stop(update, context):
            return ConversationHandler.END

        async def pick(update, context):
            await update.callback_query.answer()

        def register(app):
            app.add_handler(ConversationHandler(entry_points=[CommandHandler("signup", start)],
                                                states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, name)]},
                                                fallbacks=[CommandHandler("cancel", stop)]))
            app.add_handler(CallbackQueryHandler(pick, pattern=r"^pick:"))

        recorder = Recorder()

        async def go():
            async with PTBHarness(register, recorder) as bot:
                await bot.command("/signup")
                await bot.text("Ann")
        asyncio.run(go())
        details = {h["key"].split(":", 1)[1]: (h["detail"], h["runs"]) for h in recorder.handlers.values()}
        assert details["start/CommandHandler"] == ("entry /signup", 1)
        assert details["name/MessageHandler"][0].startswith("state 1 MessageHandler(") and details["name/MessageHandler"][1] == 1
        assert details["stop/CommandHandler"] == ("fallback /cancel", 0)
        assert details["pick/CallbackQueryHandler"] == ("CallbackQueryHandler(pattern='^pick:')", 0)
        report = core.coverage_report(recorder.interactions, list(recorder.handlers.values()))
        assert len(report["handlers"]["never_ran"]) == 2


class TestSourceScan:
    def test_finds_literals_prefixes_factories_and_dynamic_values(self, tmp_path):
        (tmp_path / "bot.py").write_text(textwrap.dedent('''
            a = InlineKeyboardButton(text="Home", callback_data="home")
            b = InlineKeyboardButton("Open", callback_data=f"open:{item.id}")
            c = {"text": "Raw", "callback_data": "raw"}
            d = InlineKeyboardButton("Var", callback_data=payload)
            class Item(CallbackData, prefix="item"):
                id: int
        '''))
        (tmp_path / "menu.mjs").write_text('const k = new InlineKeyboard().text("Buy", `buy:${id}`).text("Back", "back");\n')
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests/test_x.py").write_text('x = dict(callback_data="only-in-tests")\n')
        found = core.source_callbacks(tmp_path)
        patterns = {(s["pattern"], s["exact"]) for s in found["literal"]}
        assert patterns == {("home", True), ("open:", False), ("raw", True), ("item:", False), ("buy:", False), ("back", True)}
        assert [d["expression"] for d in found["dynamic"]] == ["payload"]

    def test_dynamic_values_are_uncertain_not_confirmed(self, tmp_path):
        (tmp_path / "bot.py").write_text("b = Button(callback_data=payload)\n")
        report = core.coverage_report([], None, core.source_callbacks(tmp_path))
        assert report["confirmed_gaps"] == [] and "cannot be checked statically" in report["uncertain_gaps"][0]


class TestCliAndCompatibility:
    def test_old_capture_without_registry_says_inspection_unavailable(self):
        report = core.coverage_report([{"kind": "command", "value": "/start", "calls": []}])
        assert report["handlers"] is None and "unavailable" in report["note"]

    def test_require_coverage_fails_only_on_confirmed_gaps(self, tmp_path):
        capture = tmp_path / "capture-1.json"
        capture.write_text(json.dumps({"framework": "aiogram", "interactions": [
            {"kind": "command", "value": "/start", "calls": [{"method": "sendMessage", "params": {"chat_id": 1, "text": "Hi"}}], "handlers": ["m:start/message"]}],
            "handlers": [{"key": "m:start/message", "event": "message", "detail": "CommandStart", "runs": 1}]}))
        (tmp_path / "bot.py").write_text("b = Button(callback_data='never')\n")
        assert core.main(["--capture", str(capture), "--require-coverage", "--source", str(tmp_path)]) == 0  # static only
        data = json.loads(capture.read_text())
        data["handlers"].append({"key": "m:admin/message", "event": "message", "detail": "Command(admin)", "runs": 0})
        capture.write_text(json.dumps(data))
        assert core.main(["--capture", str(capture), "--require-coverage"]) == 1
        assert core.main(["--capture", str(capture)]) == 0  # reported, not failing, by default


def gate_project(tmp_path, test_source):
    pytest.importorskip("aiogram")
    (tmp_path / "app.py").write_text(TRANSFER_BOT)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_journey.py").write_text(test_source)
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\ntestpaths = tests\n")
    installer.install(tmp_path, "aiogram", None, False, True, False)
    return tmp_path


def run_gate(project, **env):
    return subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header"], cwd=project, capture_output=True,
                          text=True, timeout=120, env={**ENV, "TG_LINT_REQUIRE_INTERACTIONS": "1", **env})


@pytest.mark.parametrize("require", ["0", "1"])
def test_installed_gate_reports_the_missing_screen(tmp_path, require):
    done = run_gate(gate_project(tmp_path, WRONG_USER_TEST), TG_LINT_REQUIRE_COVERAGE=require)
    assert "coverage gap: callback 'cancel:#' was only sent directly; no captured screen offered it, though app.py:" in done.stdout
    assert "possible gap (static, unverified): app.py" in done.stdout
    assert (done.returncode != 0) == (require == "1"), done.stdout[-800:]
    report = json.loads((tmp_path / ".tg-lint/report.json").read_text())
    assert report["coverage"]["pressed_never_offered"] == ["cancel:#"]


def test_installed_gate_passes_a_journey_that_reaches_the_screen(tmp_path):
    done = run_gate(gate_project(tmp_path, RIGHT_USER_TEST + textwrap.dedent('''
        def test_help(tg_recorder):
            bot = AiogramHarness(build_dispatcher({777}), tg_recorder, user_id=777)
            asyncio.run(bot.command("/help"))
    ''')), TG_LINT_REQUIRE_COVERAGE="1")
    assert done.returncode == 0, done.stdout[-800:]
    assert "coverage gap" not in done.stdout and "possible gap" not in done.stdout
    assert "handlers run 3/3 registered" in done.stdout
