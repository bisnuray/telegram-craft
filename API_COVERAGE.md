# Telegram API coverage

Audited 2026-11-09 against official docs (Bot API 10.3) and installed libraries. Updated 2026-11-10 for Bot API 10.4: widgets, callback ephemeral replies, and new entity types are documented in `platform-facts.md`, `groups-automation.md`, and `SKILL.md`. No SDK supported 10.4 on that date. "Before" is the state before this enhancement.

**Evidence labels:** *Tested* means an executable test ran offline against real library types. *Docs-only* means guidance checked against official pages, with no execution. Nothing here was run against live Telegram.

| Area | Before | Now | Evidence |
|---|---|---|---|
| HTTP Bot API: messages, keyboards, callbacks | Complete | Complete | Tested through three framework adapters |
| HTTP Bot API: updates, webhooks, deployment | Complete | Complete | Docs-only, with audit rules tested |
| HTTP Bot API: rich and ephemeral messages | Partial | Partial | Payload checks tested; block contents are not validated |
| Business, managed, guest bots | Partial | Partial | Docs-only pointers |
| MTProto API selection, layers, error classes | Missing | Complete | Docs-only, names verified against Telethon 1.45.0 |
| MTProto bot sessions | Partial (mentioned) | Complete | Sign-in flow mocked on a real client |
| MTProto user sessions | Partial (warning only) | Complete | Registry and refusal tested; real sign-in is not |
| Session storage, encryption, revocation | Missing | Complete | Encryption tested; server-side revocation docs-only |
| Telethon events and updates | Partial | Partial | Filter tested on real types; reconnection and catch-up are docs-only |
| Flood handling, bounded retries | Partial (Bot API only) | Complete | Tested with real Telethon errors |
| MTProto media | Missing | Partial | Docs-only; no transfer executed |
| Multi-client lifecycle | Missing | Complete | Tested with mocks |
| TDLib, mtcute | Missing | Partial | Status and selection only |
| Hybrid Bot API + MTProto | Missing | Partial | **Design guidance only, never executed** |
| Mini Apps: auth, viewport, native controls | Complete | Complete | Validator tested; client behavior docs-only |
| Media handling (Bot API) | Complete | Complete | Tested with real FFmpeg |
| Payments and subscriptions | Complete | Complete | Ledger and payload rules tested; no real payment |
| Authentication and authorization | Complete | Complete | init data tested; project authorization rules docs-only |
| Error handling and flood control (Bot API) | Complete | Complete | Simulated errors reach handlers typed |

## Bot and user capability boundaries

| Capability | HTTP Bot API | MTProto bot | MTProto user |
|---|---|---|---|
| Sign-in | Token | Token + `api_id` | Phone code or QR, 2FA |
| Read chat history | No | No (`messages.getHistory` is user-only) | Yes, for chats it can access |
| Contacts | No | No (`contacts.getContacts` is user-only) | Yes |
| Send messages | Yes | Yes | Yes, with heavier abuse controls |
| Schedule messages | Not via `sendMessage` | No (`SCHEDULE_BOT_NOT_ALLOWED`) | Yes |
| Large files | 20 MB down, 50 MB up on cloud; more with a local server | Limited by MTProto part limits | Limited by part limits; Premium raises them |
| Webhook delivery | Yes | No, persistent connection | No, persistent connection |

## Library status (checked 2026-11-09)

| Library | Latest | Status |
|---|---|---|
| aiogram | 3.31.0 (2026-08) | Active; declares Bot API 10.3 |
| python-telegram-bot | 22.8 (2026-06) | Active; declares Bot API 10.0 |
| grammY | 1.46.0 (2026-08) | Active |
| Telethon | 1.45.0 (2026-09) | Released; GitHub archived, moved to Codeberg; compiles layer 229 |
| TDLib | tag v1.8.0 | Active repository |
| mtcute | 0.32.7 (2026-10) | Active |
| GramJS (`telegram`) | 2.26.22 (2026-07) | GitHub archived |
| **Pyrogram** | 2.0.106 (2023-04) | **Archived; not recommended for new work** |
| kurigram, pyrotgfork | 2.2.x (2026) | Maintained forks |
| Hydrogram | 0.2.0 (2024) | Repository active, no recent release |

Sources: [Bot API](https://core.telegram.org/bots/api), [MTProto bots](https://core.telegram.org/api/bots), [API terms](https://core.telegram.org/api/terms), [obtaining api_id](https://core.telegram.org/api/obtaining_api_id), [errors](https://core.telegram.org/api/errors), [updates](https://core.telegram.org/api/updates), [files](https://core.telegram.org/api/files), [Telethon](https://codeberg.org/Lonami/Telethon).
