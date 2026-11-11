"""Capture real outgoing Telegram calls from simulated bot interactions.

Adapters plug in at the framework's HTTP boundary, so tests exercise real
dispatching and no request leaves the process. `lint_core.py` validates the capture.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BOT_USER = {"id": 999, "is_bot": True, "first_name": "Test Bot", "username": "test_bot", "can_join_groups": True,
            "can_read_all_group_messages": False, "supports_inline_queries": False}
SESSION_STRING = re.compile(r"(?<![A-Za-z0-9_+/-])1[A-Za-z0-9_+/-]{300,}={0,2}")  # never written to captures or reports
SEND_PREFIXES = ("sendMessage", "sendPhoto", "sendVideo", "sendAudio", "sendDocument", "sendAnimation", "sendVoice",
                 "sendVideoNote", "sendSticker", "sendInvoice", "sendLocation", "sendContact", "sendPoll", "sendDice",
                 "sendRichMessage", "copyMessage")


class Recorder:
    """Collects interactions in the order tests ran them."""

    def __init__(self, framework: str = "unknown") -> None:
        self.framework = framework
        self.interactions: list[dict[str, Any]] = []
        self.scenario = "default"
        self.current: dict[str, Any] | None = None
        self.handlers: dict[str, dict[str, Any]] | None = None  # None: the adapter cannot inspect handlers

    def register_handler(self, key: str, event: str, detail: str) -> None:
        if self.handlers is None:
            self.handlers = {}
        self.handlers.setdefault(key, {"key": key, "event": event, "detail": detail, "runs": 0})

    def handler_ran(self, key: str) -> None:
        if self.handlers is not None and key in self.handlers:
            self.handlers[key]["runs"] += 1
        if self.current is not None:
            self.current.setdefault("handlers", []).append(key)

    def begin(self, kind: str, value: Any, chat_type: str, **flags: Any) -> dict[str, Any]:
        self.current = {"scenario": self.scenario, "kind": kind, "value": value, "chat_type": chat_type, "calls": [],
                        **{k: v for k, v in flags.items() if v}}
        self.interactions.append(self.current)
        return self.current

    def save(self, directory: str | os.PathLike[str] = ".tg-lint") -> Path:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"capture-{os.getpid()}.json"
        data: dict[str, Any] = {"version": 1, "framework": self.framework, "interactions": self.interactions}
        if self.handlers is not None:
            data["handlers"] = list(self.handlers.values())
        text = SESSION_STRING.sub("<session string>", json.dumps(data, ensure_ascii=False, indent=1, default=str))
        path.write_text(text, encoding="utf-8")
        return path


_ACTIVE: list[Recorder] = []  # the recorder of the dispatch in progress


def handler_key(function: Any, event: str) -> str:
    """Stable name for a handler, the same across harness instances and closures."""
    target = getattr(function, "__func__", function)
    module = getattr(target, "__module__", None) or "?"
    name = str(getattr(target, "__qualname__", None) or type(target).__name__).split(".<locals>.")[-1]
    return f"{module}:{name}/{event}"


def record_run(key: str) -> None:
    if _ACTIVE:
        _ACTIVE[-1].handler_ran(key)


class BaseHarness:
    """Build Telegram updates, fake API responses, and track the visible keyboard."""

    framework = "unknown"

    def __init__(self, recorder: Recorder, user_id: int = 1000, chat_id: int | None = None, chat_type: str = "private") -> None:
        self.recorder = recorder
        recorder.framework = self.framework
        self.user_id = user_id
        self.chat_type = chat_type
        self.chat_id = chat_id if chat_id is not None else (user_id if chat_type == "private" else -100123)
        self.file_bytes = b"test file"
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[str, Any] = {}
        self.failures: dict[str, deque] = defaultdict(deque)
        self._ids = {"message": 100, "update": 1, "callback": 1}
        self.keyboard: list[list[dict[str, Any]]] = []
        self.keyboard_message_id: int | None = None

    # Test controls ------------------------------------------------------------
    @contextmanager
    def scenario(self, name: str):
        previous, self.recorder.scenario = self.recorder.scenario, name
        try:
            yield self
        finally:
            self.recorder.scenario = previous

    def respond(self, method: str, result: Any) -> None:
        """Set the fake result for a method the default does not model."""
        self.responses[method] = result

    def fail_next(self, method: str, description: str, error_code: int = 400, retry_after: int | None = None) -> None:
        self.failures[method].append({"description": description, "error_code": error_code, "retry_after": retry_after})

    @property
    def labels(self) -> list[str]:
        return [button.get("text", "") for row in self.keyboard for button in row]

    def sent(self, method: str) -> list[dict[str, Any]]:
        return [call["params"] for call in self.calls if call["method"] == method]

    @property
    def last_text(self) -> str | None:
        for call in reversed(self.calls):
            params = call["params"]
            if params.get("text") and call["method"] != "answerCallbackQuery":
                return params["text"]
        return None

    # Simulated user actions ---------------------------------------------------
    async def command(self, text: str, expected_silence: bool = False, expected_error: bool = False) -> None:
        size = len(text.split()[0])
        message = self._message(text=text, entities=[{"type": "bot_command", "offset": 0, "length": size}])
        await self._run("command", text, {"message": message}, expected_silence=expected_silence, expected_error=expected_error)

    async def text(self, text: str, expected_silence: bool = False, expected_error: bool = False) -> None:
        await self._run("text", text, {"message": self._message(text=text)}, expected_silence=expected_silence, expected_error=expected_error)

    async def press(self, label: str) -> None:
        """Tap a button that is actually on the current keyboard."""
        for row in self.keyboard:
            for button in row:
                if button.get("text") == label:
                    if "callback_data" not in button:
                        raise AssertionError(f"{label!r} is not a callback button: {button}")
                    await self.callback(button["callback_data"])
                    return
        raise AssertionError(f"no button {label!r} on the current keyboard; visible: {self.labels}")

    async def callback(self, data: str, expected_error: bool = False, user_id: int | None = None) -> None:
        """Send callback data directly, for stale or forged buttons."""
        self._ids["callback"] += 1
        sender = user_id if user_id is not None else self.user_id
        message = self._message(text="previous", message_id=self.keyboard_message_id or self._next("message"), from_user=BOT_USER)
        query = {"id": str(self._ids["callback"]), "from": self._user(sender), "chat_instance": "ci", "data": data, "message": message}
        await self._run("callback", data, {"callback_query": query}, expected_error=expected_error)

    async def media(self, field: str, attachment: dict[str, Any], caption: str | None = None, expected_error: bool = False) -> None:
        file = {"file_id": "f1", "file_unique_id": "u1", **attachment}
        message = self._message(**{field: [file] if field == "photo" else file}, **({"caption": caption} if caption else {}))
        await self._run("media", field, {"message": message}, expected_error=expected_error)

    async def pre_checkout(self, payload: str, total: int, currency: str = "XTR") -> None:
        query = {"id": "pc1", "from": self._user(self.user_id), "currency": currency, "total_amount": total, "invoice_payload": payload}
        await self._run("pre_checkout", payload, {"pre_checkout_query": query})

    async def successful_payment(self, payload: str, total: int, charge_id: str = "charge-1", currency: str = "XTR", **extra: Any) -> None:
        payment = {"currency": currency, "total_amount": total, "invoice_payload": payload, "telegram_payment_charge_id": charge_id,
                   "provider_payment_charge_id": "", **extra}
        await self._run("payment", payload, {"message": self._message(successful_payment=payment)})

    async def raw_update(self, update: dict[str, Any], kind: str = "update", value: str = "", expected_error: bool = False) -> None:
        await self._run(kind, value, update, expected_error=expected_error)

    # Internals -----------------------------------------------------------------
    def _next(self, name: str) -> int:
        self._ids[name] += 1
        return self._ids[name]

    def _user(self, user_id: int) -> dict[str, Any]:
        return {"id": user_id, "is_bot": False, "first_name": "Test", "language_code": "en"}

    def _chat(self) -> dict[str, Any]:
        chat: dict[str, Any] = {"id": self.chat_id, "type": self.chat_type}
        if self.chat_type == "private":
            chat["first_name"] = "Test"
        else:
            chat["title"] = "Test chat"
        return chat

    def _message(self, message_id: int | None = None, from_user: dict | None = None, **fields: Any) -> dict[str, Any]:
        return {"message_id": message_id if message_id is not None else self._next("message"), "date": int(time.time()),
                "chat": self._chat(), "from": from_user or self._user(self.user_id), **fields}

    async def _run(self, kind: str, value: Any, payload: dict[str, Any], **flags: Any) -> None:
        record = self.recorder.begin(kind, value, self.chat_type, **flags)
        update = {"update_id": self._next("update"), **payload}
        _ACTIVE.append(self.recorder)
        try:
            await self._dispatch(update)
        except Exception as exc:  # recorded so the gate can report it with context
            record["error"] = f"{type(exc).__name__}: {exc}"
            if not flags.get("expected_error"):
                raise
        finally:
            _ACTIVE.remove(self.recorder)

    async def _dispatch(self, update: dict[str, Any]) -> None:
        raise NotImplementedError

    def handle_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Record one outgoing API call and build Telegram's JSON response."""
        clean = {k: v for k, v in params.items() if v is not None}
        call = {"method": method, "params": clean}
        self.calls.append(call)
        if self.recorder.current is not None and method != "getMe":
            self.recorder.current["calls"].append(call)
        if self.failures[method]:
            failure = self.failures[method].popleft()
            body: dict[str, Any] = {"ok": False, "error_code": failure["error_code"], "description": failure["description"]}
            if failure["retry_after"] is not None:
                body["parameters"] = {"retry_after": failure["retry_after"]}
            return body
        result = self.responses[method] if method in self.responses else self._default_result(method, clean)
        self._track_keyboard(method, clean, result)
        return {"ok": True, "result": result}

    def _default_result(self, method: str, params: dict[str, Any]) -> Any:
        if method == "getMe":
            return BOT_USER
        if method == "getFile":
            return {"file_id": params.get("file_id", "f1"), "file_unique_id": "u1", "file_size": len(self.file_bytes), "file_path": "files/test"}
        if method == "createInvoiceLink":
            return "https://t.me/$test_invoice"
        if method == "sendMediaGroup":
            return [self._bot_message() for _ in params.get("media", [])]
        if method.startswith("edit"):
            return self._bot_message(message_id=params.get("message_id"), text=params.get("text"))
        if method.startswith(SEND_PREFIXES):
            return self._bot_message(text=params.get("text") or params.get("caption"))
        return True

    def _bot_message(self, message_id: int | None = None, text: Any = None) -> dict[str, Any]:
        fields = {"text": text} if isinstance(text, str) else {"text": "ok"}
        return self._message(message_id=message_id, from_user=BOT_USER, **fields)

    def _track_keyboard(self, method: str, params: dict[str, Any], result: Any) -> None:
        if not (method.startswith(SEND_PREFIXES) or method.startswith("edit")):
            return
        markup = params.get("reply_markup")
        if isinstance(markup, str):
            markup = json.loads(markup)
        if isinstance(markup, dict) and "inline_keyboard" in markup:
            self.keyboard = markup["inline_keyboard"]
            self.keyboard_message_id = result.get("message_id") if isinstance(result, dict) else None
        elif method.startswith("edit") and params.get("message_id") == self.keyboard_message_id:
            self.keyboard = []
