# Formatting and message construction

Use for parse modes, escaping, entities, long text, rich messages, and streaming.

## Choose a mode

| Mode | Use when |
|---|---|
| HTML `parse_mode` | Default for regular messages. Only `<`, `>`, `&` need escaping. |
| Entities array | Text comes with offsets already, or you build programmatically. No escaping. Offsets are UTF-16 code units. |
| No parse mode | Echoing user or model text as-is. Safest. |
| MarkdownV2 | Only when a project already uses it. |
| Legacy `Markdown` | Do not add it. |
| Rich message | **Default for bot screens**: headings, tables, lists, collapsible blocks, up to 32,768 characters. |

## HTML

Supported tags: `b strong i em u ins s strike del span.tg-spoiler tg-spoiler a tg-emoji tg-time code pre blockquote`. `<br>`, `<p>`, `<div>`, and lists are **not** supported in regular messages. Use newlines.

Named entities are limited to `&lt; &gt; &amp; &quot;`. Numeric entities work. `&nbsp;` does not.

Escape each value and then assemble:

```python
from html import escape

def order_text(order) -> str:
    return (
        f"<b>{escape(order.title, quote=False)}</b>\n"
        f"Status: {escape(order.status_label, quote=False)}"
    )
```

Inside an `href` attribute, use `quote=True`. Escaping the finished string would destroy your own tags. In aiogram, `aiogram.utils.formatting` builds entities with no escaping needed, and `aiogram.utils.markdown.html_decoration.quote` escapes. In TypeScript, grammY's `parse-mode` plugin provides a `fmt` helper. Otherwise replace `&` first, then `<`, then `>`.

Names are user-controlled: a user named `<b` will break an unescaped send with `can't parse entities`.

## MarkdownV2

These must be escaped outside code and links: `_ * [ ] ( ) ~ ` > # + - = | { } . !`. Inside `pre` and `code`, escape only `` ` `` and `\`. Inside a link target, escape only `)` and `\`. A price like `10.50` needs `10\.50`. Static text needs escaping as well as data.

Entity nesting limits apply to both modes: `pre` and `code` cannot contain or be inside other entities, blockquotes cannot nest, and overlapping entities must be fully contained.

## Mentions and dates

Use `<a href="tg://user?id=123">name</a>` for mentions. It works only under the documented conditions, so do not depend on it for delivery. `<tg-time unix="…" format="wDT">fallback</tg-time>` renders in the reader's locale.

Inline links show users an "Open this link?" alert. Control previews with `link_preview_options`, disabling them when the URL is not the point.

## Limits and splitting

Text is 1–4096 and captions 0–1024 characters **after** entity parsing. Split on paragraph boundaries, never mid-tag, mid-entity, or mid-surrogate pair, and keep tags balanced in each part. Add keyboards only to the last part. Over about two parts, consider a rich message, a document, or pagination.

## Rich messages (Bot API 10.1+): the default for screens

Bot screens are rich messages by default; design them with `rich-messages.md` and build them with `assets/rich_html.py`. Send with `sendRichMessage` using exactly one of `html`, `markdown`, or `blocks`, and edit in place with `editMessageText` and `rich_message`. They work in private chats, groups, and channels, and accept the usual `reply_markup`.

Limits: 32,768 characters, 500 blocks, 16 nesting levels, 50 media, 20 table columns. Tag list: `tgdocs.py page bots/api/rich-messages`.

| Stack | Send | Edit |
|---|---|---|
| aiogram 3.31+ | `await bot.send_rich_message(chat_id, InputRichMessage(html=html), reply_markup=kb)`, or `message.answer_rich(...)` / `reply_rich(...)` | `await message.edit_text(rich_message=InputRichMessage(html=html), reply_markup=kb, parse_mode=None)` |
| grammY 1.46+ | `await ctx.replyWithRichMessage({ html }, { reply_markup })` | `await ctx.editMessageText({ html }, { reply_markup })` (the first argument takes text or a rich message) |
| python-telegram-bot 22.8 | `await bot.do_api_request("sendRichMessage", api_kwargs={"chat_id": ..., "rich_message": {"html": html}, "reply_markup": kb.to_dict()})` | `do_api_request("editMessageText", ...)` with `rich_message` |
| pyTelegramBotAPI (telebot) 4.37.1+ | `bot.send_rich_message(chat_id, types.InputRichMessage(html=html), reply_markup=kb)` (also on `AsyncTeleBot`) | `bot.edit_message_text(chat_id=..., message_id=..., rich_message=..., reply_markup=kb)` |
| Telethon 1.45 (layer 229) | Raw request, below | `EditMessageRequest(peer, id, rich_message=..., reply_markup=...)` |
| kurigram 2.2.27+ (layer 233) | `await app.send_rich_message(chat_id, types.InputRichMessage(html=html), reply_markup=kb)` or `message.reply_rich(...)` | `await app.edit_message_text(chat_id, message_id, rich_message=..., reply_markup=kb)` |

