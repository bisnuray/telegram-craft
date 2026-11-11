# Message design

Use when writing or rewriting visible text. A chat message has no layout engine, so hierarchy comes from HTML formatting: a titled, iconed header, bold labels, code, and blockquotes. Every screen uses the default rich style below unless the user asks otherwise.

## Principles

- **Lead with what matters now**: the result, the decision, or the problem. The first line also appears in the notification preview.
- **One message, one job.** Two questions means two screens.
- **Shape follows the job.** Use the patterns below, not one template.
- **Say it once.** If a button says "Delete order", the text need not say "Press Delete to delete".
- **Use the user's words.** "Your order", not "entity" or "record". No enum names, HTTP codes, or stack traces.
- **Keep every fact when rewriting**: prices, dates, limits, legal text, placeholders, and locale keys.

## Default screen style: rich HTML

Send every message and edit with HTML parse mode (aiogram and python-telegram-bot `parse_mode="HTML"`, grammY `parse_mode: "HTML"`, Telethon `parse_mode="html"`). Plain unformatted text is a defect, except for one-line toasts and callback answers.

```
📡 <b>Media relay</b>
🟢 Running · 3 sources

<b>Target:</b> Daily Clips
<b>Sources:</b>
• Travel group
• Photo drops
• <code>-1001234567890</code>

<blockquote>New photos and videos from the sources are copied to the target within seconds.</blockquote>
```

| Part | How |
|---|---|
| Title | First line: one emoji that names the screen, then the title in bold. The same icon on every visit. |
| Status | Second line when the screen has a state: one marker (🟢 running, ⏸ paused, ⚪ not set up, ⚠️ needs action, ✅ done) and a few words. |
| Facts | `<b>Label:</b> value`, one per line, grouped with blank lines. |
| Lists | `•` bullets, up to about 10 items; paginate beyond that. |
| Copyable values | `<code>` for IDs, usernames, commands, keys. |
| Hints and explanations | `<blockquote>` at the end of the screen. |
| Details, logs, long help | `<blockquote expandable>`, so the screen stays short. |
| Links | `<a href="...">` with meaningful text, never a bare URL in a sentence. |
| Dates and times | `<tg-time>` where supported, otherwise one consistent format. |
| Long structured content (tables, reports, help pages, more than about 15 lines) | A rich message (`sendRichMessage`, `formatting.md`) when the library or a raw API call supports it; otherwise HTML with an expandable blockquote. |
| Buttons | An icon on the main action and on navigation is fine (`⚙️ Settings`, `‹ Back`); `style` per `keyboards.md`. |

Escape every dynamic value. Check the installed library's HTML support before using a tag: Telethon's parser handles `b i u s code pre a blockquote`; if `expandable` or `tg-time` is missing in the installed version, fall back to a plain blockquote or a formatted date.

**Rich, not noisy.** Icons go on the title, the status, and buttons, not on every line. No decorative dividers (`━━━`), ALL-CAPS labels, runs of `!`, bold whole sentences, centering with spaces, or ASCII tables (phones wrap monospace). Serious contexts (finance, health, admin) keep the structure and may drop the title icon.

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
After:
```
🎧 <b>Audio converter</b>

Send a video and I'll turn it into an MP3 or a voice message.

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

```
📦 <b>Orders</b> · 12 open

#1042  Waiting for payment
#1041  Shipped 3 Mar
#1039  Delivered
```
Use a stable title. Show the fields needed to choose. Move everything else to the detail screen. Give an empty state with a next step: `No orders yet. Browse the catalog to place one.`

### Transaction details

Show what was bought, the amount, the status, and a reference. Keep the order constant across every receipt.

```
<b>Receipt</b>
Item: Pro plan, 1 month
Paid: 150 ⭐
Date: 3 March 2026
Ref: <code>A81F2</code>

Help with this payment: /paysupport
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
