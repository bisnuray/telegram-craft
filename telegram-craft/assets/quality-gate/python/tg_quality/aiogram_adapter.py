"""Run an aiogram 3 dispatcher against a fake Telegram session."""
from __future__ import annotations

import json
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import Default, DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.types import InputFile, Update

from . import BaseHarness, Recorder, handler_key, record_run

SKIPPED_EVENTS = {"update", "error"}  # the dispatcher's own update listener, and error handlers


class _CaptureSession(BaseSession):
    def __init__(self, harness: AiogramHarness) -> None:
        super().__init__()
        self.harness = harness

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: Any, timeout: Any = None) -> Any:  # noqa: ASYNC109 - aiogram's BaseSession signature
        params = _plain(bot, method.model_dump(warnings=False))
        body = self.harness.handle_call(method.__api_method__, params)
        status = 200 if body["ok"] else body["error_code"]
        return self.check_response(bot=bot, method=method, status_code=status, content=json.dumps(body)).result

    async def stream_content(self, url: str, headers: Any = None, timeout: int = 30,  # noqa: ASYNC109 - aiogram's BaseSession signature
                              chunk_size: int = 65536, raise_for_status: bool = True):
        yield self.harness.file_bytes


def _plain(bot: Bot, value: Any) -> Any:
    """Resolve aiogram's default sentinels, so the capture matches the wire."""
    if isinstance(value, Default):
        return bot.default[value.name]
    if isinstance(value, InputFile):
        return "<InputFile>"
    if isinstance(value, dict):
        cleaned = {k: _plain(bot, v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v is not None}
    if isinstance(value, list):
        return [_plain(bot, item) for item in value]
    return value


class AiogramHarness(BaseHarness):
    framework = "aiogram"

    def __init__(self, dispatcher: Dispatcher, recorder: Recorder, default: DefaultBotProperties | None = None,
                 workflow_data: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(recorder, **kwargs)
        self.dispatcher = dispatcher
        self.workflow_data = workflow_data or {}
        self.bot = Bot("123456:TEST-TOKEN", session=_CaptureSession(self), default=default)
        instrument(dispatcher, recorder)

    async def _dispatch(self, update: dict[str, Any]) -> None:
        parsed = Update.model_validate(update, context={"bot": self.bot})
        await self.dispatcher.feed_update(self.bot, parsed, **self.workflow_data)


def _routers(router: Any) -> list[Any]:
    found = [router]
    for child in getattr(router, "sub_routers", []):
        found += _routers(child)
    return found


def _describe_magic(magic: Any) -> str:
    text = "F"
    for operation in getattr(magic, "_operations", ()):
        kind = type(operation).__name__
        if kind == "GetAttributeOperation":
            text += f".{operation.name}"
        elif kind == "CallOperation":
            text += "(" + ", ".join(repr(a) for a in operation.args) + ")"
        elif kind == "ComparatorOperation":
            text += f" {getattr(operation.comparator, '__name__', '?')} {operation.right!r}"
        elif kind == "FunctionOperation":
            text += f".{getattr(operation.function, '__name__', 'fn')}(" + ", ".join(repr(a) for a in operation.args) + ")"
        else:
            text += ".?"
    return text


def _describe_filter(item: Any) -> str:
    magic = getattr(item, "magic", None)
    if magic is not None:
        return _describe_magic(magic)
    target = item.callback
    commands = getattr(target, "commands", None)
    if commands:
        return type(target).__name__ + "(" + ", ".join(str(getattr(c, "command", c)) for c in commands) + ")"
    if type(target).__name__ == "StateFilter":
        return "StateFilter(" + ", ".join(str(getattr(s, "state", s)) for s in getattr(target, "states", ())) + ")"
    if type(target).__name__ == "CommandStart":
        return "CommandStart"
    return type(target).__name__ if not callable(target) or hasattr(target, "__self__") or not hasattr(target, "__name__") else target.__name__


def instrument(dispatcher: Dispatcher, recorder: Recorder) -> None:
    """Register every handler with the recorder and count its runs. Dispatching is unchanged."""
    for router in _routers(dispatcher):
        for event, observer in router.observers.items():
            if event in SKIPPED_EVENTS:
                continue
            for handler in observer.handlers:
                key = handler_key(handler.callback, event)
                detail = ", ".join(_describe_filter(f) for f in handler.filters or []) or "no filters"
                recorder.register_handler(key, event, detail)
                if getattr(handler, "_tg_counted", False):
                    continue
                original = handler.call

                async def counted(*args: Any, _original: Any = original, _key: str = key, **kwargs: Any) -> Any:
                    record_run(_key)
                    return await _original(*args, **kwargs)

                handler.call = counted
                handler._tg_counted = True
