# Keyboards and navigation

Use for buttons, menus, pagination, confirmations, and callback bugs.

## Inline or reply keyboard

| | Inline | Reply |
|---|---|---|
| Attached to | One message | The input area |
| Press produces | Callback, URL, Mini App, copy, inline switch | A normal text message, or a contact, location, or chat request |
| Best for | Menus, item actions, pagination, confirmations | Requesting contact or location, or a few persistent shortcuts |

Plain reply buttons send visible text, so handlers must match strings. That breaks across languages and anyone can type the same text. Prefer inline for actions. Remove a reply keyboard explicitly when it is finished.

## Labels and layout

- Use verb and object: `Download PDF`, `Renew plan`. Bare nouns are fine for navigation (`Settings`).
- Name the outcome. `Back` goes back, and a button that also cancels must say `Cancel`.
- Keep labels short. Phones truncate long labels, particularly in two-column rows. Test the longest language.
- One main action per screen, placed first, on its own row. Secondary actions follow. Navigation goes last.
- Use two per row for short paired choices. Numbers and short tokens can go up to 5 per row.
- A screen with more than about 8 rows should paginate or split.
- Use the same label for the same action everywhere.

Design a screen in this order, and stop when it works: the words (does the user know what happens next?), the actions and their grouping, the way back and out, the message body, and only then emphasis. A screen that fails on words is not rescued by color.

Use `style` sparingly: `primary` for the single main action, `danger` for real destruction (behind a confirmation), `success` for a desirable commit. Leave Back and Cancel unstyled. Every label must still make sense with no color and no icon, because clients and themes render styles differently. Check SDK support first. A `disabled` button (Bot API 10.3) can show a state that is unavailable.

`icon_custom_emoji_id` works only for bots that bought extra usernames on Fragment, or in messages the bot sends directly to private chats and groups when its owner has Telegram Premium. Never invent an emoji ID: get a real one from the owner.

Do not put an emoji on every button. An icon helps when it aids scanning, such as a language flag.

Use the right button type: `url` for external links, `web_app` for Mini Apps (private chats only), `copy_text` for codes, `login_url` for site sign-in, `pay` for invoices (first button).

## Callback data

Limit is 1–64 **bytes**. Cyrillic text costs 2 bytes a character, so put identifiers there, not text.

Use a versioned, parseable format with a typed codec:

```
v1:order:view:1042
```

- aiogram: subclass `CallbackData`; `pack()` raises `ValueError` over 64 bytes.
- grammY: `InlineKeyboard` with a small encode/decode module.
- python-telegram-bot: string patterns with a codec. `arbitrary_callback_data` stores objects server-side, in memory unless persistence is set.
- Over 64 bytes: store the payload server-side and pass a short token with an expiry.

Keep prior formats parseable after deploys, because old keyboards stay in chats indefinitely.

**Callback data is input.** Parse it strictly and authorize on every press:

```python
@router.callback_query(OrderCb.filter(F.action == "cancel"))
async def cancel_order(cb: CallbackQuery, callback_data: OrderCb, orders: OrderService) -> None:
    result = await orders.cancel(order_id=callback_data.id, actor_id=cb.from_user.id)
    match result:
        case Cancelled(order):
            await cb.answer("Order cancelled")
            await cb.message.edit_text(render_order(order), reply_markup=order_kb(order))
        case NotAllowed():
            await cb.answer("This order belongs to another account.", show_alert=True)
        case AlreadyClosed(order):
            await cb.answer("This order was already closed.")
            await cb.message.edit_text(render_order(order), reply_markup=order_kb(order))
```

The service, not the handler, checks ownership and current state in one transaction.

## Answering callbacks

- Answer every callback on every path. `answer()` with no text just stops the spinner.
- For slow work, answer first and then work.
- Use a toast for small acknowledgements, up to 200 characters, and `show_alert=True` only for something the user must read.
- A late answer raises `query is too old`. Log it at a low level and continue.
- In aiogram, `CallbackAnswerMiddleware` can answer automatically.

## Editing in place

Prefer `editMessageText` or `editMessageReplyMarkup` over sending. Handle these:

| Case | Handling |
|---|---|
| `message is not modified` | Harmless: double taps or a repeat render. Catch it and continue. |
| Switching between text and media | Can't edit a text message into media with `editMessageText`. Delete and send, or use `editMessageMedia` when already media. |
| `message to edit not found` / can't be edited | Send a fresh screen. |
| `callback.message` is `None` or inaccessible | Old message or inline-mode callback. Check before using it; use `inline_message_id` for inline. |

Answer the callback before catching edit errors so that no path leaves a spinner.

## Navigation

- **Back** returns to the previous screen and keeps context such as list page and filters. Encode the return target in callback data or store it, for example `v1:order:view:1042:p3`.
- **Cancel** abandons the current flow, clears its state, and says what happened.
- **Home** is useful in deep structures. Keep hierarchies to about 3 levels.
- `/cancel` must always work during a flow. Unexpected input should re-prompt, not fall through to a generic handler.

## Pagination

```
[ Item 11 ]
[ Item 12 ]
[ ‹ Prev ] [ 3 / 7 ] [ Next › ]
[ Back ]
```

- Omit Prev on page 1 and Next on the last page, or use a disabled button so that the layout does not jump.
- A current-page button must still have an action. Answer it with no text.
- Use keyset or stored pagination for lists that change. Clamp out-of-range pages and show the nearest valid page.
- With many pages, add search or move to a Mini App.

## Confirmations

Confirm destructive, irreversible, or costly actions only. Over-confirming trains users to tap through.

- State the object and the effect in text, and use specific verbs on buttons.
- Put the safe option where a mis-tap is harmless and keep the destructive one distinct.
- The final action must re-check state. Protect against double taps with a conditional update such as `UPDATE ... WHERE status='active'`, not by removing the keyboard.

## Stale and invalid actions

Every old button will eventually be tapped.

| Situation | Response |
|---|---|
| Object deleted | Toast, then re-render the parent list |
| State already changed | Toast naming the current state, then re-render |
| Malformed or unknown callback | Toast and show home. Log it. |
| Session or flow expired | "This menu expired", then show a fresh one |
| Another user taps in a group | `show_alert` "Only the requester can use this". Bind actions to a user ID. |
| Permission revoked | Refuse and redraw without that action |

Add a catch-all callback handler last so that unknown data is answered, not ignored.

## Permission-aware UI

Hide actions that a user cannot perform, and still enforce on the server. Button visibility is a convenience.

## Common defects

- A new message for every navigation tap
- Labels like `Click here`, `OK`, or `Option 1`
- A Back button that restarts the menu and loses the page
- Yes or No confirmations that do not say what is being confirmed
- No handling for the old keyboards left in chat history
- Callback data with display text in it, which overflows in other languages
