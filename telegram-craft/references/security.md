# Security

Use for secrets, authorization, input handling, privacy, and abuse prevention. Security requirements are not traded for feature completeness.

## Trust boundaries

| Input | Trust |
|---|---|
| `update.from.id` delivered to a verified webhook or via polling | Identity, trusted |
| Validated `initData` | Identity, trusted, within its age limit |
| `callback_data`, `/start` payload, `start_param`, `web_app_data` | Untrusted input |
| Message text, captions, filenames, and names | Untrusted, and may contain markup |
| `initDataUnsafe`, request bodies, client state | Untrusted |
| Model output, or another bot's messages | Untrusted |
| Payment updates | Trusted facts, but verify against the order |

## Secrets

- Keep tokens in environment variables or a secret manager. Commit `.env.example` only.
- The token is embedded in `api.telegram.org/bot<token>/...` and file URLs. Mask these in logs and error reports, and in HTTP client debug output.
- Keep a separate webhook secret.
- Have a rotation plan. If a token leaks, revoke via BotFather, then redeploy.
- A pasted token: use it only for what was asked, never repeat it, keep it out of files that could be committed, and recommend rotation if it was exposed in a shared place.

## Authorization

Check three things on every privileged command, callback, HTTP endpoint, and job: **who** (role from your store), **which object** (ownership), and **current state** (still allowed).

```python
if order.owner_id != actor_id and not actor.has_role("support"):
    return NotAllowed()
```

- Set the owner by trusted config, using a numeric ID. Never "first user to press /start".
- `setMyCommands` scope only changes the display.
- Group admin status can change, so re-check with `getChatMember` for sensitive actions, with a short cache at most.
- Sign `callback_data` only if it must not be forged or inspected. A server-side lookup with authorization is usually simpler.
- Don't expose sequential IDs in links that grant access. Use random tokens.

## Input handling

- Escape for the output context (`formatting.md`). Validate type, length, and range.
- Use parameterized SQL only.
- Run subprocesses with argv lists.
- URLs from users: allow only http(s), resolve and block private ranges, limit redirects and bytes, and set timeouts (SSRF).
- Paths: generate server-side names. Never join a user filename to a path.
- Archives: limit file count, total extracted size, and ratio, and reject path traversal entries.
- Parsers for images, documents, and video are attack surface. Keep them patched and isolated.
- MIME type and filename from Telegram are claims. Inspect the content when it matters.

## Mini Apps

Validate init data as in `mini-apps.md`, restrict CORS, set a Content Security Policy, avoid `innerHTML` with dynamic data, and keep sessions short. Long-lived credentials should go in `SecureStorage`. Don't link to untrusted origins.

## Webhooks

Check the secret header in constant time. Limit body size. Return no internal details. Restricting source IPs to Telegram's published ranges (`149.154.160.0/20`, `91.108.4.0/22`) is defense in depth and needs maintaining.

## Payments

See `payments.md`. The server sets prices, grants on `successful_payment` only, dedupes on charge ID, and audit-logs refunds.

## Privacy

Telegram's [developer terms](https://telegram.org/tos/bot-developers) require an accessible privacy policy, which can be Telegram's standard one if yours isn't provided.

- Collect the minimum. Do you need the phone number? The full name? Message content?
- Define retention, and purge on schedule.
- Support deletion on request. Include caches, backups policy, and logs.
- Don't place personal data in logs. Prefer numeric IDs, or hashes where IDs aren't needed.
- Check the terms before using Telegram data for model training or sharing it with third parties, and disclose third-party AI processing.
- Encrypt sensitive fields at rest, and restrict database and admin access.
- Handle minors' and special-category data according to law. Flag this for human review.

## Audit logging

For admin actions, role changes, refunds, and bans, record the actor, the action, the target, the time, and the before and after values, in append-only storage. Do not include secrets.

## Abuse prevention

- Rate-limit per user for expensive operations, and globally for shared resources.
- Cap free AI usage, jobs, and file sizes.
- Referral and reward systems attract farming. Grant on validated events, once, server-side.
- Mini App games: the client score is a claim. Validate plausibility on the server.
- For LLM bots, prompt injection is expected. Tools must enforce permissions themselves. Model output must not create buttons, links, or commands unchecked.
- Bot-to-bot: Telegram requires loop prevention.
- Offer block, report, and appeal paths where users interact with each other.

## Requests to decline or reshape

Do not implement token theft, phishing Mini Apps, covert data collection, spam tools, sockpuppet fleets, ban evasion, or impersonation of Telegram. Where a request is close to this line, offer the legitimate form, such as opt-in broadcasts or the user's own account with consent.
