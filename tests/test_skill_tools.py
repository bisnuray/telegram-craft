"""Tests for the skill's scripts and assets. Run: pytest tests/ -q

Network-dependent tests are marked `live` and skip when core.telegram.org is
unreachable. The FFmpeg tests skip when FFmpeg is absent.
"""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "telegram-craft"
TOKEN = "123456:TEST-token-for-unit-tests"


def load(relative):
    path = SKILL / relative
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


init_data = load("assets/init_data.py")
ledger_mod = load("assets/stars_ledger.py")
media = load("assets/media_job.py")
lint = load("scripts/tg_lint.py")
audit = load("scripts/tg_audit.py")
tgdocs = load("scripts/tgdocs.py")


def sign(fields, token=TOKEN):
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


USER = json.dumps({"id": 42, "first_name": "Ann & <Bob>"}, separators=(",", ":"))


class TestInitDataPython:
    def fields(self, **extra):
        return {"auth_date": str(int(time.time())), "query_id": "AAE", "user": USER, **extra}

    def test_valid(self):
        result = init_data.validate_init_data(sign(self.fields()), TOKEN)
        assert result.user_id == 42

    def test_signature_field_stays_in_hmac(self):
        assert init_data.validate_init_data(sign(self.fields(signature="abc")), TOKEN).user_id == 42

    def test_wrong_token(self):
        with pytest.raises(init_data.InitDataError, match="mismatch"):
            init_data.validate_init_data(sign(self.fields()), "999:other")

    def test_tampered_user(self):
        raw = sign(self.fields()).replace("42", "43", 1)
        with pytest.raises(init_data.InitDataError):
            init_data.validate_init_data(raw, TOKEN)

    def test_expired(self):
        raw = sign(self.fields(auth_date=str(int(time.time()) - 7200)))
        with pytest.raises(init_data.InitDataError, match="expired"):
            init_data.validate_init_data(raw, TOKEN)

    def test_future(self):
        raw = sign(self.fields(auth_date=str(int(time.time()) + 600)))
        with pytest.raises(init_data.InitDataError, match="future"):
            init_data.validate_init_data(raw, TOKEN)

    def test_missing_hash_and_garbage(self):
        for raw in ("auth_date=1", "%%%notquery", ""):
            with pytest.raises(init_data.InitDataError):
                init_data.validate_init_data(raw, TOKEN)

    def test_duplicate_keys(self):
        with pytest.raises(init_data.InitDataError, match="duplicate"):
            init_data.validate_init_data(sign(self.fields()) + "&user=x", TOKEN)


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
class TestInitDataNode:
    def run(self, raw, token=TOKEN):
        script = (
            f'import {{ validateInitData }} from {json.dumps(str(SKILL / "assets/init_data.mjs"))};'
            f"try {{ console.log(JSON.stringify(validateInitData({json.dumps(raw)}, {json.dumps(token)}))) }}"
            'catch (e) { console.log("ERR:" + e.message) }'
        )
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    def test_python_signed_payload_verifies_in_node(self):
        fields = {"auth_date": str(int(time.time())), "user": USER, "signature": "abc"}
        assert json.loads(self.run(sign(fields)))["user"]["id"] == 42

    def test_wrong_token(self):
        fields = {"auth_date": str(int(time.time())), "user": USER}
        assert "mismatch" in self.run(sign(fields), "999:other")

    def test_expired(self):
        fields = {"auth_date": str(int(time.time()) - 7200)}
        assert "expired" in self.run(sign(fields))


@pytest.fixture
def ledger():
    return ledger_mod.StarsLedger(sqlite3.connect(":memory:"))


