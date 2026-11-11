# Rich message screens

Use when designing or writing any bot screen. Bot screens are rich messages (`sendRichMessage`, edited in place with `editMessageText` and `rich_message`). Library calls: `formatting.md`. Copy rules (lead with the result, the user's words, errors that say what to do): `messages.md`. The shape of each screen type: `rich-recipes.md`.

## The standard style

Every screen looks like a clean, well-organized document: a plain title, one status line, a bordered table or a list, and nothing else unless the user needs it. Organized beats decorated.

1. **No emoji in screen text**: not in titles, headings, status lines, table cells, or list items. Words carry the state: **Running**, **Paused**, **Not set up**. Use emoji only when the user asks for them; buttons follow `keyboards.md`.
2. **Every table is bordered.** `<table bordered>` for data with a header row, `<table bordered compact>` for label and value facts.
3. **Show only what the user needs on this screen.** Most screens are a title and two or three blocks. No "How it works" fold, footer, or hint on every screen by habit.
4. **Never repeat the keyboard.** If the buttons list the chats, plans, or items, the text says what to do and does not list them again.
5. **No internal data.** Chat IDs, database IDs, enum names, and raw error codes stay out of the screen unless the user must copy or report them.
6. **One divider between the summary and the body.** When a screen has both a summary (title, status, facts) and a body (a section with its own `<h4>`), put one `<hr/>` between them. Never use one as decoration.
7. **The same shapes everywhere.** The same title level, status line, and table style on every screen, so the bot feels like one product.

## Build screens with the helper

Copy `assets/rich_html.py` into the project's text layer (for example `app/texts/rich.py`) and build every screen with it. It escapes all plain strings, makes tables bordered, and checks the limits (32,768 characters, 500 blocks, 16 levels, 20 columns). Keep one function per screen in `texts/`; handlers pick the screen and the keyboard.

```python
def home(state) -> Html:
    return screen(
        title("Media relay", level=2),
        status(state.mode_label, f"{len(state.sources)} sources"),
        facts([("Target", state.target.title if state.target else i("Not set")),
               ("Posting as", state.poster)]),
        section("Sources", bullets(state.source_titles) if state.source_titles else para(i("None yet"))),
    )
```

Show only data the product really has. Never invent counts or times to fill a table. If a useful fact is cheap to track, propose it in the handoff.

## Screen anatomy

Top to bottom. Only the title and the main content are always there.

| Part | Tag | Rule |
|---|---|---|
| Title | `<h2>` on the root screen, `<h3>` on the others | Names the place or the object, in plain words |
| Notice | `<p>` | Only right after an action: `Added <b>Travel group</b>.` Directly under the title, never above it |
| Status | `<p>` | The state in bold, then one or two facts joined by ` · ` |
| Divider | `<hr/>` | Between the summary and the body, only when the screen has both |
| Main content | A bordered table, a list, a checklist, or numbered steps | The one thing this screen is for |
| Sections | `<h4>` | Only when the screen has two kinds of content |
| Hint | `<blockquote>` | Only when the user is likely to be stuck: the next step, or the one limit that will bite |
| Footer | `<footer>` | Only for a page count the buttons do not show, or a reference the user may report |

The keyboard stays in `reply_markup` (`keyboards.md`).

## Components: what each one is for

**Headings.** `<h2>` for the root screen, `<h3>` for every other screen, `<h4>` for a section inside one. Never use a heading for a sentence. `<h1>` is too large for a chat screen.

**Tables** are for facts and for items whose fields the user compares. Every table is `bordered`.
- `<table bordered compact>` with bold labels for facts about one thing (target, mode, plan, renewal date).
- `<table bordered>` with a `<th>` header row for items with several fields, such as orders, invoices, or report rows.
- `align="right"` on number and money cells. A bold last row for totals, with `colspan` on the label instead of empty cells.
- Never leave a cell empty: Telegram hides a cell with no text, which breaks the bordered grid. Write `—` or `<i>None</i>`, or span the neighbouring cell.
- Two to four columns on a phone. Cells hold inline formatting only.
- No table for one fact (use the status line), for a single column (use a list), or for what the buttons already list.

**Lists.**
- `<ul>` for a set of names or short items.
- `<ol>` for steps the user follows in order.
- A checklist (`<li><input type="checkbox" checked>…`) for on/off settings, setup progress, and job stages.

**Dividers.** `<hr/>` separates two parts of one screen: the summary (title, status, facts table) from the body (the sections below). Use at most two per screen, and usually one. A divider never goes:
- right after the title;
- first or last;
- next to another divider;
- between a heading and its content;
- on a short screen that has no body.

It is the only divider; never type `━━━`, `———`, or `-----` lines.

**Quotes.** `<blockquote>` for one hint. `<blockquote expandable>` for long quoted text, such as a message preview or a log excerpt. `<aside>` only for a report's one headline number.

**Folds.** `<details><summary>…</summary>…</details>` only for content some users need and most do not: a full breakdown, the remaining items after ten, raw data. Never for a standing "How it works" on the home screen; put help on a help screen.

**Footer.** `<footer>` is a quiet last line for a page count or a reference ID, never for decoration or the time the screen was drawn.

**Code.** `<code>` for values the user copies or types: commands, usernames, references. `<pre><code class="language-…">` for real code or config only.

**Dates and times.** Use `<tg-time unix="…" format="…">fallback</tg-time>`. It shows in the reader's time zone and language.
- `r`: relative ("5 minutes ago").
- `t`: a time today.
- `D`: a date.
- `DT`: a full timestamp.

Always include fallback text.

**Media and the rest.**
- `<figure>` with `<figcaption>`, `<tg-collage>`, and `<tg-slideshow>` for images inside a screen.
- `<tg-map>` for a place.
- `<tg-math>` for formulas.
- Footnotes with `<tg-reference>`.
- `<tg-button>` places buttons inside the content. Prefer `reply_markup`, which every library and the quality gate support.

Captions and albums of files stay regular media messages (`media.md`).

## Text styles carry meaning

| Style | Tag | Use for |
|---|---|---|
| Bold | `<b>` | Table labels, the state, totals, the object's name in a notice |
| Italic | `<i>` | Empty or secondary values: `<i>Not set</i>`, `<i>None yet</i>` |
| Code | `<code>` | Commands, usernames, references to copy |
| Mark | `<mark>` | The one value that just changed, right after the user changed it |
| Strikethrough | `<s>` | An old price beside the new one |
| Spoiler | `<tg-spoiler>` | Codes and keys |

Bold labels and states, never whole sentences. At most one `<mark>` per screen.

## Mistakes that make a screen messy

| Mistake | Fix |
|---|---|
| The text lists the chats, items, or plans that the buttons already show | One sentence on what to do; the buttons are the list |
| A table with an ID column | Drop internal IDs; show names |
| Emoji in titles, headings, status, or cells | Plain words; bold for the state |
| A table without borders | `bordered`, always |
| A one-row or one-column table | The status line, or a list |
| An empty `<td></td>` (Telegram hides it, so the borders break) | `—`, `<i>None</i>`, or `colspan` |
| Help fold, hint, footer, and checklist all on one screen | Keep the main content; move help to a help screen |
| A notice above the title | Directly under the title |
| The same blocks on every screen | Use the recipe for the screen's job (`rich-recipes.md`) |
| `•` lines, `━━━` rules, or `<br>` stacks faking structure | Real `<ul>`, `<hr/>`, and `<p>` blocks |
| A divider after the title, at the end, or between every block | One `<hr/>` between the summary and the body |
| Bold whole sentences, or several `<mark>`s | Bold the label or the state; one mark |
| Times as `2026-11-11 12:33:00 UTC` | `<tg-time>` |

## Review before handoff

For each screen:

1. Does it follow its recipe in `rich-recipes.md`?
2. Could a block be removed without the user missing it? If so, remove it.
3. Does any text repeat a button?
4. Is every table bordered? Is the text free of emoji and internal IDs? Is there at most one divider, between the summary and the body?
5. Is user text escaped (the helper does it), with `skip_entity_detection` set when the screen shows user-written text?
6. Do `tg_lint.py` and the quality gate pass without `rich-*` warnings?

7. Is every rich payload free of `rich-*` errors? `tg_lint.py` and the gate validate:
   - tags, attributes, and nesting;
   - the 13 named entities Telegram allows;
   - `tg://` media references;
   - limits.

Report rich rendering as L1 or L2 until it has been seen on a real screen. L3 for a rich screen means a screenshot from a real Telegram client:
- the screen sent by a test bot, preferably on Telegram's test server (`frameworks.md`);
- seen on a phone and on desktop, in light and dark themes.

A rebuilt image, an HTML preview, or a captured payload is not visual proof.
