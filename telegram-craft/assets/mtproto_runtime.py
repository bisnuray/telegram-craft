"""Safe runtime helpers for Telethon-based MTProto services.

Copy and adapt. Flood handling and the client registry use only the standard
library. The session helpers import Telethon when called; EncryptedSessionStore
requires `cryptography`.

Use only with accounts and bots you are authorized to operate.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import struct
import tempfile
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")
Sleep = Callable[[float], Awaitable[Any]]


class FloodLimitExceeded(RuntimeError):
    """The server asked for a wait longer than this operation may take."""

    def __init__(self, seconds: int, limit: int) -> None:
        super().__init__(f"server requested {seconds}s, limit is {limit}s")
        self.seconds = seconds


async def call_with_flood_control(
    operation: Callable[[], Awaitable[T]],
    max_wait_seconds: int = 120,
    max_attempts: int = 3,
    jitter_seconds: float = 2.0,
    sleep: Sleep = asyncio.sleep,
    on_wait: Callable[[int, int], None] | None = None,
) -> T:
    """Run `operation`, honoring server-requested waits within strict bounds.

    Pass `operation` as a factory, because a coroutine can only be awaited once.
    Only errors exposing an integer `.seconds` (FloodWaitError, SlowModeWaitError)
    are retried. PeerFloodError carries no wait: it signals a restricted account,
    so it propagates and the workflow must stop. Set the client's
    `flood_sleep_threshold=0` so that waits reach this function.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except Exception as error:
            seconds = getattr(error, "seconds", None)
            if not isinstance(seconds, int):
                raise
            if seconds > max_wait_seconds:
                raise FloodLimitExceeded(seconds, max_wait_seconds) from error
            if attempt >= max_attempts:
                raise
            if on_wait is not None:
                on_wait(seconds, attempt)
            await sleep(seconds + random.uniform(0, jitter_seconds))


_SECRETS = [
    (re.compile(r"(?<![A-Za-z0-9_+/-])1[A-Za-z0-9_+/-]{300,}={0,2}"), "<session string>"),  # Telethon StringSession
    (re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{35}\b"), "<bot token>"),
    (re.compile(r"(api_hash[\"']?\s*[=:]\s*[\"']?)[0-9a-f]{32}", re.I), r"\1<api_hash>"),
    (re.compile(r"(?<![\w+])\+\d{7,15}\b"), "<phone>"),
    (re.compile(r"((?:phone_code|login code|code)[\"']?\s*[=:]\s*[\"']?)\d{5,6}\b", re.I), r"\1<code>"),
]


def redact(text: str) -> str:
    """Remove session strings, bot tokens, api_hash values, phone numbers, and login codes from text."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Attach to handlers so credentials never reach log output, even from library code.

        handler.addFilter(RedactingFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


class RecentIds:
    """Bounded memory of handled keys, for updates replayed after a reconnect."""

    def __init__(self, capacity: int = 10_000) -> None:
        self.capacity = capacity
        self._seen: OrderedDict[Any, None] = OrderedDict()

    def first_time(self, key: Any) -> bool:
        if key in self._seen:
            return False
        self._seen[key] = None
        if len(self._seen) > self.capacity:
            self._seen.popitem(last=False)
        return True


class SessionUnavailable(RuntimeError):
    """The account session is missing, malformed, or no longer authorized.

    The fix is a new session from the setup script, never a login at startup.
    """


def string_session_from_env(name: str = "TELEGRAM_SESSION_STRING") -> Any:
    """Build a StringSession from an environment variable, refusing anything unusable.

    An empty StringSession is a brand-new unauthorized session, and starting a client
    with one begins an interactive login, so a missing value must fail here.
    """
    from telethon.sessions import StringSession

    value = os.environ.get(name, "").strip()
    if not value:
        raise SessionUnavailable(f"{name} is not set")
    try:
        session = StringSession(value)
    except (ValueError, struct.error) as error:
        raise SessionUnavailable(f"{name} is not a valid Telethon session string") from error
    if session.auth_key is None:
        raise SessionUnavailable(f"{name} holds no authorization key")
    return session


async def connect_authorized(client: Any) -> None:
    """Connect with an existing session and confirm it is still authorized. Never prompts.

    Use instead of `client.start()`, which asks for a phone number when the
    session is not authorized.
    """
    from telethon import errors

    await client.connect()
    try:
        authorized = await client.is_user_authorized()
    except (errors.UnauthorizedError, errors.AuthKeyError) as error:
        await client.disconnect()
        raise SessionUnavailable(f"Telegram rejected the session ({type(error).__name__})") from error
    if not authorized:
        await client.disconnect()
        raise SessionUnavailable("the session is no longer authorized")


class EncryptedSessionStore:
    """Store Telethon StringSession values encrypted at rest.

    A session string is full account access. Keep the Fernet key in a secret
    manager, never next to the files.
    """

    def __init__(self, directory: str | os.PathLike[str], key: bytes) -> None:
        from cryptography.fernet import Fernet  # optional dependency

        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._fernet = Fernet(key)

    def _path(self, name: str) -> Path:
        if not name or not all(c.isalnum() or c in "-_" for c in name):
            raise ValueError("session name may contain only letters, digits, - and _")
        return self.directory / f"{name}.session.enc"

    def save(self, name: str, session: str) -> None:
        target = self._path(name)
        descriptor, temporary = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(self._fernet.encrypt(session.encode()))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self, name: str) -> str | None:
        target = self._path(name)
        return self._fernet.decrypt(target.read_bytes()).decode() if target.exists() else None

    def delete(self, name: str) -> None:
        """Forget the local copy. Call log_out() first to revoke it on the server."""
        self._path(name).unlink(missing_ok=True)


class ClientRegistry:
    """Own client lifecycle, one live connection per session.

    Using one authorization key from two places can end in AUTH_KEY_DUPLICATED,
    which also invalidates the key, so a duplicate start is refused here.
    """

    def __init__(self, factory: Callable[[str], Any], max_connecting: int = 2) -> None:
        self._factory = factory
        self._clients: dict[str, Any] = {}
        self._starting: set[str] = set()
        self._gate = asyncio.Semaphore(max_connecting)

    async def start(self, name: str) -> Any:
        if name in self._clients or name in self._starting:
            raise RuntimeError(f"session {name!r} is already running")
        self._starting.add(name)
        try:
            client = self._factory(name)
            async with self._gate:
                try:
                    await client.connect()
                    if not await client.is_user_authorized():
                        raise PermissionError(f"session {name!r} is not authorized; sign in interactively")
                except BaseException:  # includes cancellation, so a failed start leaves no connection behind
                    await asyncio.shield(client.disconnect())
                    raise
            self._clients[name] = client
            return client
        finally:
            self._starting.discard(name)

    def get(self, name: str) -> Any:
        return self._clients[name]

    async def stop(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client is not None:
            await client.disconnect()

    async def stop_all(self) -> None:
        names = list(self._clients)
        results = await asyncio.gather(*(self.stop(name) for name in names), return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures:
            raise failures[0]
