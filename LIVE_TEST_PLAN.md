# Live validation plan

This plan has not been run. Nothing in it may start until the owner gives explicit authorization for the specific stage. Everything verified so far is offline (evidence level L2 at most).

Never paste credentials into a chat, an issue, a log, or a repository.

## Stages and order

Each stage needs its own go-ahead. Stop at the first failed exit criterion.

| Stage | Needs | Risk | Exit criterion |
|---|---|---|---|
| 0. Isolation check | Dedicated host or container | None | Preflight passes; no production service, token, or session reachable |
| 1. Test bot, Bot API | Test bot token | Low | Message, keyboard, and error journeys pass in a real client |
| 1b. Rich screen review | Stage 1 | None | Every screen's recipe renders as designed; screenshots recorded |
| 2. Mini App launch | Test bot, HTTPS test URL | Low | Real `initData` accepted; tampered rejected |
| 3. Stars purchase and refund | Stage 1, test environment | Low if test environment only | Purchase grants once; refund reverses once |
| 4. MTProto bot session | `api_id`/`api_hash`, test bot | Low | Sign-in, one small download, clean shutdown |
| 5. MTProto user session | Dedicated test account | Medium: account limits | Sign-in, Saved Messages read, revocation |
| 6. Media transfer | Stage 4 | Low; uses bandwidth | Transfer above the Bot API limit, verified by hash |
| 7. Hybrid | Stages 1 and 4 | Low | Bot stays responsive during transfer; Cancel works |

## Accounts

- **Test bot:** a new bot created for this purpose. Never reuse a production bot, because only one consumer can read its updates.
- **Prefer Telegram's test environment** for bots and Stars. It has separate accounts and data. Bot API calls use `https://api.telegram.org/bot<token>/test/METHOD`. aiogram uses `AiohttpSession(api=aiogram.client.telegram.TEST)`.
- **MTProto test accounts:** use Telegram's [test servers](https://core.telegram.org/api/auth#test-accounts). Read that page again on the day, since the phone number format and DC details are defined there. Use a production-network account only if a test server cannot exercise the behavior, and only an account the owner controls and can afford to lose.
- **Never** use a real user's account, a borrowed session, or a production session string.

## Minimum configuration

The owner sets these values on the test host. They stay out of the repository and out of this conversation.

| Variable | Stage | Purpose |
|---|---|---|
| `TG_LIVE_AUTHORIZED` | All | Must equal the stage name being run, such as `stage-3`. Absent means the suite refuses to run. |
| `TG_TEST_BOT_TOKEN` | 1–4, 6, 7 | Test bot only |
| `TG_TEST_ENV` | 1–3 | `1` routes Bot API calls to the test environment |
| `TG_TEST_CHAT_ID` | 1, 4, 6, 7 | A private test chat or group |
| `TG_TEST_USER_ID` | 1–3 | The numeric id of the tester |
| `TG_MINI_APP_URL` | 2 | HTTPS URL of a disposable deployment |
| `TG_API_ID`, `TG_API_HASH` | 4–7 | The owner's own app from my.telegram.org. Never from a library example. |
| `TG_TEST_SESSION_DIR` | 4–7 | Directory, mode 0700, outside the repository |
| `TG_SESSION_KEY` | 5 | Fernet key for `EncryptedSessionStore`, from a secret manager or an owner-only file |
| `TG_LIVE_MAX_MESSAGES` | All | Upper limit on sends per run; default 50 |

Store them in a mode 0600 file outside the repository and load it with `set -a; . /path/to/file; set +a` in the session that runs the suite.

## Safety controls

