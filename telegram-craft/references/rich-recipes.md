# Rich screen recipes

The standard shape for each kind of bot screen, as rich message HTML. Rules, components, and text styles: `rich-messages.md`. Build them with `assets/rich_html.py`. Use the parts shown; add one only when the user needs it, and drop one when the product has no data for it.

## Home or dashboard

The title, the status line, the facts that define the setup, a divider, and the main collection.

```html
<h2>Media relay</h2>
<p><b>Running</b> · 3 sources</p>
<table bordered compact>
<tr><td><b>Target</b></td><td>Daily Clips</td></tr>
<tr><td><b>Posting as</b></td><td>@clips_relay_bot</td></tr>
<tr><td><b>Copies</b></td><td>Photos and videos, with captions</td></tr>
</table>
<hr/>
<h4>Sources</h4>
<ul><li>Travel group</li><li>Photo drops</li><li>Weekend clips</li></ul>
```

Not set up yet: the status says so, and a numbered list replaces the sources.

```html
<h2>Media relay</h2>
<p><b>Not set up</b></p>
<ol><li>Choose the target channel.</li><li>Add at least one source chat.</li></ol>
```

## Picker

The buttons are the list. The text says what to pick and what to do if it is missing. Never list the options in the text as well.

```html
<h3>Add a source</h3>
<p>Choose a group or channel your account is in.</p>
<blockquote>Not listed? Send its @username or t.me link, or forward a message from it.</blockquote>
```

With pages, the keyboard holds the page buttons (`‹ 1/3 ›`), so the text needs no footer. When nothing can be picked, say why and what to do instead:

```html
<h3>Add a source</h3>
<p>Your account isn't in any other groups or channels.</p>
<p>Send a chat's @username or t.me link to add it.</p>
```

## Remove or choose from the user's own items

Again the buttons are the items. Say what tapping does and what is kept.

```html
<h3>Remove a source</h3>
<p>Tap a chat to stop copying from it. Posts already copied stay in <b>Daily Clips</b>.</p>
```

## Detail view

The object's name, its status, its facts, a divider, then its parts.

```html
<h3>Order 1042</h3>
<p><b>Waiting for payment</b> · placed <tg-time unix="1762760000" format="r">yesterday</tg-time></p>
<table bordered compact>
<tr><td><b>Customer</b></td><td>Anna K.</td></tr>
<tr><td><b>Delivery</b></td><td>Courier, 14 Mar</td></tr>
</table>
<hr/>
<h4>Items</h4>
<table bordered>
<tr><th>Item</th><th>Qty</th><th>Price</th></tr>
<tr><td>Coffee beans 1 kg</td><td align="right">2</td><td align="right">900 ⭐</td></tr>
<tr><td>Paper filters</td><td align="right">1</td><td align="right">350 ⭐</td></tr>
<tr><td colspan="2"><b>Total</b></td><td align="right"><b>1,250 ⭐</b></td></tr>
</table>
```

The Stars sign `⭐` is the currency symbol, not decoration.

## Data list

When the list itself is the content (orders, invoices, history) and each row has fields to compare. If the user opens a row with a button, keep the table to the fields needed to choose.

```html
<h3>Orders</h3>
<p><b>12 open</b> · 3 waiting for payment</p>
<table bordered>
<tr><th>Order</th><th>Status</th><th>Total</th></tr>
<tr><td>1042</td><td>Waiting for payment</td><td align="right">1,250 ⭐</td></tr>
<tr><td>1041</td><td>Shipped</td><td align="right">400 ⭐</td></tr>
<tr><td>1039</td><td>Delivered</td><td align="right">90 ⭐</td></tr>
</table>
```

## Settings

A checklist for the on/off settings and a facts table for the values. After a change, a notice under the title.

```html
<h3>Settings</h3>
<p>Interval changed to <b>15 minutes</b>.</p>
<ul>
<li><input type="checkbox" checked>Keep captions</li>
<li><input type="checkbox" checked>Keep albums together</li>
<li><input type="checkbox">Copy text-only posts</li>
</ul>
<table bordered compact>
<tr><td><b>Check every</b></td><td><mark>15 minutes</mark></td></tr>
<tr><td><b>Post as</b></td><td>Bot</td></tr>
</table>
```

