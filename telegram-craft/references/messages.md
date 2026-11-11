# Message design

Use when writing or rewriting visible text. A chat message has no layout engine: hierarchy comes from word order, line breaks, and sparing bold.

## Principles

- **Lead with what matters now**: the result, the decision, or the problem. The first line also appears in the notification preview.
- **One message, one job.** Two questions means two screens.
- **Shape follows the job.** Use the patterns below, not one template.
- **Say it once.** If a button says "Delete order", the text need not say "Press Delete to delete".
- **Use the user's words.** "Your order", not "entity" or "record". No enum names, HTTP codes, or stack traces.
- **Keep every fact when rewriting**: prices, dates, limits, legal text, placeholders, and locale keys.

## Formatting

| Device | Use for | Avoid |
|---|---|---|
| Bold | One title or the key value | Whole sentences |
| Blank line | Separating groups | Between every line |
| `Label: value` lines | Up to about 6 facts | Long prose as label/value |
| `code` | Copyable IDs, keys, addresses | Decoration or alignment |
| Blockquote, expandable | Secondary detail | The main message |
| Rich message | Real tables, sections | Short replies |

**Emoji** carry meaning or they go. One status marker can help (✅ for done, ⚠️ for a warning needing action). Do not start each line with one, or use them as bullets or in headings as decoration. Bots in serious contexts (finance, health, admin tools) may need none.

Avoid decorative dividers (`━━━`, `═══`), ALL-CAPS labels, runs of `!`, centering with spaces, and invented ASCII tables. On phones, monospace grids wrap unpredictably.

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
Send a video and I'll turn it into an MP3 or a voice message.

Files up to 20 MB.
```
Why: it states what to do and the one limit that will bite. Buttons, if any, carry the rest.

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
<b>Orders</b> · 12 open

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