- Preflight must refuse to run if `TG_LIVE_AUTHORIZED` is wrong, if the bot's `getMe` id is not on an owner-provided allowlist, or if `getWebhookInfo` shows a webhook URL (it may belong to something else).
- Send only to `TG_TEST_CHAT_ID`. No broadcasts, no joining chats, no contact imports, no messages to third parties.
- Sequential only: one bot consumer and one connection per session. A second connection on one session can invalidate its authorization key.
- A `FLOOD_WAIT` above 60 seconds or any `PEER_FLOOD` aborts the stage. Never retry past either.
- Redact tokens, API hashes, phone numbers, codes, 2FA passwords, and session strings from all logs. Scan the logs for these values before keeping them.
- No live money. Stars purchases run only in the test environment unless the owner separately authorizes a named, single real purchase and its refund.
- Run under a memory limit on a host without production services. This server is not suitable: it has about 1 GB free, no swap, and live bots.

## Stage detail

### 1. Test bot

Run through a real client on one phone and one desktop:

- `/start`, every keyboard, Back and Cancel, pagination, stale buttons, and error messages.
- Compare each message Telegram accepted with what the quality gate approved. Any payload the gate passed and Telegram refused is a gate defect. Any payload the gate failed and Telegram accepted is a false positive.
- Force one real `429` only if a harmless method can do it within `TG_LIVE_MAX_MESSAGES`. Otherwise record it as untested.

### 1b. Rich screen review

Send every screen in the screen map through the test bot, then screenshot each one:
- in Telegram for Android or iOS, and in Telegram Desktop;
- in a light and a dark theme;
- at the default text size and one size larger.

Check each screen against its recipe in `rich-recipes.md`:
- Table borders show on every cell, including the total rows.
- No cell is hidden, and no column is cut off on the phone.
- Headings and dividers sit where the recipe puts them.
- `<tg-time>` shows the reader's local time.
- The keyboard sits directly under the content.

Also check two cases:
- An edit from one screen to another keeps the message in place.
- An older client, or one that cannot show rich messages, receives the formatted HTML fallback.

Only a screenshot of a real Telegram client counts as visual proof. A rebuilt image, an HTML preview, or the gate's capture does not. Store the screenshots outside the repository if they show real chat names.

### 2. Mini App

- Launch from the keyboard button, menu button, and direct link, on iOS, Android, and desktop if available.
- Send the real raw `initData` to the backend. Confirm acceptance, then rejection with one changed character and after `auth_date` expiry.
- Confirm theme changes, safe areas, and the native Back button. These are human checks.

### 3. Stars purchase and refund

Using the test environment:

1. Create an invoice and pay in a real client. Confirm no grant at pre-checkout, then one grant on `successful_payment`.
2. Replay the stored update through the handler. Confirm no second grant.
3. Call `refundStarPayment`. Confirm reversal. Repeat it and confirm no second reversal.
4. Record whether a real `CHARGE_ALREADY_REFUNDED` matches the offline fake.

### 4 and 5. MTProto sign-in

- Bot session: `client.start(bot_token=...)`, `get_me`, one permitted call, one bot-forbidden call such as `messages.getHistory` to observe the real error, then `disconnect`.
- User session: interactive provisioning only, by the owner, at a terminal. Save through `EncryptedSessionStore`. Reconnect in a new process, read Saved Messages, then call `log_out()` and confirm the session stops working.

### 6. Media transfer

Upload a generated file above the Bot API download limit to the test chat. Download it by message reference, compare SHA-256, watch memory, and cancel one transfer midway to confirm no partial file or connection remains. Test `FILE_REFERENCE_EXPIRED` only if it occurs naturally.

### 7. Hybrid

Start a transfer through the Bot API UI. Confirm the bot still answers another user during the transfer, Cancel stops it, and the worker shuts down cleanly on SIGTERM. Simulate worker loss and confirm the bot says the capability is unavailable.

## Teardown

1. `log_out()` every test user session and delete local copies.
2. Revoke the test bot token in BotFather, and delete any webhook.
3. Remove the test deployment and credential files.
4. Review logs for secrets before archiving them.

## What only live testing can answer

Telegram's real error text and limits, client rendering of rich messages (borders, hidden cells, themes, text size), real flood behavior, sign-in codes and 2FA, file references, reconnect and update-gap recovery, and the Stars purchase UI. Offline tests cannot prove any of these.