class TestLedger:
    def test_happy_path(self, ledger):
        order = ledger.create_order(1, "pdf", 50)
        ledger.pre_checkout(order, 1, "XTR", 50)
        assert ledger.record_payment(order, 1, "c1", "XTR", 50).newly_recorded
        assert ledger.claim_delivery(order)
        ledger.mark_delivered(order)

    def test_redelivered_update_is_idempotent(self, ledger):
        order = ledger.create_order(1, "pdf", 50)
        ledger.record_payment(order, 1, "c1", "XTR", 50)
        assert not ledger.record_payment(order, 1, "c1", "XTR", 50).newly_recorded

    def test_only_one_worker_claims(self, ledger):
        order = ledger.create_order(1, "pdf", 50)
        ledger.record_payment(order, 1, "c1", "XTR", 50)
        assert ledger.claim_delivery(order)
        assert not ledger.claim_delivery(order)

    def test_crashed_claim_can_retry_after_lease(self, ledger):
        order = ledger.create_order(1, "pdf", 50)
        ledger.record_payment(order, 1, "c1", "XTR", 50)
        assert ledger.claim_delivery(order, now=1000.0)
        assert not ledger.claim_delivery(order, lease_seconds=300, now=1100.0)
        assert ledger.claim_delivery(order, lease_seconds=300, now=1400.0)

    @pytest.mark.parametrize(
        "user,currency,amount",
        [(2, "XTR", 50), (1, "USD", 50), (1, "XTR", 49)],
    )
    def test_pre_checkout_rejects(self, ledger, user, currency, amount):
        order = ledger.create_order(1, "pdf", 50)
        with pytest.raises(ledger_mod.OrderRejected):
            ledger.pre_checkout(order, user, currency, amount)

    def test_pre_checkout_rejects_expired_and_paid(self, ledger):
        order = ledger.create_order(1, "pdf", 50, ttl_seconds=10, now=1000.0)
        with pytest.raises(ledger_mod.OrderRejected, match="expired"):
            ledger.pre_checkout(order, 1, "XTR", 50, now=1011.0)
        order2 = ledger.create_order(1, "pdf", 50)
        ledger.record_payment(order2, 1, "c2", "XTR", 50)
        with pytest.raises(ledger_mod.OrderRejected, match="completed"):
            ledger.pre_checkout(order2, 1, "XTR", 50)

    def test_mismatched_payment_is_not_granted(self, ledger):
        order = ledger.create_order(1, "pdf", 50)
        with pytest.raises(ValueError):
            ledger.record_payment(order, 1, "c1", "XTR", 49)
        assert not ledger.claim_delivery(order)

    def test_second_charge_for_paid_order_flagged(self, ledger):
        order = ledger.create_order(1, "pdf", 50)
        ledger.record_payment(order, 1, "c1", "XTR", 50)
        with pytest.raises(ValueError, match="refund"):
            ledger.record_payment(order, 1, "c2", "XTR", 50)

    def test_refund_once(self, ledger):
        order = ledger.create_order(1, "pdf", 50)
        ledger.record_payment(order, 1, "c1", "XTR", 50)
        assert ledger.mark_refunded("c1")
        assert not ledger.mark_refunded("c1")


class TestMediaJob:
    def test_workspace_removed_on_error(self):
        async def scenario():
            captured = {}
            with pytest.raises(RuntimeError):
                async with media.job_workspace() as path:
                    captured["path"] = path
                    (path / "x").write_text("data")
                    raise RuntimeError("boom")
            return captured["path"]
        assert not asyncio.run(scenario()).exists()

    def test_timeout_kills_child(self):
        async def scenario():
            with pytest.raises(media.MediaJobError) as info:
                await media.run_tool(["sleep", "30"], asyncio.Semaphore(1), timeout_seconds=0.2)
            return info.value
        started = time.monotonic()
        assert asyncio.run(scenario()).user_message
        assert time.monotonic() - started < 5

    def test_failure_hides_stderr_from_user(self):
        async def scenario():
            with pytest.raises(media.MediaJobError) as info:
                await media.run_tool(["sh", "-c", "echo /secret/path >&2; exit 3"], asyncio.Semaphore(1))
            return info.value
        error = asyncio.run(scenario())
        assert "/secret/path" not in error.user_message
        assert "/secret/path" in str(error)

    def test_limiter_caps_concurrency(self, tmp_path):
        async def scenario():
            limiter = asyncio.Semaphore(2)
            log = tmp_path / "log"
            cmd = ["sh", "-c", f"echo s >> {log}; sleep 0.25; echo e >> {log}"]
            await asyncio.gather(*(media.run_tool(cmd, limiter) for _ in range(5)))
            depth = peak = 0
            for line in log.read_text().split():
                depth += 1 if line == "s" else -1
                peak = max(peak, depth)
            return peak
        assert asyncio.run(scenario()) <= 2

    def test_output_size_guard(self, tmp_path):
        file = tmp_path / "out"
        file.write_bytes(b"x" * 11)
        with pytest.raises(media.MediaJobError):
            media.assert_uploadable(file, limit_bytes=10)
        assert media.assert_uploadable(file, limit_bytes=11) == 11
        with pytest.raises(media.MediaJobError):
            media.assert_uploadable(tmp_path / "missing")

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
    def test_real_voice_conversion(self):
        async def scenario():
            limiter = asyncio.Semaphore(1)
            async with media.job_workspace() as path:
                source = path / "a b; rm -rf x.wav"  # hostile but harmless name
                await media.run_tool(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-f", "wav", str(source)], limiter)
                target = path / "voice.ogg"
                await media.run_tool(media.ffmpeg_to_voice_argv(source, target), limiter)
                probe = await asyncio.to_thread(subprocess.run, ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(target)], capture_output=True, text=True)
                return media.assert_uploadable(target), probe.stdout.strip()
        size, codec = asyncio.run(scenario())
        assert size > 0 and codec == "opus"


