# Testing and review

Use for tests, journey verification, and pre-release review.

## Test the journey through the real dispatcher

Unit tests for services are useful. Most Telegram bugs, though, live at the seams: filters, routing, callback data, and state. Feed real `Update` objects through the real dispatcher, with only the HTTP layer faked.

```python
class FakeSession(AiohttpSession):
    """Records outgoing Bot API calls instead of sending them."""
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        return fake_result_for(method)   # True or a Message, per method.__returning__
```

Construct `Bot("123:TEST", session=FakeSession())`, then `await dp.feed_update(bot, update)`. Assert on `session.calls`. Build updates with real model classes so that validation runs. For python-telegram-bot, use `application.process_update` with a custom `BaseRequest`. For grammY, use `bot.api.config.use(...)` as a transformer that records calls, and set `botInfo` so `init` isn't needed.

## Journey checklist

Include those that apply, not all by default:

- First `/start`, returning `/start`, deep link valid and invalid
- Main flow to a visible result and a database change
- Every button on the screen map leads somewhere and answers the callback
- Back keeps context; Cancel clears state
- Wrong input type mid-flow; `/cancel` mid-flow
- Empty state; last page; out-of-range page
- Stale callback: deleted object, changed state, old format, garbage data
- Other user's object; revoked role; group non-owner tapping
- Double tap, redelivered update, concurrent action
- Text containing `<`, `&`, emoji, long names, RTL text
- Restart mid-flow, with persistent storage
- API errors: 429, 403 blocked, `message is not modified`, timeout
- Payments: duplicate, mismatch, crash before delivery, refund, expiry
- Media: corrupt, oversize, timeout, cancel, temp cleanup
- Mini App: forged, expired, or tampered init data; another user's object

## Test quality

- A test must fail when the behavior breaks. Check by temporarily breaking the code on critical paths.
- Assert exact API calls and arguments, not merely that nothing raised.
- Use controlled barriers to test races, not sleeps.
- Use a temporary real database for state logic, so that constraints apply.

## Visual checks

For bots, use the automatic gate in `quality-gate.md`. If it cannot be installed, lint what the bot really sends by dumping recorded calls to a file for `scripts/tg_lint.py`:

```python
DEFAULT_PARSE_MODE = "HTML"  # whatever the Bot was created with; aiogram stores a sentinel otherwise
screens = [
    {
        "text": call.text,
        "parse_mode": call.parse_mode if isinstance(call.parse_mode, str) else DEFAULT_PARSE_MODE,
        "reply_markup": call.reply_markup.model_dump(exclude_none=True) if call.reply_markup else None,
    }
    for call in session.calls
    if isinstance(call, (SendMessage, EditMessageText))
]
Path("screens.json").write_text(json.dumps(screens, ensure_ascii=False))
```

Any copy or keyboard change should get this check. Then read each screen at phone width.

For Mini Apps, take screenshots with a browser tool and `assets/webapp_mock.js`, at two sizes and in two themes, and look at them. See `mini-app-design.md`.

## Review procedure

1. Run `scripts/tg_audit.py PROJECT`. These are leads.
2. Read the code at each lead. Confirm it's reachable, or drop it. Look for what a scan can't see: authorization on each callback, race conditions, payment logic, deployment settings.
3. Report by severity, with `file:line`, impact, and fix. State what wasn't checked.

| Severity | Examples |
|---|---|
| **P0** | Token exposed; forged initData accepted; paid goods without payment or twice; authorization bypass; SQL or command injection |
| **P1** | Lost updates or payments; event loop blocked; crash on user input (`<` in a name); no webhook secret; 429 handling that drops work |
| **P2** | Dead ends; unanswered callback paths; stale-button errors; leaking temp files; no shutdown handling |
| **P3** | Copy, label consistency, minor UX, and maintainability |

Check beyond code too:

| Area | Questions |
|---|---|
| Messages | First line carries the point? Errors say what to do? Terms consistent? |
| Keyboards | Clear labels, one main action, Back and Cancel coherent, stale actions recover? |
| Platform | Features available in the installed SDK and at the right Bot API version? Limits respected? |
| Architecture | Proportionate to the bot? Blocking calls? State durable? |
| Operations | Secrets, logs, shutdown, one consumer, monitoring? |
| Mini App | Validated auth, theme, safe area, native controls, states, contrast, real-device test? |

## Evidence

Report what you ran and what you saw, with the L0–L3 level from `SKILL.md`. "Not tested on a real client" is an acceptable statement. Implying otherwise isn't.
