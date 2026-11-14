# MTProto foundations

Use when a project needs MTProto, signs in with `api_id` and `api_hash`, or has to choose between Bot API and MTProto. Checked against official docs on 2026-11-09. For code, see `mtproto-telethon.md`. For combined systems, see `hybrid-architecture.md`.

## Choose the API

Default to the HTTP Bot API. Adopt MTProto only for a named requirement it alone meets.

| Requirement | Use |
|---|---|
| Normal bot features, webhooks, payments, keyboards | Bot API |
| Bot files over 20 MB download or 50 MB upload | MTProto bot session, or a local Bot API server (no `api_id` client code needed in the app) |
| Raw layer features the Bot API lacks, callable by bots | MTProto bot session |
| Reading chat history, searching, contacts | MTProto **user** session, with that user's knowledge and consent |
| A full Telegram client | TDLib |
| Bot UI plus one user-only capability | Hybrid (`hybrid-architecture.md`) |

## Bot sessions and user sessions differ

| | Bot session | User session |
|---|---|---|
| Sign-in | `auth.importBotAuthorization` with bot token and `api_id` | Phone code or QR, then 2FA if enabled |
| Identity | The bot | A real person's whole account |
| Blast radius if leaked | That bot | The entire account |
| Methods | Those marked "Both users and bots" or "Only bots" | Those marked "Both users and bots" or "Only users" |
| Ban risk | Bot rules | Account can be limited or banned |

Each method page states who can call it. For example, `messages.getHistory` and `contacts.getContacts` are **only users**, and bots get `BOT_METHOD_INVALID`-style errors for user-only methods. `messages.sendMessage` is for both, though bots cannot schedule (`SCHEDULE_BOT_NOT_ALLOWED`). Check `https://core.telegram.org/method/<name>.md` before designing around a method. Business and managed bots have their own rules under `/api/bots/`.

## Authorization boundaries