def codes(screen, level=None):
    found = lint.lint_screens([screen] if isinstance(screen, dict) else screen)
    return {f["code"] for f in found if level is None or f["level"] == level}


class TestLint:
    def test_clean_screen(self):
        screen = {
            "id": "plan", "kind": "detail", "parse_mode": "HTML",
            "text": "<b>Pro plan</b>\nRenews on 3 March for 150 Stars.",
            "reply_markup": {"inline_keyboard": [[{"text": "Cancel renewal", "callback_data": "sub:cancel:ask"}], [{"text": "Back", "callback_data": "home"}]]},
        }
        assert lint.lint_screens([screen]) == []

    @pytest.mark.parametrize(
        "text,code",
        [
            ("<b>open", "html-balance"),
            ("<b>a<i>b</b></i>", "html-balance"),
            ("<div>x</div>", "html-tag"),
            ("1 < 2", "html-escape"),
            ("Tom & Jerry", "html-escape"),
            ("&nbsp;x", "html-entity"),
            ('<a>x</a>', "html-attr"),
            ("<blockquote><blockquote>x</blockquote></blockquote>", "html-nesting"),
        ],
    )
    def test_html_errors(self, text, code):
        assert code in codes({"text": text, "parse_mode": "HTML"}, "error")

    @pytest.mark.parametrize(
        "text", ["a &lt; b &amp; c", '<a href="https://t.me/x">x</a>', '<pre><code class="language-py">x</code></pre>', "&#128512; ok", '<span class="tg-spoiler">x</span>'],
    )
    def test_html_valid(self, text):
        assert codes({"text": text, "parse_mode": "HTML"}, "error") == set()

    def test_mdv2(self):
        assert "mdv2-escape" in codes({"text": "Price: 10.50", "parse_mode": "MarkdownV2"}, "error")
        assert "mdv2-balance" in codes({"text": "*bold", "parse_mode": "MarkdownV2"}, "error")
        assert codes({"text": "*bold* 10\\.50 [a](https://t.me/x)", "parse_mode": "MarkdownV2"}, "error") == set()

    def test_length_counts_visible_text_only(self):
        assert "length" not in codes({"text": "<b>" + "a" * 4096 + "</b>", "parse_mode": "HTML"}, "error")
        assert "length" in codes({"text": "a" * 4097}, "error")
        assert "length" in codes({"caption": "a" * 1025}, "error")
        assert "length" in codes({"kind": "callback_answer", "text": "a" * 201}, "error")

    def test_callback_bytes_not_characters(self):
        button = {"text": "x", "callback_data": "я" * 33}
        assert "callback-bytes" in codes({"text": "t", "reply_markup": {"inline_keyboard": [[button]]}}, "error")

    def test_button_contract(self):
        def kb(b):
            return {"text": "t", "reply_markup": {"inline_keyboard": [[b]]}}
        assert "button-action" in codes(kb({"text": "x"}), "error")
        assert "button-action" in codes(kb({"text": "x", "url": "https://t.me", "callback_data": "a"}), "error")
        assert "button-url" in codes(kb({"text": "x", "url": "example.com"}), "error")
        assert "button-style" in codes(kb({"text": "x", "callback_data": "a", "style": "red"}), "error")

    def test_ai_style_copy_warned(self):
        text = "🚀🚀 WELCOME TO THE BEST BOT!!!\n━━━━━━━━━━\n✨ Feature one\n🔥 Feature two\n💎 Feature three\n🎯 Feel free to explore!"
        found = codes({"text": text}, "warning")
        assert {"emoji-heavy", "decorative-rule", "all-caps", "exclamations", "boilerplate", "emoji-bullets"} <= found

    def test_navigation_signals(self):
        menu = {"id": "m", "kind": "list", "text": "Items", "reply_markup": {"inline_keyboard": [[{"text": "Item", "callback_data": "i:1"}]]}}
        assert "dead-end" in codes(menu, "warning")
        delete = {"text": "Item", "reply_markup": {"inline_keyboard": [[{"text": "Delete", "callback_data": "i:del:1"}]]}}
        assert "unconfirmed-destructive" in codes(delete, "warning")
        a = {"text": "a", "reply_markup": {"inline_keyboard": [[{"text": "Back", "callback_data": "x"}]]}}
        b = {"text": "b", "reply_markup": {"inline_keyboard": [[{"text": "Go back", "callback_data": "y"}]]}}
        assert "inconsistent-back" in codes([a, b], "warning")

    def test_cli_exit_codes(self, tmp_path):
        script = str(SKILL / "scripts/tg_lint.py")
        good = tmp_path / "g.json"
        good.write_text(json.dumps({"text": "Done."}))
        bad = tmp_path / "b.json"
        bad.write_text(json.dumps({"text": "<b>", "parse_mode": "HTML"}))
        broken = tmp_path / "x.json"
        broken.write_text("{")
        assert subprocess.run([sys.executable, script, str(good)], capture_output=True).returncode == 0
        assert subprocess.run([sys.executable, script, str(bad)], capture_output=True).returncode == 1
        assert subprocess.run([sys.executable, script, str(broken)], capture_output=True).returncode == 2