## Help

What the bot does and the steps, then a divider and the commands.

```html
<h3>Help</h3>
<p>The bot copies new photos and videos from your source chats to one channel.</p>
<ol>
<li>Choose the target channel.</li>
<li>Add the chats to copy from.</li>
<li>New posts are copied within seconds. Albums stay together.</li>
</ol>
<hr/>
<h4>Commands</h4>
<table bordered compact>
<tr><td><code>/start</code></td><td>Home screen</td></tr>
<tr><td><code>/addsource</code></td><td>Add a chat to copy from</td></tr>
<tr><td><code>/settarget</code></td><td>Choose the channel to post to</td></tr>
</table>
```

## Receipt

The status, what was paid for, and the reference.

```html
<h3>Receipt</h3>
<p><b>Paid</b> · <tg-time unix="1762850000" format="DT">11 Nov 2026, 12:33</tg-time></p>
<table bordered>
<tr><th>Item</th><th>Price</th></tr>
<tr><td>Pro plan, 1 month</td><td align="right"><s>500 ⭐</s> 350 ⭐</td></tr>
<tr><td>Extra storage 10 GB</td><td align="right">100 ⭐</td></tr>
<tr><td><b>Total</b></td><td align="right"><b>450 ⭐</b></td></tr>
</table>
<footer>Reference <code>stxAbC123</code> · refunds within 14 days with /refund</footer>
```

## Report

The period, one summary table, and at most a few highlights.

```html
<h3>Weekly report</h3>
<p><tg-time unix="1762214400" format="D">4 November</tg-time> to <tg-time unix="1762819200" format="D">11 November</tg-time></p>
<table bordered>
<tr><th>Source</th><th>Posts</th><th>Size</th></tr>
<tr><td>Travel group</td><td align="right">702</td><td align="right">3.1 GB</td></tr>
<tr><td>Photo drops</td><td align="right">582</td><td align="right">2.4 GB</td></tr>
<tr><td><b>Total</b></td><td align="right"><b>1,284</b></td><td align="right"><b>5.5 GB</b></td></tr>
</table>
<ul><li>2 posts skipped: over the 2 GB file limit.</li></ul>
```

## Problem

What is wrong, what it affects, and the steps to fix it.

```html
<h3>Can't post to Daily Clips</h3>
<p><b>Copying is paused</b> · 14 posts waiting</p>
<ol>
<li>Open Daily Clips, then Administrators.</li>
<li>Add the bot and turn on <b>Post messages</b>.</li>
<li>Tap Retry.</li>
</ol>
```

## Confirmation

The question names the object; the text gives the consequence. The buttons repeat the verb (`Remove source` / `Keep it`).

```html
<h3>Remove Travel group?</h3>
<p>New posts from it will stop being copied. Posts already copied stay in <b>Daily Clips</b>.</p>
```

## Progress

Edit the same message as stages complete.

```html
<h3>Converting lecture.mp4</h3>
<p><b>Converting</b> · 62% of 48 MB</p>
<ul>
<li><input type="checkbox" checked>Downloaded</li>
<li><input type="checkbox">Converted</li>
<li><input type="checkbox">Uploaded</li>
</ul>
```

## Messy versus standard

A picker an agent produced with an earlier version of this skill:

```html
<h3>➕ Add a source</h3>
<p><b>12 chats</b> you can copy from · 3 already added</p>
<table striped>
<tr><th>Chat</th><th>ID</th></tr>
<tr><td>Travel group</td><td>-1001234567890</td></tr>
<tr><td>Photo drops</td><td>-1009876543210</td></tr>
</table>
<blockquote>Not listed? Send its @username.</blockquote>
<footer>Page 1 of 3</footer>
```

What is wrong:
- The table lists the same chats as the buttons below it.
- It shows internal chat IDs.
- The table has no borders, and the title has an emoji.
- The footer repeats the page buttons.
- A screen this short needs no divider; the standard version has none.

The standard version is the picker recipe above: a title, one sentence, and one hint.