```python
from telethon.tl.functions.messages import SendMessageRequest
from telethon.tl.types import InputRichMessageHTML

await client(SendMessageRequest(
    peer=await client.get_input_entity(chat_id),
    message="",                                   # rich content replaces the text
    rich_message=InputRichMessageHTML(html=html),
    reply_markup=client.build_reply_markup(buttons),
))
```

The MTProto `rich_message` field (`messages.sendMessage` flags.23, and `messages.editMessage`) is in both Telethon's layer 229 and kurigram's layer 233 schemas, but not yet in the public MTProto docs, so report it as unverified until a test bot shows the screen (L3). Keep a fallback to `parse_mode="html"` text if the server rejects it. In a hybrid app, prefer running the control bot on a Bot API library (aiogram) where rich messages are documented, and keep Telethon for the user client.

- **aiogram edits:** `edit_text` and `edit_message_text` send the bot's default `parse_mode` alongside `rich_message` unless you pass `parse_mode=None`. Always pass it on rich edits; the gate warns (`rich-parse-mode`).
- **Fallback:** see the ladder below.
- **Where else rich messages work:**
  - Inline mode, with `InputRichMessageContent`; only previously uploaded files may be used.
  - Ephemeral messages; edit them with `editEphemeralMessageText(rich_message=…)`.
  - `editMessageMedia`, which replaces a rich message with media.
  - Editing an inline message, which cannot upload new files.
- **Other fields:** `is_rtl` for right-to-left locales, and `media` for files referenced as `tg://photo?id=…` in the HTML.
- Escape every dynamic value; user text in rich `html` or `markdown` can otherwise create headings, links, and `<tg-button>`s. Use `blocks` when most of the content is dynamic: block text is literal.
- Set `skip_entity_detection` when showing user-written text.
- Media in a rich message is a block (`<figure>`, `<tg-collage>`); files come from HTTPS URLs or `tg://photo?id=` links plus the `media` field. Media captions and albums stay regular messages.
- Callback answers, toasts, and one-line replies inside a flow stay regular messages.
- Put navigation in `reply_markup`. `<tg-button>` inside the content suits a button tied to one block (a row in a table, a section). The quality gate checks both, but its `press()` taps only `reply_markup` buttons; reach in-content buttons in tests with `callback(data)`.

### When a rich message fails

Classify the failure first; each class has one reaction.

| Failure | Signal | Reaction |
|---|---|---|
| Your payload is invalid | 400 parse or validation error, or a `tg_lint` `rich-*` error | Fix the HTML. Never retry it unchanged, and never hide a bug behind a fallback |
| Rich messages are unsupported | The library has no method (use the raw call in the table), or 400 or MTProto `RICH_MESSAGE_UNSUPPORTED` from the chat or account | Step down the ladder |
| Rate limit, network, or 5xx | 429 `retry_after`, timeout, 5xx | Wait, then retry the same rich message a bounded number of times (`delivery.md`) |
| Not allowed | 403, or no right to send media in the chat | Stop for that chat and surface it |

The ladder, one step at a time:
1. `blocks` or `html` rich message.
2. The same screen as formatted HTML text (`parse_mode="HTML"`), with the same title, facts, and keyboard.
3. Plain text, for the error path only.

Rules:
- Build the fallback from the same screen data, so both versions show the same facts.
- Log each fallback once with its reason, never the token or the user's text.
- Never fall back silently for money or legal content. A receipt, invoice, or refund screen that cannot be sent rich is sent as formatted HTML with every amount and reference intact, and the failure is reported.

Tables too wide for a phone: transpose them (attributes as rows) or split them into two tables that share a key column; never drop columns silently. A table over the limits splits across messages between rows, never mid-row, with the header row repeated.

## Streaming drafts (private chats)

`sendMessageDraft` and `sendRichMessageDraft` show a temporary preview for AI replies. Drafts are ephemeral, so send a final real message when done. Update on a timer, a few times per second at most, and not per token. Pass empty text for a "Thinking…" placeholder. With `can_stop` (10.3), handle the `stopped_message_generation` update. In groups, use a chat action and send the finished reply.

Model output is untrusted. Render it with no parse mode, or convert it through a strict sanitizer with a fallback to plain text on parse failure.

## Handling parse errors

`Bad Request: can't parse entities` reports a byte offset. Log the template ID, not the user's content. In production, a safe fallback is to resend with no parse mode so the user still gets the message. Fix the cause, which is nearly always a missing escape.
