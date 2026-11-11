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

```html
<h3>📡 Media relay</h3>
<p>🟢 <b>Running</b> · 3 sources · 128 copied today</p>
<table compact>
<tr><td><b>Target</b></td><td>Daily Clips</td></tr>
<tr><td><b>Last post</b></td><td><tg-time unix="1762850000" format="t">12:33</tg-time></td></tr>
</table>
<h4>Sources</h4>
<ul><li>Travel group</li><li>Photo drops</li><li><code>-1001234567890</code></li></ul>
<details><summary>How it works</summary><p>New photos and videos from the sources are copied to the target within seconds. Albums stay together.</p></details>
```

| Part | Rich tag |
|---|---|
| Screen title | `<h3>` (or `<h2>` for a root screen) with one emoji that names the screen, the same on every visit |
| Status | A `<p>` right under the title: one marker (🟢 running, ⏸ paused, ⚪ not set up, ⚠️ needs action, ✅ done) and a few words, bold for the state |
| Facts | A compact `<table>` of label and value, or `<b>Label:</b> value` lines for two or three facts |
| Collections | `<ul>`/`<ol>`, a checklist (`<input type="checkbox">`) for toggles and progress, or a `<table>` with `<th>` when items have several fields |
| Sections | `<h4>` subheadings; `<hr/>` only between real sections |
| Secondary detail, help, logs | `<details><summary>…</summary>…</details>` so the screen stays short; `<blockquote expandable>` for quoted text |
| Hints | `<blockquote>` or `<footer>` at the end |
| Copyable values | `<code>`; a `copy_text` button for long ones |
| Dates and times | `<tg-time>`, which shows in the reader's time zone |
| Media inside a screen | `<figure>`, `<tg-collage>`, `<tg-slideshow>` |

Limits: 32,768 characters, 500 blocks, 16 nesting levels, 50 media, 20 table columns.

**Use a regular message instead** for: callback answers and toasts; media captions and albums (send the media, with an HTML caption); one-line chat replies inside a conversation flow (`Saved.`); and stacks that cannot send rich messages. Those use the formatted HTML fallback below.

**Security:** escape every dynamic value (`<`, `>`, `&`, quotes in attributes). Unescaped user text in rich HTML can add headings, links, and even `<tg-button>`s. Set `skip_entity_detection` when the screen shows user-written text, so their `@mentions`, links, and commands are not made tappable.

### Fallback: formatted HTML text

Where a rich message is not possible, send with `parse_mode="HTML"` and keep the same shape: `📡 <b>Media relay</b>` title line, a status line, `<b>Label:</b> value` facts, `•` lists, `<code>` IDs, `<blockquote>` hints, `<blockquote expandable>` details. Plain unformatted text is a defect except in toasts and one-line replies.

**Rich, not noisy**, in both modes: icons on the title, the status, and buttons, not on every line or list item. No decorative dividers (`━━━`), ALL-CAPS labels, runs of `!`, bold whole sentences, centering with spaces, or ASCII tables. Serious contexts (finance, health, admin) keep the structure and may drop the title icon.

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
<h3>🎧 Audio converter</h3>
<p>Send a video and I'll turn it into an MP3 or a voice message.</p>
<blockquote>Files up to 20 MB.</blockquote>
```
Why: a titled screen that states what to do and the one limit that will bite. Buttons, if any, carry the rest.

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
<h3>📦 Orders</h3>
<p><b>12 open</b></p>
<table compact>
<tr><th>Order</th><th>Status</th></tr>
<tr><td>#1042</td><td>Waiting for payment</td></tr>
<tr><td>#1041</td><td>Shipped 3 Mar</td></tr>
<tr><td>#1039</td><td>Delivered</td></tr>
</table>
```
Use a stable title. Show the fields needed to choose. Move everything else to the detail screen. Give an empty state with a next step: `No orders yet. Browse the catalog to place one.`

### Transaction details

Show what was bought, the amount, the status, and a reference. Keep the order constant across every receipt.

```html
<h3>🧾 Receipt</h3>
<table compact>
<tr><td><b>Item</b></td><td>Pro plan, 1 month</td></tr>
<tr><td><b>Paid</b></td><td>150 ⭐</td></tr>
<tr><td><b>Date</b></td><td>3 March 2026</td></tr>
<tr><td><b>Ref</b></td><td><code>A81F2</code></td></tr>
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
