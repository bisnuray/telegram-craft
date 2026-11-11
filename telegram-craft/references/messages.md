# Message design

Use when writing or rewriting visible text. Bot screens are **rich messages** by default (Bot API 10.1+): real headings, tables, lists, and collapsible sections, rendered natively by Telegram. Formatted HTML text is the fallback where rich messages cannot be sent.

## Principles

- **Lead with what matters now**: the result, the decision, or the problem. The first line also appears in the notification preview.
- **One message, one job.** Two questions means two screens.
- **Shape follows the job.** Use the patterns below, not one template.
- **Say it once.** If a button says "Delete order", the text need not say "Press Delete to delete".
- **Use the user's words.** "Your order", not "entity" or "record". No enum names, HTTP codes, or stack traces.
- **Keep every fact when rewriting**: prices, dates, limits, legal text, placeholders, and locale keys.

## Default: rich message screens

Send every screen (menus, dashboards, lists, detail views, settings, help, receipts, reports) with `sendRichMessage` and `rich_message.html`, and update it in place with `editMessageText` and `rich_message`. Keep the inline keyboard in `reply_markup`, so callbacks work as usual. How to call it from each library: `formatting.md`.

**Design every screen with `rich-messages.md`** (the standard style: plain titles, no emoji, bordered tables, only what the user needs, never repeating the buttons) **and `rich-recipes.md`** (the shape for each screen type). Build the HTML with `assets/rich_html.py`, which escapes user text and keeps every screen consistent.

**Use a regular message instead** for: callback answers and toasts; media captions and albums (send the media, with an HTML caption); one-line chat replies inside a conversation flow (`Saved.`); and stacks that cannot send rich messages. Those use the formatted HTML fallback below.

**Security:** escape every dynamic value (`<`, `>`, `&`, quotes in attributes). Unescaped user text in rich HTML can add headings, links, and even `<tg-button>`s. Set `skip_entity_detection` when the screen shows user-written text, so their `@mentions`, links, and commands are not made tappable.

### Fallback: formatted HTML text

Where a rich message is not possible, send with `parse_mode="HTML"` and keep the same shape: a `<b>Media relay</b>` title line, a status line, `<b>Label:</b> value` facts, `•` lists, `<code>` IDs, `<blockquote>` hints, `<blockquote expandable>` details. Plain unformatted text is a defect except in toasts and one-line replies.

**Standard, not noisy**, in both modes: no emoji in titles, status lines, or list items (words carry the state), and no decorative dividers (`━━━`), ALL-CAPS labels, runs of `!`, bold whole sentences, centering with spaces, or ASCII tables. Never repeat in the text what the buttons already show. Use emoji only when the user asks for them.

## Patterns by job

These are starting shapes, not templates. Adapt them to the product's voice.

### First contact

Before:
```
🎉🎉 WELCOME TO SUPERCONVERT BOT!!! 🎉🎉
━━━━━━━━━━━━━━━
👋 Hello, dear user! I'm your AI-powered assistant,
here to help you with all your conversion needs!
✨ Fast  🔥 Reliable  💎 Premium quality
👇 Please choose an option below to get started! 👇
```
After (rich message HTML):
```html
<h3>Audio converter</h3>
<p>Send a video and I'll turn it into an MP3 or a voice message.</p>
<blockquote>Files up to 20 MB.</blockquote>
```
Why: a titled screen that states what to do and the one limit that will bite. Buttons, if any, carry the rest. A full help screen follows the help recipe in `rich-recipes.md`.

### Status and progress

Before: `⏳ Please wait... Processing your request... This may take a moment!`

After: `Converting lecture.mp4…` and then edit that same message to `Converting lecture.mp4 — 62%`.

Name the object. Show real progress or a stage (Downloading, Converting, Uploading). Do not invent percentages. Under about 5 seconds, a chat action alone is enough.

### Success

Before: `✅ Success! Your operation has been completed successfully! 🎉`

After:
```
Saved to Invoices.
Find it any time with /files.
```
State what changed and where it went. Often the delivered file is the confirmation.

### Errors

Each error gives what happened, in the user's terms, and what to do next.

| Before | After |
|---|---|
| `❌ Error: 400 Bad Request` | `This link has expired. Ask the sender for a new one.` |
| `Something went wrong. Please try again later.` | `I couldn't reach the bank. Nothing was charged. Try again in a minute.` |
| `Invalid input!` | `I need a date like 25.12.2026.` |
| `File too large` | `That file is 84 MB. I can download up to 20 MB, so try a shorter clip.` |

If money or data is involved, state its status explicitly. For unknown failures, give a short reference ID that matches a log entry.

### Confirmation

Name the object and consequence. The buttons repeat the verb.

```
Delete “Q3 report”?
This also removes its 4 attachments and can't be undone.
```
Buttons: `Delete report` / `Keep report`. Avoid `Yes` / `No` and "Are you sure?".

### Lists and details

```html
<h3>Orders</h3>
<p><b>12 open</b> · 3 waiting for payment</p>
<table bordered>
<tr><th>Order</th><th>Status</th><th>Total</th></tr>
<tr><td>#1042</td><td>Waiting for payment</td><td align="right">1,250 ⭐</td></tr>
<tr><td>#1041</td><td>Shipped <tg-time unix="1772524800" format="d">3 Mar</tg-time></td><td align="right">400 ⭐</td></tr>
<tr><td>#1039</td><td>Delivered</td><td align="right">90 ⭐</td></tr>
<tr><td>#1038</td><td>Delivered</td><td align="right">2,300 ⭐</td></tr>
</table>
```
Use a stable title. Show the fields needed to choose. Move everything else to the detail screen. Give an empty state with a next step: `No orders yet. Browse the catalog to place one.`

### Transaction details

Show what was bought, the amount, the status, and a reference. Keep the order constant across every receipt.

```html
<h3>Receipt</h3>
<p><b>Paid</b> · <tg-time unix="1772524800" format="D">3 March 2026</tg-time></p>
<table bordered compact>
<tr><td><b>Item</b></td><td>Pro plan, 1 month</td></tr>
<tr><td><b>Amount</b></td><td><b>150 ⭐</b></td></tr>
<tr><td><b>Reference</b></td><td><code>A81F2</code></td></tr>
</table>
<footer>Help with this payment: /paysupport</footer>
```

### Settings

Show the current value next to each setting, on the buttons or in the text. A setting that hides its state forces users to tap to find out. After a change, re-render the same screen with the new value.

### Forms

Ask for one thing, show the format, and offer Cancel. Validate on receipt and re-ask with the specific problem. Never ask for name, phone, and address in one message.

### Media captions

Up to 1024 characters. Give the title and the one detail that matters. Put long notes in a separate message. A long caption hides the media on small screens.

### Notifications

Unprompted messages must earn the interruption. Lead with the event, include the object, and link to the action. Batch frequent events, offer a way to mute, and use `disable_notification` for low-priority items.

## Voice

Pick a voice for the product and keep it. Plain and calm suits most tools. Write "Saved", not "Awesome! Your file has been successfully saved!". Skip self-reference ("As your assistant, I…"). Do not apologize repeatedly.

Use consistent terms: if it is a "Plan" on one screen it is never a "Subscription" or "Tier" elsewhere.

## Check

Run `scripts/tg_lint.py` on the screens, then read each one on a phone-width view and ask: what is the first line, what should the reader do, and what could be removed?
