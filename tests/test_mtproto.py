"""Mocked MTProto workflows using real Telethon types. No network, no real account."""
import ast
import asyncio
import importlib.util
import logging
import re
import stat
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("telethon")
pytest.importorskip("cryptography")
from cryptography.fernet import Fernet, InvalidToken  # noqa: E402
from telethon import TelegramClient, errors, events, functions, types  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "telegram-craft"
spec = importlib.util.spec_from_file_location("mtproto_runtime", SKILL / "assets/mtproto_runtime.py")
rt = importlib.util.module_from_spec(spec)
sys.modules["mtproto_runtime"] = rt
spec.loader.exec_module(rt)


class Sleeps:
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


def flood(seconds):
    return errors.FloodWaitError(request=None, capture=seconds)


def sequence(*steps):
    iterator = iter(steps)

    async def operation():
        step = next(iterator)
        if isinstance(step, Exception):
            raise step
        return step
    return operation


class TestFloodControl:
    def test_waits_the_server_time_then_succeeds(self):
        sleeps = Sleeps()
        waits = []
        result = asyncio.run(rt.call_with_flood_control(sequence(flood(5), "ok"), sleep=sleeps, jitter_seconds=0, on_wait=lambda s, a: waits.append((s, a))))
        assert result == "ok" and sleeps.calls == [5] and waits == [(5, 1)]

    def test_long_wait_is_not_slept(self):
        sleeps = Sleeps()
        with pytest.raises(rt.FloodLimitExceeded) as info:
            asyncio.run(rt.call_with_flood_control(sequence(flood(9000)), max_wait_seconds=120, sleep=sleeps))
        assert info.value.seconds == 9000 and sleeps.calls == []

    def test_attempts_are_bounded(self):
        sleeps = Sleeps()
        with pytest.raises(errors.FloodWaitError):
            asyncio.run(rt.call_with_flood_control(sequence(flood(1), flood(1), flood(1), "never"), max_attempts=3, sleep=sleeps, jitter_seconds=0))
        assert len(sleeps.calls) == 2

    def test_slowmode_is_honored(self):
        sleeps = Sleeps()
        error = errors.SlowModeWaitError(request=None, capture=7)
        assert asyncio.run(rt.call_with_flood_control(sequence(error, 1), sleep=sleeps, jitter_seconds=0)) == 1
        assert sleeps.calls == [7]

    def test_peer_flood_stops_without_retrying(self):
        sleeps = Sleeps()
        with pytest.raises(errors.PeerFloodError):
            asyncio.run(rt.call_with_flood_control(sequence(errors.PeerFloodError(request=None), "never"), sleep=sleeps))
        assert sleeps.calls == []

    def test_other_errors_propagate(self):
        with pytest.raises(errors.ChatWriteForbiddenError):
            asyncio.run(rt.call_with_flood_control(sequence(errors.ChatWriteForbiddenError(request=None)), sleep=Sleeps()))


def test_recent_ids_dedupe_and_stay_bounded():
    recent = rt.RecentIds(capacity=2)
    assert recent.first_time(1) and not recent.first_time(1)
    recent.first_time(2)
    recent.first_time(3)
    assert recent.first_time(1)
    assert len(recent._seen) == 2


class TestSessionStore:
    def store(self, tmp_path):
        return rt.EncryptedSessionStore(tmp_path / "s", Fernet.generate_key())

    def test_round_trip_is_encrypted_and_private(self, tmp_path):
        store = self.store(tmp_path)
        store.save("bot1", "SECRET-SESSION")
        file = tmp_path / "s/bot1.session.enc"
        assert b"SECRET-SESSION" not in file.read_bytes()
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        assert store.load("bot1") == "SECRET-SESSION"

    def test_wrong_key_fails(self, tmp_path):
        store = self.store(tmp_path)
        store.save("a", "x")
        other = rt.EncryptedSessionStore(tmp_path / "s", Fernet.generate_key())
        with pytest.raises(InvalidToken):
            other.load("a")

    def test_delete_and_missing(self, tmp_path):
        store = self.store(tmp_path)
        store.save("a", "x")
        store.delete("a")
        assert store.load("a") is None
        store.delete("a")

    @pytest.mark.parametrize("name", ["", "../x", "a/b", "a b"])
    def test_rejects_path_names(self, tmp_path, name):
        with pytest.raises(ValueError):
            self.store(tmp_path).save(name, "x")

    def test_leaves_no_temporary_files(self, tmp_path):
        store = self.store(tmp_path)
        store.save("a", "x")
        assert [p.name for p in (tmp_path / "s").iterdir()] == ["a.session.enc"]

    def test_stores_a_real_string_session(self, tmp_path):
        session = StringSession()
        store = self.store(tmp_path)
        store.save("a", session.save() or "x")
        assert store.load("a")


def fake_client(authorized=True):
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_user_authorized = AsyncMock(return_value=authorized)
    return client


