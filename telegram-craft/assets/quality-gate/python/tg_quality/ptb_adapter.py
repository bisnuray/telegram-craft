"""Run a python-telegram-bot Application against a fake HTTP layer."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from telegram import Update
from telegram.ext import Application, ContextTypes
from telegram.request import BaseRequest

from . import BaseHarness, Recorder, handler_key, record_run


class _CaptureRequest(BaseRequest):
    def __init__(self, harness: PTBHarness) -> None:
        self.harness = harness

    @property
    def read_timeout(self) -> float:
        return 1.0

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def do_request(self, url: str, method: str, request_data: Any = None, read_timeout: Any = None,
                         write_timeout: Any = None, connect_timeout: Any = None, pool_timeout: Any = None) -> tuple[int, bytes]:
        if method == "GET" and "/file/bot" in url:
            return 200, self.harness.file_bytes
        name = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data is not None else {}
        body = self.harness.handle_call(name, params)
        return (200 if body["ok"] else body["error_code"]), json.dumps(body).encode()


class PTBHarness(BaseHarness):
    framework = "python-telegram-bot"

    def __init__(self, register: Callable[[Application], None], recorder: Recorder, **kwargs: Any) -> None:
        super().__init__(recorder, **kwargs)
        request = _CaptureRequest(self)
        self.app = Application.builder().token("123456:TEST-TOKEN").request(request).get_updates_request(_CaptureRequest(self)).updater(None).build()
        register(self.app)
        instrument(self.app, recorder)
        self.app.add_error_handler(self._on_error)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        current = self.recorder.current
        if current is not None and context.error is not None:
            current["error"] = f"{type(context.error).__name__}: {context.error}"

    async def __aenter__(self) -> PTBHarness:
        await self.app.initialize()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.app.shutdown()

    async def _dispatch(self, update: dict[str, Any]) -> None:
        await self.app.process_update(Update.de_json(update, self.app.bot))


def _describe(handler: Any) -> str:
    kind = type(handler).__name__
    commands = getattr(handler, "commands", None)
    if commands:
        return "/" + ", /".join(sorted(commands))
    pattern = getattr(handler, "pattern", None)
    if pattern is not None:
        return f"{kind}(pattern={getattr(pattern, 'pattern', getattr(pattern, '__name__', pattern))!r})"
    filters = getattr(handler, "filters", None)
    if filters is not None and kind == "MessageHandler":
        return f"MessageHandler({filters})"
    return kind


def _flatten(handler: Any, state: str = "") -> list[tuple[Any, str]]:
    """Expand ConversationHandler into its entry points, states, and fallbacks."""
    if type(handler).__name__ != "ConversationHandler":
        return [(handler, state)]
    found: list[tuple[Any, str]] = []
    for inner in handler.entry_points:
        found += _flatten(inner, f"{state}entry ")
    for name, inners in handler.states.items():
        for inner in inners:
            found += _flatten(inner, f"{state}state {name} ")
    for inner in handler.fallbacks:
        found += _flatten(inner, f"{state}fallback ")
    return found


def instrument(app: Application, recorder: Recorder) -> None:
    """Register every handler with the recorder and count its runs. Matching is unchanged."""
    for group in app.handlers.values():
        for top in group:
            for handler, state in _flatten(top):
                callback = getattr(handler, "callback", None)
                if callback is None:
                    continue
                original = getattr(callback, "_tg_original", callback)
                event = type(handler).__name__
                key = handler_key(original, event)
                recorder.register_handler(key, event, (state + _describe(handler)).strip())
                if getattr(callback, "_tg_original", None) is not None:
                    continue

                async def counted(update: Any, context: Any, _original: Any = original, _key: str = key) -> Any:
                    record_run(_key)
                    return await _original(update, context)

                counted._tg_original = original
                handler.callback = counted