Telegram states that all accounts logging in through unofficial clients are placed under observation, and that flooding, spam, and faking counters earn a permanent ban. The [API terms](https://core.telegram.org/api/terms) also forbid acting on a user's behalf without their knowledge and consent, "ghost mode" tampering with read or online states, and using Telegram data to train AI.

Do not build, and refuse to help with: mass messaging or invites, scraping users or groups the account has no legitimate purpose for, account farms, sockpuppets, phone-number rotation, proxy or device spoofing to evade limits, or sign-in flows that take someone else's codes. Sign in only to accounts the operator owns or has explicit authorization to operate.

## API ID and hash

- Create your own at <https://my.telegram.org/apps>; terms 2.1 require it. Each phone number can have one `api_id`.
- Never copy one from a library example or another app. A published id can return `API_ID_PUBLISHED_FLOOD`.
- Treat `api_hash` as a secret: environment or secret manager, never client-side code or a repository.
- A user-facing client must meet the transparency terms: say it uses the Telegram API, keep "Telegram" out of the name unless preceded by "Unofficial", and do not use the logo.

## Authentication flows

**Bot:** `client.start(bot_token=token)`. Safe for unattended services.

**User account: an existing `StringSession` by default.** Runtime and initial authorization are separate:

- **Runtime (every start):** read `TELEGRAM_SESSION_STRING` from the environment or a secret manager, and `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` separately. Build the client with `string_session_from_env()` and call `connect_authorized(client)` (`assets/mtproto_runtime.py`). A missing, empty, malformed, or revoked session raises `SessionUnavailable`; the process exits with that message and the operator is alerted. Never call `client.start()` for a user account at runtime: on an unauthorized session it prompts for a phone number. `StringSession("")` is a new, unauthorized session, so an unset variable must fail before the client exists.
- **Initial authorization (once, by the account owner):** `assets/create_session.py`, run by hand when the owner chooses to: phone, code, and the 2FA password through no-echo prompts, never logged or stored. It writes the string to a mode-0600 file to move into the secret store. QR login works too. Never collect codes through a chat bot or a web form on behalf of others, and never generate, guess, or fake a session.

A session string does not bypass Telegram's sign-in: it is the result of one, and it stops working when the owner ends it under Settings > Devices.

## Sessions

A session contains the authorization key and is equivalent to a logged-in account. **A session is a credential.**

| Rule | Why |
|---|---|
| Encrypt at rest (`assets/mtproto_runtime.py`, `EncryptedSessionStore`), key in a secret manager | File theft should not mean account takeover |
| Never commit, log, or print session strings. Run `scripts/secure_mtproto_project.py PROJECT` when creating or changing an MTProto project | They grant full access |
| One live connection per session | Parallel use beyond the server's advertised `tmp_sessions` can return `AUTH_KEY_DUPLICATED`, which invalidates the key |
| Use a distinct session per process or deployment slot | The same reason, during rolling deploys especially |
| Restrict file and backup access | Backups are copies of the credential |

### Storing sessions safely

- **Where:** a secret manager or the deployment's secret environment (`TELEGRAM_SESSION_STRING`), never a literal in code, tests, fixtures, `.env.example`, docs, or a Docker image. `.gitignore` alone does not protect it: check `docker inspect`, CI logs, and crash reports too. Where the product must catch up on updates across restarts, keep a `SQLiteSession` on an encrypted volume, or a string in `EncryptedSessionStore` (mode 0700, key in a secret manager). `SQLiteSession` files (`name.session`, plus `-journal`, `-wal`, and `-shm` sidecars) hold the same key unencrypted, and `TelegramClient("name", ...)` creates one silently.
- **Tests:** build a synthetic string offline (`s = StringSession(); s.set_dc(2, "149.154.167.51", 443); s.auth_key = AuthKey(bytes(256))`), mock `connect` and `is_user_authorized`, and never use a real account's session.
- **Ignore rules:** `secure_mtproto_project.py` appends `*.session`, the sidecars, `*.session.enc`, `.env`, `.env.*` (keeping `.env.example`), and `tdata/`, only where they are missing. It changes no existing rule. `--ci` adds `.github/workflows/telegram-credentials.yml`, a self-contained job that fails when a session file is tracked or a session string is committed. It never replaces an existing workflow. With `--check` it changes nothing and fails when a rule is missing.
- **Logs and reports:** add `RedactingFilter` from `assets/mtproto_runtime.py` to log handlers. It strips session strings, bot tokens, `api_hash`, phone numbers, and login codes. The quality gate removes session strings from its captures and reports.
- **Checks:** the same script, and `tg_audit.py`, report session files and real `.env` files tracked by git, session files not ignored, session strings in source, sessions passed to `print` or a logger, hard-coded `api_hash` values, secrets in a Dockerfile `ENV` or `ARG` (baked into image layers), `StringSession` built from a possibly empty variable, and `start()` or `log_out()` at runtime. They never delete, untrack, or revoke anything.

### If a session leaked

Act in this order, with the account owner deciding each step. An agent reports the leak and does not revoke sessions itself.

1. **End the session on the server.** Use the owner's device list (Settings > Devices), `account.resetAuthorization` for that session, or `client.log_out()` from the leaked session. A new sign-in creates a new key; the old one stays valid until ended.
2. **Remove the copy.** `git rm --cached` stops tracking it, but it stays in history and in every clone. Rewriting history needs the owner's agreement and a force-push.
3. **Rotate related secrets.** That includes the storage key, and the bot token if a bot session leaked (BotFather `/revoke`). Check the account's 2FA.
4. **Review.** Check `account.getAuthorizations` for unknown sessions, and look for actions taken with the leaked key.

Protocol details that change this order:

- **Watch for new sign-ins.** Other sessions receive `updateNewAuthorization` for each new login. Alert the owner, who can end it with `account.resetAuthorization`.
- **A fresh session cannot end others.** For its first 24 hours it gets `FRESH_RESET_AUTHORISATION_FORBIDDEN`, so the owner's older device does the ending.
- **Logging out is not a lockout.** `auth.logOut` may return a `future_auth_token` that lets the next sign-in skip the code. The 2FA password is the real barrier, so the account should have one.

**Revocation:** `client.log_out()` ends this session on the server, and only then delete the local copy. Deleting only the file leaves the session active. `account.getAuthorizations` lists sessions, `account.resetAuthorization` ends one, and `auth.resetAuthorizations` ends all others. After a suspected leak, end the session from the account's device list and rotate the storage key.

Handle `AUTH_KEY_UNREGISTERED`, `SESSION_REVOKED`, `USER_DEACTIVATED*`, and `AUTH_KEY_DUPLICATED` as terminal: stop that client, alert, and do not loop on reconnects.

## Layers and raw calls

The API is versioned by TL **layers**. Telethon 1.45.0 compiles layer 229, while the public schema page showed layer 225 on 2026-11-09, so check the schema your library actually ships. Libraries pin the layer they were generated from. Consequences:

- A method or constructor exists only if your library's layer has it. Check before writing the code.
- Do not hand-write constructor IDs. Upgrade the library when you need a newer layer.
- Clients should tolerate objects newer than they expect. Test library upgrades.

## Errors

| Code | Meaning | Action |
|---|---|---|
| 303 `*_MIGRATE_X` | Different data center | Libraries redirect automatically |
| 400 | Bad input | Do not retry |
| 401 `AUTH_KEY_*`, `SESSION_*` | Authorization gone | Terminal for this client |
| 403 | Privacy or rights | Do not retry; report to the workflow |
| 406 | Includes `AUTH_KEY_DUPLICATED` | Stop; fix deployment |
| 420 `FLOOD_WAIT_X`, `SLOWMODE_WAIT_X` | Wait X seconds | Bounded wait; see `mtproto-telethon.md` |
| 420 `FLOOD_PREMIUM_WAIT_X` | File speed limit | Library handles or wait as instructed |
| `PEER_FLOOD` | Account restricted from contacting people | **Stop the workflow.** Retrying risks a ban |
| 500 and `RPC_CALL_FAIL` | Server side | Bounded retry with backoff |

## Files

Parts must be equal sizes, with `part_size % 1024 == 0` and `524288 % part_size == 0`, and 512 KB is the recommended size. The maximum part count comes from `upload_max_fileparts_default` and `upload_max_fileparts_premium` in appConfig, so read those rather than hard-coding a total size. `FILE_MIGRATE_X` redirects downloads to another data center, and `FILE_REFERENCE_EXPIRED` requires refetching the parent message to refresh the reference.

## Library status (2026-11-09)

| Library | Status | Recommendation |
|---|---|---|
| Telethon 1.45.0 | Released 2026-09 on PyPI; GitHub repository archived and moved to Codeberg | Default for Python. Pin the version and watch the new home. |
| TDLib 1.8.x | Official and active | Choose for full clients or strict state handling. Heavier, with native binaries. |
| mtcute 0.32 | Active | TypeScript default |
| GramJS (`telegram` npm) | GitHub repository archived 2026-07; npm 2.26.22 | Existing projects only |
| Pyrogram 2.0.106 | **Upstream archived; last release 2023** | Do not choose for new work |
| kurigram, pyrotgfork | Maintained forks | Reasonable migration path for existing Pyrogram code; check layer and maintainers first |
| Hydrogram | Repository active; last PyPI release 2024 | Verify before adopting |