class TestClientRegistry:
    def test_refuses_a_duplicate_session(self):
        async def go():
            registry = rt.ClientRegistry(lambda name: fake_client())
            await registry.start("a")
            with pytest.raises(RuntimeError, match="already running"):
                await registry.start("a")
        asyncio.run(go())

    def test_refuses_concurrent_duplicate_starts(self):
        async def go():
            registry = rt.ClientRegistry(lambda name: fake_client())
            results = await asyncio.gather(registry.start("a"), registry.start("a"), return_exceptions=True)
            assert sum(isinstance(r, RuntimeError) for r in results) == 1
        asyncio.run(go())

    def test_unauthorized_session_never_prompts(self):
        async def go():
            client = fake_client(authorized=False)
            registry = rt.ClientRegistry(lambda name: client)
            with pytest.raises(PermissionError):
                await registry.start("a")
            client.disconnect.assert_awaited_once()
            client.start.assert_not_called()
        asyncio.run(go())

    def test_limits_simultaneous_connections(self):
        async def go():
            active = peak = 0

            def factory(name):
                client = fake_client()

                async def connect():
                    nonlocal active, peak
                    active += 1
                    peak = max(peak, active)
                    await asyncio.sleep(0.01)
                    active -= 1
                client.connect = connect
                return client
            registry = rt.ClientRegistry(factory, max_connecting=2)
            await asyncio.gather(*(registry.start(str(i)) for i in range(6)))
            assert peak == 2
        asyncio.run(go())

    def test_stop_all_disconnects_everything(self):
        async def go():
            clients = []

            def factory(name):
                clients.append(fake_client())
                return clients[-1]
            registry = rt.ClientRegistry(factory)
            await registry.start("a")
            await registry.start("b")
            await registry.stop_all()
            assert all(c.disconnect.await_count == 1 for c in clients)
            await registry.start("a")
        asyncio.run(go())


