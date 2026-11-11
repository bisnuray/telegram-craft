# Platform facts

Checked against official docs on 2026-11-10 at Bot API 10.4. Before relying on anything version-sensitive, run `scripts/tgdocs.py version`. If it reports newer than 10.4, also run `changes --since 10.4`.

Official Markdown lives at `https://core.telegram.org/bots/api/methods/<name-lowercase>.md`, `.../bots/api/types/<name-lowercase>.md`, and `https://core.telegram.org/llms.txt`.

## Text

| Item | Limit |
|---|---|
| Message text | 1–4096 characters after entity parsing |
| Caption | 0–1024 after entity parsing |
| Rich message | 32,768 characters; 500 blocks; 16 nesting levels; 50 media; 20 table columns |
| Callback answer text | 0–200 |
| `callback_data` | 1–64 **bytes** |
| `copy_text` | 1–256 |
| Deep-link parameter | Up to 64 from `A-Za-z0-9_-` |
| Command | 1–32 lowercase letters, digits, underscore; description 1–256; 100 commands per scope and language |
| Album | 2–10 items |

## Files

| Item | Limit |
|---|---|
| Download via `getFile` | 20 MB; link valid at least 1 hour |
| Upload | 10 MB photo; 50 MB other |
| Send by URL | 5 MB photo; 20 MB other |
| Local Bot API server | Upload to 2000 MB; download unlimited |
| Thumbnail | JPEG, under 200 kB, up to 320 px per side, fresh upload |

## Delivery

| Item | Value |
|---|---|
| Pending updates kept | 24 hours |
| Webhook ports | 443, 80, 88, 8443 |
| `max_connections` | 1–100, default 40 |
| `secret_token` | 1–256 from `A-Za-z0-9_-` |
| Default exclusions from updates | `chat_member`, `message_reaction`, `message_reaction_count` |
| Omitted `allowed_updates` | Keeps the previous setting |

## Sending rates (FAQ guidance, not contracts)

1 message per second per chat, with bursts; 20 per minute per group; about 30 per second bulk; up to 1000 per second with paid broadcast at 0.1 Stars per message over 30, for bots with 100,000 Stars and 100,000 monthly active users. Rate-limit data comes only in `parameters.retry_after`.

## Actions and edits

| Item | Value |
|---|---|
| Chat action duration | Up to 5 seconds |
| Delete message | Sent less than 48 hours ago (with exceptions in the method docs) |
| Ephemeral message | Within 15 seconds of an eligible action; replies within 15 seconds |
| HTML widget (`sendWidget`, 10.4) | `html` 1–32,768 bytes and at most 4,096 bytes after maximum zlib compression; `public_data` and `chat_data` up to 1,024 bytes each; height clamped to 50–600 px; production: private chats only, always protected content |
| `update_id` | Sequential, but after a week without updates the next one is random. Use it as an identity, never to compare age across a gap |
| Message draft | 30-second preview; private chats |

## Payments

| Item | Value |
|---|---|
| Digital goods currency | `XTR`, with empty `provider_token` and exactly one price item |
| Invoice title, description, payload | 1–32 chars, 1–255 chars, 1–128 bytes |
| Pre-checkout answer | Within 10 seconds |
| Stars subscription | `createInvoiceLink`, `subscription_period` 2,592,000 only, up to 10,000 Stars |
| Paid media | 1–25,000 Stars, up to 10 items |
| Required command | `/paysupport` |

## Mini Apps

| Item | Value |
|---|---|
| `sendData` | Up to 4096 bytes; keyboard-button launches only |
| HMAC secret | `HMAC_SHA256(key="WebAppData", msg=bot_token)` |
| HMAC data string | All fields except `hash`, sorted, newline-joined |
| Ed25519 data string | `bot_id:WebAppData`, then all fields except `hash` and `signature` |
| Ed25519 production key (hex) | `e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d` |
| Ed25519 test key (hex) | `40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec` |
| Origin hardening | On by default since 2026-07-20 |

## Recent changes commonly missed

| Version | Change |
|---|---|
| 10.4 (2026-11-09) | HTML widgets: `sendWidget`, `widget_query` and `shared_widget_query` updates, `answerWidgetQuery`, `editMessageWidgetData`; ephemeral replies to callback queries in any chat (`callback_query_id` without `receiver_user_id`; `chat_id` optional); quoting rich messages; TON wallet cards; `ton_address` and `bank_card_number` entities; `getUniqueGift` |
| 10.3 (2026-08-24) | `ephemeral_message_parameters` replaced `receiver_user_id` and `callback_query_id`; `DisabledButton`; `force_reply` on markups; rich block buttons; `can_stop` on drafts |
| 10.2 (2026-07-14) | Ephemeral messages; rich message `blocks`; Communities; `subscription` updates; Mini App origin lockdown |
| 10.1 (2026-06-11) | Rich messages; `sendRichMessage`; `sendRichMessageDraft`; join-request queries |
| 10.0 (2026-05-08) | Guest mode; live photos; polls with media and 1+ options; bots can see some bot messages in groups |
| 9.x | `style` and `icon_custom_emoji_id` on buttons; `sendMessageDraft` |

## Library status (2026-11-11)

No library supported 10.4 on 2026-11-11; use a raw API call in one adapter for widgets and the new ephemeral replies. aiogram 3.31.0 → Bot API 10.3. python-telegram-bot 22.8 → 10.0. grammY 1.46.0. Telegraf 4.16.3. Telethon 1.45.0 (layer 229). kurigram 2.2.27 (layer 233, Pyrogram fork) has native rich messages. pyTelegramBotAPI 4.37.1 has `send_rich_message`. Pyrogram upstream archived.