VULN_PY = '''
import time, subprocess
from aiogram import F
from aiogram.types import CallbackQuery, Message
BOT = "1234567890:AAFAKE_TEST_TOKEN_NOT_REAL_00000000"

async def on_cb(callback: CallbackQuery):
    time.sleep(2)
    await callback.message.edit_text("done")

async def greet(message: Message):
    await message.answer(f"<b>Hi {message.from_user.full_name}</b>", parse_mode="HTML")

async def conv(path):
    subprocess.run(f"ffmpeg -i {path}", shell=True)

async def paid(message: Message):
    if message.successful_payment:
        grant(message.from_user.id)

async def admin(message):
    if message.from_user.username == ADMIN_NAME:
        pass

async def q(db, name):
    await db.execute(f"select * from t where n='{name}'")

async def boot(bot):
    await bot.set_webhook("https://x.test/hook", drop_pending_updates=True)
'''
CLEAN_PY = '''
import asyncio, html
from aiogram.types import CallbackQuery, Message

async def on_cb(callback: CallbackQuery):
    await callback.answer()
    await asyncio.sleep(0)

async def greet(message: Message):
    await message.answer(f"<b>Hi {html.escape(message.from_user.full_name)}</b>")

async def paid(message: Message):
    charge = message.successful_payment.telegram_payment_charge_id
    await store(charge)

async def q(db, name):
    await db.execute("select * from t where n=?", (name,))

async def boot(bot, secret):
    await bot.set_webhook("https://x.test/hook", secret_token=secret)
'''


class TestAudit:
    def rules(self, tmp_path, files):
        for name, content in files.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        return {lead.rule for lead in audit.audit(tmp_path)}

    def test_vulnerable_python(self, tmp_path):
        rules = self.rules(tmp_path, {"bot.py": VULN_PY})
        assert {"token-in-source", "blocking-call", "callback-unanswered", "unescaped-text", "shell-true", "payment-no-charge-id", "username-auth", "sql-string", "webhook-no-secret", "drops-updates"} <= rules

    def test_clean_python(self, tmp_path):
        assert self.rules(tmp_path, {"bot.py": CLEAN_PY}) == set()

    def test_callback_middleware_suppresses(self, tmp_path):
        src = 'from aiogram.utils.callback_answer import CallbackAnswerMiddleware\nasync def f(c: CallbackQuery):\n    await c.message.edit_text("x")\n'
        assert "callback-unanswered" not in self.rules(tmp_path, {"b.py": src})

    def test_init_data_without_expiry(self, tmp_path):
        rules = self.rules(tmp_path, {"a.py": "from aiogram.utils.web_app import safe_parse_webapp_init_data\nd = safe_parse_webapp_init_data(t, x)\n"})
        assert "init-data-no-expiry" in rules

    def test_frontend_rules(self, tmp_path):
        src = 'fetch("/api", {body: JSON.stringify(Telegram.WebApp.initDataUnsafe)});\nconst x = import.meta.env.VITE_BOT_TOKEN;\nel.innerHTML = `<b>${name}</b>`;\n'
        rules = self.rules(tmp_path, {"webapp/src/main.js": src})
        assert {"init-data-unsafe-sent", "frontend-secret", "innerhtml-template", "no-theme", "no-safe-area", "no-ready", "no-back-button"} <= rules

    def test_regressions_from_eval_false_positives(self, tmp_path):
        src = """
from aiogram.types import CallbackQuery, Message
TABLE = "orders"
async def boot(bot, db):
    await bot.delete_webhook(drop_pending_updates=False)
    await db.execute(f"select * from {TABLE} where id=?", (1,))
async def paid(message: Message, service):
    if message.successful_payment:
        await service.on_payment(message)
async def cb(callback: CallbackQuery):
    await helper(callback)
"""
        rules = self.rules(tmp_path, {"bot.py": src, "svc.py": "x = 'telegram_payment_charge_id'\n", "tests/test_a.py": "import time\nasync def f():\n    time.sleep(1)\n"})
        assert not rules & {"drops-updates", "sql-string", "payment-no-charge-id", "callback-unanswered", "blocking-call"}
        assert "callback-delegated" in rules

    def test_dynamic_sql_still_flagged(self, tmp_path):
        assert "sql-string" in self.rules(tmp_path, {"a.py": 'async def q(db, name):\n    await db.execute(f"select {name}")\n'})

    def test_placeholder_token_ignored(self, tmp_path):
        assert "token-in-source" not in self.rules(tmp_path, {"c.py": 'T = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"\n'})

    def test_ignores_vendor_and_handles_syntax_errors(self, tmp_path):
        rules = self.rules(tmp_path, {"node_modules/x/a.py": VULN_PY, "bad.py": "def ("})
        assert rules == {"syntax-error"}

    def test_never_executes_project_code(self, tmp_path):
        marker = tmp_path / "pwned"
        self.rules(tmp_path, {"evil.py": f'open({str(marker)!r}, "w").write("x")\n'})
        assert not marker.exists()