class TestCleanupAndCancellation:
    def test_flood_wait_can_be_cancelled(self):
        async def go():
            calls = []

            async def operation():
                calls.append(1)
                raise flood(100)
            task = asyncio.create_task(rt.call_with_flood_control(operation, max_wait_seconds=200, jitter_seconds=0))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == [1]
        asyncio.run(go())

    def test_authorization_check_failure_disconnects(self):
        async def go():
            client = fake_client()
            client.is_user_authorized = AsyncMock(side_effect=ConnectionError("lost"))
            registry = rt.ClientRegistry(lambda name: client)
            with pytest.raises(ConnectionError):
                await registry.start("a")
            client.disconnect.assert_awaited_once()
            client.is_user_authorized = AsyncMock(return_value=True)
            assert await registry.start("a") is client  # the name was released
        asyncio.run(go())

    def test_cancelled_start_disconnects_and_releases_the_name(self):
        async def go():
            client = fake_client()
            entered = asyncio.Event()

            async def connect():
                entered.set()
                await asyncio.get_running_loop().create_future()
            client.connect = connect
            registry = rt.ClientRegistry(lambda name: client)
            task = asyncio.create_task(registry.start("a"))
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            client.disconnect.assert_awaited_once()
            assert "a" not in registry._starting and "a" not in registry._clients
        asyncio.run(go())

    def test_stop_all_tries_every_client_when_one_fails(self):
        async def go():
            clients = {"a": fake_client(), "b": fake_client()}
            clients["a"].disconnect = AsyncMock(side_effect=OSError("socket"))
            registry = rt.ClientRegistry(lambda name: clients[name])
            await registry.start("a")
            await registry.start("b")
            with pytest.raises(OSError):
                await registry.stop_all()
            clients["b"].disconnect.assert_awaited_once()
        asyncio.run(go())

    def test_helpers_never_prompt_or_sign_in(self):
        tree = ast.parse((SKILL / "assets/mtproto_runtime.py").read_text())
        called = {(getattr(n.func, "value", None) and getattr(n.func.value, "id", ""), getattr(n.func, "attr", getattr(n.func, "id", "")))
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        forbidden = {name for owner, name in called if name in {"input", "getpass", "send_code_request", "sign_in", "log_out", "qr_login"}
                     or name == "start" and owner != "registry"}
        assert not forbidden, forbidden


def real_client():
    return TelegramClient(StringSession(), 12345, "test-hash", flood_sleep_threshold=0)


class TestRealTelethonOffline:
    def test_bot_token_sign_in_flow(self):
        async def go():
            client = real_client()
            client.connect = AsyncMock()
            client.is_connected = MagicMock(return_value=True)
            client.get_me = AsyncMock(return_value=None)
            client.sign_in = AsyncMock(return_value=types.User(id=1, bot=True, first_name="b"))
            await client._start(phone=lambda: "", password=lambda: "", bot_token="123:abc", force_sms=False, code_callback=None, first_name="", last_name="", max_attempts=1)
            client.sign_in.assert_awaited_once_with(bot_token="123:abc")
        asyncio.run(go())

    def test_new_message_handler_with_pattern(self):
        async def go():
            calls = []
            builder = events.NewMessage(pattern=r"^/status$", incoming=True)
            builder.resolved = True  # normally done by the client when the handler is added

            async def handler(event):
                calls.append(event.raw_text)
            message = types.Message(id=7, peer_id=types.PeerUser(5), date=None, message="/status", out=False)
            event = events.NewMessage.Event(message)
            event.original_update = None
            event._entities = {}
            if builder.filter(event):
                await handler(event)
            other = events.NewMessage.Event(types.Message(id=8, peer_id=types.PeerUser(5), date=None, message="/other", out=False))
            other._entities = {}
            assert not builder.filter(other)
            outgoing = events.NewMessage.Event(types.Message(id=9, peer_id=types.PeerUser(5), date=None, message="/status", out=True))
            outgoing._entities = {}
            assert not builder.filter(outgoing)
            assert calls == ["/status"]
        asyncio.run(go())

    def test_raw_requests_match_the_documented_methods(self):
        assert functions.auth.ImportBotAuthorizationRequest(flags=0, api_id=1, api_hash="h", bot_auth_token="t").CONSTRUCTOR_ID == 0x67a3ff2c
        assert functions.account.ResetAuthorizationRequest(hash=1).CONSTRUCTOR_ID == 0xdf77f3bc
        assert functions.auth.ResetAuthorizationsRequest().CONSTRUCTOR_ID == 0x9fab0d1a

    def test_flood_control_around_a_mocked_send(self):
        async def go():
            client = real_client()
            client.send_message = AsyncMock(side_effect=[flood(2), "sent"])
            sleeps = Sleeps()
            result = await rt.call_with_flood_control(lambda: client.send_message("me", "x"), sleep=sleeps, jitter_seconds=0)
            assert result == "sent" and client.send_message.await_count == 2 and sleeps.calls == [2]
        asyncio.run(go())

    def test_string_session_does_not_persist_update_state(self):
        from telethon.crypto import AuthKey
        from telethon.tl.types.updates import State

        session = StringSession()
        session.set_dc(2, "149.154.167.51", 443)
        session.auth_key = AuthKey(b"0" * 256)
        session.set_update_state(0, State(pts=9, qts=0, date=None, seq=1, unread_count=0))
        assert session.get_update_state(0) is not None
        assert StringSession(session.save()).get_update_state(0) is None

    def test_terminal_authorization_errors_exist(self):
        for name in ("AuthKeyUnregisteredError", "SessionRevokedError", "AuthKeyDuplicatedError", "UserDeactivatedError"):
            assert issubclass(getattr(errors, name), errors.RPCError)

    def test_session_string_is_not_in_debug_logs_of_our_helpers(self, caplog, tmp_path):
        caplog.set_level(logging.DEBUG)
        store = rt.EncryptedSessionStore(tmp_path, Fernet.generate_key())
        store.save("a", "TOP-SECRET")
        store.load("a")
        assert "TOP-SECRET" not in caplog.text


DOCS = [SKILL / "references" / n for n in ("mtproto-foundations.md", "mtproto-telethon.md", "hybrid-architecture.md")]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_python_examples_compile(doc):
    blocks = re.findall(r"```python\n(.*?)```", doc.read_text(), re.S)
    for block in blocks:
        compile(block.replace("await ", "").replace("async for", "for"), doc.name, "exec")


def test_named_telethon_errors_and_functions_exist():
    text = "\n".join(p.read_text() for p in DOCS)
    names = set(re.findall(r"`?\b([A-Z][A-Za-z]+Error)\b`?", text)) - {"FloodLimitExceeded", "AttributeError", "PermissionError", "RuntimeError"}
    assert names and all(hasattr(errors, n) for n in names), sorted(n for n in names if not hasattr(errors, n))
    assert hasattr(functions.channels, "GetFullChannelRequest")
    for attribute in ("catch_up", "iter_download", "upload_file", "log_out", "qr_login"):
        assert hasattr(TelegramClient, attribute)


def test_documented_telethon_parameters_exist():
    import inspect
    expected = {"__init__": ("flood_sleep_threshold", "connection_retries", "auto_reconnect", "catch_up", "sequential_updates"),
                "upload_file": ("part_size_kb", "progress_callback"), "iter_download": ("request_size",), "iter_messages": ("wait_time",)}
    for method, names in expected.items():
        parameters = inspect.signature(getattr(TelegramClient, method)).parameters
        assert all(name in parameters for name in names), (method, names)


def test_guidance_separates_capabilities_and_responsibilities():
    foundations = DOCS[0].read_text().lower()
    hybrid = DOCS[2].read_text().lower()
    assert "only users" in foundations and "bot_method_invalid" in foundations
    assert "separate processes" in hybrid and "keep the bot api for the user interface" in hybrid
    assert "never accept a raw method name" in hybrid
    assert "have not been run against live telegram" in hybrid


def test_mtproto_guidance_sets_the_required_boundaries():
    text = "\n".join(p.read_text() for p in DOCS).lower()
    for phrase in ("knowledge and consent", "api_id", "a session is a credential", "evade limits", "peer_flood"):
        assert phrase in text
