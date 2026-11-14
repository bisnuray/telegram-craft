# Code quality

Use when writing, refactoring, or reviewing the Python code of a bot, MTProto client, or backend. Mini App frontend code: `mini-apps.md`. The project's own conventions (its rules file, linter config, and the code around your change) override anything here; match them.

## Contents

- [Size the design to the product](#size-the-design-to-the-product)
- [Names and functions](#names-and-functions)
- [Comments and docstrings](#comments-and-docstrings)
- [Errors](#errors)
- [Async lifecycle](#async-lifecycle)
- [Logging and types](#logging-and-types)
- [Tooling](#tooling)
- [Review before handoff](#review-before-handoff)

## Size the design to the product

Choose the smallest structure that keeps each responsibility in one obvious place.

| Product | Shape |
|---|---|
| Utility bot: one or two commands, no storage | A small package: `bot.py` (handlers and startup) plus a module for the real logic, such as `money.py`. No services layer |
| Product bot: several flows, storage, payments | The layout in `backend.md`: handlers, keyboards, texts, services, storage |
| Platform: several bots, workers, a Mini App backend | Separate deployables that share a domain package. Boundaries follow what changes and scales separately |

- **Handlers are transport.** They parse the update, call one function that does the work, and send the result. Business rules a test needs to reach live outside the handler.
- **No abstraction without a second real use.** No `ABC` or `Protocol` with one implementation, no factory that returns one class, no `*Manager` or `*Service` wrapping two functions, no config flag nothing sets. Add them when the second case arrives.
- **Dependencies come from the framework.** aiogram workflow data and middlewares, python-telegram-bot `bot_data`, grammY context. No module-level mutable globals and no hand-rolled DI container.
- **No placeholders.** Do not create empty packages, `pass` bodies, or `TODO: implement` stubs for later. Build what was asked, completely.

Before (over-engineered):

```python
class AbstractPaymentProcessor(ABC):
    @abstractmethod
    def parse_payload(self, payload): ...


class StarsPaymentProcessor(AbstractPaymentProcessor):
    def parse_payload(self, payload):
        data2 = payload.split(":")  # Split the payload
        ...


class PaymentProcessorFactory:
    @staticmethod
    def create():
        return StarsPaymentProcessor()  # Create the processor


async def handle_basic(callback, ledger):
    if callback.data == "buy:basic":
        await do_it(callback, ledger, "basic")
# ...the same function again for "pro" and "max"
```

After:

```python
class Purchase(NamedTuple):
    plan: str
    user_id: int


def parse_payload(payload: str) -> Purchase | None:
    plan, _, user_id = payload.partition(":")
    if plan not in PLANS or not user_id.isdigit():
        return None
    return Purchase(plan, int(user_id))


async def on_buy(callback: CallbackQuery, ledger: Ledger) -> None:
    plan = (callback.data or "").removeprefix(BUY_PREFIX)
    if plan not in PLANS:
        return
    ...
```

One parser function, one handler for every plan, a typed result, and nothing to configure.

## Names and functions

- A name says what a value holds or what a function does: `share_per_person`, `parse_payload`, `grant_once`. Not `data`, `result`, `temp`, `obj`, `info`, `do_it`, `handle_thing`, `proc`, or single letters outside comprehensions.
- Handler names follow the project's pattern (`on_buy`, `cmd_start`, `stats`). Keep them.
- One function, one level of abstraction. Return early instead of nesting.
- Review signals, not hard limits: a function past about 40 lines, nesting past three levels, more than five parameters, a boolean parameter that switches behavior, or the same five lines in two places. Each one asks "would splitting this make it clearer?" Sometimes the answer is no.
- Shorter is not the goal. A clear eight-line loop beats a clever one-line comprehension.

## Comments and docstrings

A comment earns its place when it tells the reader something the code cannot: why, not what.

Delete:

```python
# Import asyncio
import asyncio

# Create the client
client = TelegramClient(...)

# ===================== HANDLERS =====================

# Return the result
return user
```

Also delete commented-out code, `TODO` placeholders for unbuilt features, banner and section comments, and tutorial explanations. If a comment is needed to explain *what* a block does, give the block a function with a name instead.

Keep, and write, comments like these:

```python
# Telegram cancels the payment if pre-checkout is not answered within 10 seconds,
# so only the payload is checked here.

# Telegram may deliver the same successful_payment more than once; grant by charge id.

# Bot sessions cannot call messages.getHistory; this path needs the user client.

# disconnect, not log_out: logging out would revoke the reusable session.

# Cancel the poller before closing the HTTP session, or its last request fails.
```

- Docstrings for public functions and classes whose contract is not obvious from the signature: arguments with constraints, side effects, what is raised. Not on every private helper.
- When editing existing code, keep its comments that carry context, even long ones. Remove only comments that are wrong or restate the code, and update comments next to code you change.
- Match the comment style already in the file.

## Errors

- Catch only what you can handle, where you can handle it. Typical expected errors:
  - Bot API: `TelegramBadRequest` "message is not modified" (ignore), `TelegramForbiddenError` (user blocked the bot: stop for that chat), and `TelegramRetryAfter` (wait `retry_after`).
  - MTProto: `FloodWaitError` (`call_with_flood_control`), and `UnauthorizedError` (terminal: stop and alert).
- Everything else propagates to **one** error boundary that logs with the traceback and, for user actions, sends a short apology: aiogram `@router.errors()`, python-telegram-bot `add_error_handler`, grammY `bot.catch`.
- Never `except Exception: pass`, and never return a fake success (`[]`, `None`, `{"ok": True}`) from a failure. A swallowed error after a payment loses money silently.
- Never swallow cancellation. `asyncio.CancelledError` is a `BaseException`; a bare `except:` or `except BaseException:` must re-raise. Do not catch `CancelledError` except to clean up and re-raise.
- `raise NewError(...) from error` keeps the cause. Error text goes to logs; the user gets a short message that says what to do.
- The floor, never cut for simplicity:
  - validation at trust boundaries (`initData`, callback data, payloads);
  - idempotency for payments and updates;
  - authorization checks;
  - output escaping;
  - secret handling.

  Removing one is a behavior change, not a cleanup.

## Async lifecycle

- **Every task has an owner.** Use `asyncio.TaskGroup` for work that must finish together. For background workers, keep the task, cancel it on shutdown, and await it. A bare `asyncio.create_task(...)` whose result is dropped can be garbage-collected mid-run and hides its exceptions.
- **Every network call has a timeout.** Set `aiohttp.ClientTimeout` on the session, `request_timeout` in the bot library, or `asyncio.timeout()` around the call.
- **Retries are bounded:** a maximum count, exponential backoff with jitter, and `retry_after` honored. Never retry a 400; fix the request. Patterns: `delivery.md`.
- **No blocking calls in `async def`:** `time.sleep`, `requests`, synchronous database drivers, and `subprocess.run`. Use the async client, or `asyncio.to_thread` once at the boundary.
- **Open resources where they are owned:** `async with aiohttp.ClientSession()` inside the worker, not in `__init__`. One session per process or worker, not per request.
- **Shutdown, in order:**
  1. stop taking updates;
  2. cancel and await workers;
  3. close HTTP sessions and database pools;
  4. close the bot session or `await client.disconnect()`.

  Wire this to the framework's shutdown hook or a `finally:`.

```python
class PriceWatcher:
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="price-watcher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            while True:
                try:
                    await self._check(session)
                except (aiohttp.ClientError, TimeoutError) as error:
                    log.warning("price request failed: %s", error)
                await asyncio.sleep(self.interval)
```

## Logging and types

- `log = logging.getLogger(__name__)` per module; configure handlers once at startup. No `print` in application code.
- Pass values as arguments: `log.info("granted %s to user %s", plan, user_id)`. Log `log.exception` once at the error boundary, not at every layer.
- Log ids and outcomes, never tokens, session strings, `api_hash`, phone numbers, login codes, payment details, or message text by default. MTProto services add `RedactingFilter` (`assets/mtproto_runtime.py`).
- Annotate public functions and handler parameters. Use dataclasses or `NamedTuple` for structured values instead of loose dicts and tuples, and `X | None` for absence. Use the type checker the project already runs; do not add one to a small script.

## Tooling

Tools enforce what they can, so review time goes to design. Use what the project already has. For a new project, or one without a linter, copy `assets/ruff.template.toml` to the project root as `ruff.toml` (or put its tables under `[tool.ruff]` in `pyproject.toml`) and run:

```bash
ruff check .            # errors to fix, not to silence
ruff format --check .   # only if the project formats with Ruff; keep Black if it uses Black
python3 <skill>/scripts/tg_audit.py .
```

| Ruff rules | Catch |
|---|---|
| `F401`, `F841`, `ERA001`, `PIE790` | Unused imports and variables, commented-out code, placeholder `pass` |
| `E722`, `BLE001`, `S110`, `S112` | Bare, blind, and empty exception handlers |
| `RUF006`, `ASYNC2xx`, `ASYNC109`, `ASYNC110` | Dropped tasks, blocking calls in async code, homemade timeouts and busy waits |
| `S105`, `S106`, `S602`, `S604` | Hard-coded secrets, shell injection |
| `C901`, `PLW0603`, `T201`, `G004` | Complex functions, global state, `print`, f-strings in log calls |

`tg_audit.py` adds what Ruff cannot see: swallowed cancellation, a user-account client started with `start()` at runtime, `StringSession` from a possibly empty variable, `log_out()` outside setup, plus its Telegram checks: unanswered callbacks, webhooks without a secret, unverified `initData`, blocking calls, and payments without a charge id. Fix a finding or explain it in the handoff. Never weaken a gate to pass it: no `# noqa` without a reason, no lowered thresholds, no skipped tests.

## Review before handoff

Read the diff as its reviewer would:

1. Does each module have one job, sized to the product? Is there an abstraction, file, or option with no present use?
2. Would a new teammate understand each name without the comment next to it?
3. Comments: does every remaining comment say something the code cannot? Were context comments in edited code kept?
4. Are expected errors handled narrowly, unexpected ones visible at one boundary, cancellation propagated, and the floor intact?
5. Does every task, session, and client have an owner that closes it on shutdown? Does every network call have a timeout and every retry a limit?
6. Do Ruff, `tg_audit.py`, the tests, and the quality gate pass, with no new suppressions?

Reject these rationalizations:

| Thought | Reality |
|---|---|
| "An interface now makes it extensible later" | Later has its own requirements. Add the interface when the second implementation exists |
| "The comment helps beginners" | Production code is read by the team. Name things well instead |
| "`except Exception` keeps the bot alive" | The error boundary keeps it alive; a local catch-all hides the bug that will cost money |
| "Fewer lines is cleaner" | Clarity is the goal. A longer explicit version often reads faster |
| "I'll clean up the code next to mine too" | Refactor what the task touches. Ask before broad changes |