CHANGELOG = """# Bot API changelog

### 2026

#### August 24, 2026

**Bot API 10.3**

**Rich Messages**

- Added A.

#### July 14, 2026

**Bot API 10.2**

- Added B.
"""


class TestTgdocsOffline:
    def test_release_parsing(self):
        releases = tgdocs.parse_releases(CHANGELOG)
        assert [r["version"] for r in releases] == ["10.3", "10.2"]
        assert releases[0]["date"] == "August 24, 2026"
        assert "Added A" in releases[0]["body"] and "July" not in releases[0]["body"]

    def test_rejects_path_tricks(self, capsys):
        assert tgdocs.main(["page", "../../etc/passwd"]) == 2
        assert tgdocs.main(["method", "a/b"]) == 2

    def test_offline_exit_code(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tgdocs, "cache_dir", lambda: tmp_path)
        monkeypatch.setattr(tgdocs.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(tgdocs.urllib.error.URLError("no net")))
        assert tgdocs.main(["version"]) == 3


def online():
    try:
        tgdocs.fetch("bots/api-changelog")
        return True
    except Exception:  # noqa: BLE001 - any failure to fetch means the live tests are skipped
        return False


@pytest.mark.live
@pytest.mark.skipif(not online(), reason="core.telegram.org unreachable")
class TestTgdocsLive:
    def test_version(self, capsys):
        assert tgdocs.main(["version"]) == 0
        assert capsys.readouterr().out.startswith("Bot API ")

    def test_method_and_type(self, capsys):
        assert tgdocs.main(["method", "sendInvoice"]) == 0
        assert "payload" in capsys.readouterr().out
        assert tgdocs.main(["type", "InlineKeyboardButton"]) == 0
        assert "callback_data" in capsys.readouterr().out

    def test_missing_and_search_and_section(self, capsys):
        assert tgdocs.main(["method", "doesNotExistXyz"]) == 2
        assert tgdocs.main(["search", "ephemeral"]) == 0
        assert "phemeral" in capsys.readouterr().out
        assert tgdocs.main(["page", "bots/webapps", "--section", "Validating data received"]) == 0
        assert "WebAppData" in capsys.readouterr().out



def test_bot_api_version_is_consistent_everywhere():
    """A new Bot API version must be applied to every place that states it, or none."""
    import re
    root = Path(__file__).resolve().parent.parent
    skill = (root / "telegram-craft/SKILL.md").read_text()
    snapshot = re.search(r'bot-api-snapshot: "([\d.]+)"', skill).group(1)
    assert f"Bot API {snapshot} (released" in skill
    facts = (root / "telegram-craft/references/platform-facts.md").read_text()
    assert f"at Bot API {snapshot}." in facts and f"newer than {snapshot}" in facts
    assert f"newer than {snapshot})" in (root / "README.md").read_text()
