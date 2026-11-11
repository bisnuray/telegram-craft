# Delivery and deployment

Use for polling, webhooks, deployment, rate limits, and broadcasts.

## Polling or webhook

| | Long polling | Webhook |
|---|---|---|
| Choose for | Development, single-instance bots, no public HTTPS | Serverless, scale-out, an existing HTTPS service |
| Needs | Outbound network | Public HTTPS on port 443, 80, 88, or 8443 |
| Risk | Two instances conflict (409) | A slow response triggers retries |

Polling is fine in production for most small bots. Do not add a webhook without a reason. They are mutually exclusive, and updates wait at most 24 hours.

## Webhook requirements

- Set `secret_token` and compare the `X-Telegram-Bot-Api-Secret-Token` header in constant time. Do not rely on a secret path alone.
- Telegram retries on non-2xx responses. Return quickly and do heavy work afterward, with durable handoff if the work must not be lost.
- aiogram's `SimpleRequestHandler` defaults to `handle_in_background=True`, which returns 200 before the handler finishes, so a crash loses the update.
- Set the webhook in deployment, or once at startup by a single instance. List `allowed_updates` explicitly (`dp.resolve_used_update_types()` in aiogram).
- Do not use `drop_pending_updates` on routine restarts. It discards queued work, including payment updates.
- `max_connections` defaults to 40. Size it to what the service can handle.
- Check `getWebhookInfo` for `pending_update_count` and `last_error_message`.

## Containers

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
RUN useradd --create-home bot && chown -R bot /app
USER bot
CMD ["python", "-m", "app"]
```

- Use exec form so that SIGTERM reaches the process. Allow a stop grace period longer than the shutdown deadline.
- Include FFmpeg only in images that need it, and set memory and CPU limits.
- Secrets come from the environment or a secret manager, not image layers.
- Run migrations as a separate deploy step, not in each replica's startup.
- For polling, run exactly one replica. During rolling deploys, an old and a new poller overlap and produce 409 errors, so use stop-first.
- Serving Mini App assets: HTTPS is required, and caches should use hashed filenames.

Telegram also offers hosted backends for bots and Mini Apps: read `bots/serverless` before recommending them.

## Rate limits

Published guidance from the [Bots FAQ](https://core.telegram.org/bots/faq):

| Scope | Limit |
|---|---|
| One chat | Avoid more than 1 message per second; short bursts tolerated |
| One group | 20 messages per minute |
| Bulk notifications | About 30 messages per second |
| Paid broadcasts | Up to 1000 per second at 0.1 Stars per message past the free 30. Requires 100,000 Stars and 100,000 monthly active users. |

These are not guarantees. Handle 429 anyway. Self-hosting the Bot API server changes file limits and webhook options; the docs list no change to sending rates.

Throttle at the outbound layer: aiogram has no built-in limiter, grammY has `auto-retry` and `transformer-throttler`, python-telegram-bot has `AIORateLimiter`.

## Broadcasts

A broadcast is a persistent job:

1. Create a campaign row and one recipient row per user, so that a restart resumes. `Broadcast` and `send_honoring_retry_after` in `assets/update_delivery.py` implement this.
2. Claim recipients in batches, pacing below the limit. Spreading sends over hours also lowers server load from link clicks.
3. On 429, pause the whole sender for `retry_after`.
4. Mark 403 recipients inactive. Retry transient errors with a cap.
5. Record sent, failed, and blocked counts. Offer a preview and require confirmation before launch.

Keep user replies responsive while broadcasting by separating the send queue from interactive traffic. Message only users who opted in.

## Monitoring

BotFather sends status alerts if a popular bot's reply rate drops. Do not depend on those: monitor process liveness, update lag, error rate, and queue depth. A health endpoint should check the database and queue, not merely return 200.

## Release checklist

Token and secrets via environment; `.env` ignored; webhook secret on; `allowed_updates` set; migrations applied; one consumer; shutdown tested; logs free of secrets; alerts on; rollback plan; commands, description, and About set in BotFather; privacy policy available; `/paysupport` works if selling.
