"""Code-quality tooling and StringSession-first MTProto helpers. Synthetic sessions and mocked clients only."""
import ast
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon import errors
from telethon.crypto import AuthKey
from telethon.sessions import StringSession
from test_quality_gate import SKILL

AUDIT = str(SKILL / "scripts/tg_audit.py")
RUFF = shutil.which("ruff")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load("mtproto_runtime_cq", SKILL / "assets/mtproto_runtime.py")
setup_script = load("create_session_cq", SKILL / "assets/create_session.py")


def synthetic_session() -> str:
    session = StringSession()
    session.set_dc(2, "149.154.167.51", 443)
    session.auth_key = AuthKey(bytes(range(256)))  # synthetic, never valid on Telegram
    return session.save()


class TestStringSessionFromEnv:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_missing_or_empty_fails_instead_of_creating_a_login(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("TELEGRAM_SESSION_STRING", raising=False)
        else:
            monkeypatch.setenv("TELEGRAM_SESSION_STRING", value)
        with pytest.raises(runtime.SessionUnavailable, match="TELEGRAM_SESSION_STRING"):
            runtime.string_session_from_env()

    @pytest.mark.parametrize("value", ["not-a-session", "1abc", "1" + "A" * 351])
    def test_malformed_fails_without_echoing_the_value(self, monkeypatch, value):
        monkeypatch.setenv("TELEGRAM_SESSION_STRING", value)
        with pytest.raises(runtime.SessionUnavailable) as caught:
            runtime.string_session_from_env()
        assert value not in str(caught.value)

    def test_valid_string_loads_the_key(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_SESSION_STRING", synthetic_session())
        session = runtime.string_session_from_env()
        assert isinstance(session, StringSession)
        assert session.auth_key.key == bytes(range(256))


def mocked_client(authorized=True, error=None):
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=authorized, side_effect=error)
    client.start = AsyncMock(side_effect=AssertionError("start() must not run"))
    client.log_out = AsyncMock(side_effect=AssertionError("log_out() must not run"))
    return client


@pytest.mark.asyncio
class TestConnectAuthorized:
    async def test_authorized_session_connects_without_prompting(self):
        client = mocked_client()
        await runtime.connect_authorized(client)
        client.connect.assert_awaited_once()
        client.start.assert_not_called()
        client.disconnect.assert_not_awaited()

    async def test_unauthorized_session_fails_and_disconnects(self):
        client = mocked_client(authorized=False)
        with pytest.raises(runtime.SessionUnavailable, match="no longer authorized"):
            await runtime.connect_authorized(client)
        client.disconnect.assert_awaited_once()
        client.start.assert_not_called()
        client.log_out.assert_not_called()

    @pytest.mark.parametrize("error", [errors.AuthKeyUnregisteredError(request=None), errors.SessionRevokedError(request=None),
                                       errors.AuthKeyDuplicatedError(request=None)])
    async def test_revoked_or_duplicated_key_fails_and_disconnects(self, error):
        client = mocked_client(error=error)
        with pytest.raises(runtime.SessionUnavailable, match=type(error).__name__):
            await runtime.connect_authorized(client)
        client.disconnect.assert_awaited_once()
        client.log_out.assert_not_called()


class TestCreateSessionScript:
    def test_writes_a_private_file_and_never_overwrites(self, tmp_path):
        target = tmp_path / "session.txt"
        setup_script.write_private(str(target), "1secret")
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert target.read_text() == "1secret\n"
        with pytest.raises(FileExistsError):
            setup_script.write_private(str(target), "1other")

    def test_disconnects_and_never_logs_out(self):
        tree = ast.parse((SKILL / "assets/create_session.py").read_text())
        calls = {getattr(n.func, "attr", getattr(n.func, "id", "")) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert "disconnect" in calls and "log_out" not in calls


def audit(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    result = subprocess.run([sys.executable, AUDIT, str(tmp_path), "--json"], capture_output=True, text=True)
    import json
    return [(lead["rule"], lead["line"]) for lead in json.loads(result.stdout)["leads"]]


RUNTIME_SAMPLE = '''import asyncio
import contextlib
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

a = StringSession(os.environ.get("TELEGRAM_SESSION_STRING", ""))
b = StringSession(os.getenv("TELEGRAM_SESSION_STRING"))
c = StringSession(os.environ.get("S") or "")
ok = StringSession(os.environ["TELEGRAM_SESSION_STRING"])


async def run(client, bot):
    await bot.start(bot_token=os.environ["BOT_TOKEN"])
    await client.start()
    try:
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    try:
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        await client.disconnect()
        raise
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.sleep(1)
    try:
        await asyncio.sleep(1)
    except (OSError, TimeoutError):
        pass
    await client.log_out()
'''


class TestAuditRules:
    def test_runtime_mistakes_are_flagged_and_safe_patterns_are_not(self, tmp_path):
        leads = audit(tmp_path, {"app.py": RUNTIME_SAMPLE})
        rules = {(rule, line) for rule, line in leads if rule in
                 ("empty-string-session", "user-client-start", "swallowed-cancellation", "log-out")}
        assert rules == {("empty-string-session", 8), ("empty-string-session", 9), ("empty-string-session", 10),
                         ("user-client-start", 16), ("swallowed-cancellation", 19), ("log-out", 32)}

    def test_setup_script_may_sign_in_and_bare_except_swallows_cancellation(self, tmp_path):
        leads = audit(tmp_path, {
            "tools/create_session.py": "from telethon import TelegramClient\nasync def make(client):\n    await client.start()\n",
            "worker.py": "import asyncio\nasync def loop():\n    while True:\n        try:\n            await asyncio.sleep(1)\n        except:\n            continue\n",
        })
        assert not [r for r in leads if r[0] == "user-client-start"]
        assert ("swallowed-cancellation", 6) in leads

    def test_awaiting_a_cancelled_task_is_not_flagged(self, tmp_path):
        stop = ("import asyncio\nasync def stop(self):\n    self._task.cancel()\n    try:\n        await self._task\n"
                "    except asyncio.CancelledError:\n        pass\n")
        assert not [r for r in audit(tmp_path, {"w.py": stop}) if r[0] == "swallowed-cancellation"]

    def test_bot_api_project_gets_no_mtproto_leads(self, tmp_path):
        leads = audit(tmp_path, {"bot.py": "import os\nfrom aiogram import Bot\nasync def main(app):\n    await app.start()\n    os.environ.get('X', '')\n"})
        assert not [r for r in leads if r[0] in ("user-client-start", "empty-string-session", "log-out")]


GOOD_BOT = '''import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)


class Poller:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            while True:
                try:
                    async with session.get("https://example.org") as response:
                        log.info("status %s", response.status)
                except aiohttp.ClientError as error:
                    log.warning("request failed: %s", error)
                await asyncio.sleep(30)
'''

BAD_BOT = '''import asyncio
import os
import time

TOKEN = "123456:secret-token-value"


async def run():
    asyncio.create_task(asyncio.sleep(1))
    # old_value = compute()
    try:
        time.sleep(1)
    except Exception:
        pass
    print("done")
'''


@pytest.mark.skipif(RUFF is None, reason="ruff is not installed")
class TestRuffTemplate:
    def ruff(self, tmp_path, source):
        shutil.copy(SKILL / "assets/ruff.template.toml", tmp_path / "ruff.toml")
        (tmp_path / "bot.py").write_text(source)
        result = subprocess.run([RUFF, "check", "--no-cache", "--output-format", "concise", "."], cwd=tmp_path, capture_output=True, text=True)
        return set(re.findall(r": ([A-Z]+\d+) ", result.stdout)), result.returncode

    def test_clean_async_code_passes(self, tmp_path):
        codes, returncode = self.ruff(tmp_path, GOOD_BOT)
        assert returncode == 0, codes

    def test_each_defect_class_is_caught(self, tmp_path):
        codes, _ = self.ruff(tmp_path, BAD_BOT)
        assert {"F401", "RUF006", "ERA001", "ASYNC251", "BLE001", "S110", "T201", "S105"} <= codes, codes


def test_code_quality_examples_are_valid_python():
    text = (SKILL / "references/code-quality.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    assert len(blocks) >= 4
    for block in blocks:
        ast.parse(block)


def test_skill_routes_to_the_new_guidance():
    skill = (SKILL / "SKILL.md").read_text()
    for needle in ("code-quality.md", "string_session_from_env()", "connect_authorized()", "create_session.py", "ruff.template.toml"):
        assert needle in skill, needle
    assert os.path.exists(SKILL / "assets/ruff.template.toml")


class TestStringSessionConfiguration:
    def test_secrets_in_dockerfile_and_tracked_env_are_reported(self, tmp_path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\nARG TELEGRAM_SESSION_STRING\nENV TELEGRAM_API_HASH=x\nENV LOG_LEVEL=info\n")
        (tmp_path / ".env").write_text("TELEGRAM_SESSION_STRING=x\n")
        (tmp_path / ".env.example").write_text("TELEGRAM_SESSION_STRING=\n")
        (tmp_path / "app.py").write_text("from telethon import TelegramClient\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f", "."], check=True)
        result = subprocess.run([sys.executable, str(SKILL / "scripts/secure_mtproto_project.py"), str(tmp_path), "--check", "--json"],
                                capture_output=True, text=True)
        import json
        problems = json.loads(result.stdout)["problems"]
        assert result.returncode == 1
        assert any("Dockerfile:2 [secret-in-image]" in p for p in problems)
        assert any("Dockerfile:3 [secret-in-image]" in p for p in problems)
        assert not any("LOG_LEVEL" in p for p in problems)
        assert any(p.startswith(".env [env-file-tracked]") for p in problems)
        assert not any(p.startswith(".env.example") for p in problems)
