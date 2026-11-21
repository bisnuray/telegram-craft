"""Rich message HTML (Bot API 10.1+) for bot screens. Plain str arguments are escaped; only Html passes through."""
from __future__ import annotations

import html as _html
from collections.abc import Iterable, Sequence
from html.parser import HTMLParser

__all__ = [
    "Html", "esc", "join", "b", "i", "u", "s", "code", "mark", "spoiler", "sub", "sup", "link", "time",
    "title", "heading", "para", "status", "facts", "table", "bullets", "numbered", "checklist",
    "section", "details", "note", "quote", "pull", "pre", "footer", "divider", "screen",
    "RICH_LIMIT", "check",
]

RICH_LIMIT = 32768        # UTF-8 characters, per the Bot API
BLOCK_LIMIT = 500         # blocks, including list items, table rows, quotes, and details
NESTING_LIMIT = 16
COLUMN_LIMIT = 20
TIME_FORMATS = {"", "r"} | {w + d + t for w in ("", "w") for d in ("", "d", "D") for t in ("", "t", "T")}


class Html(str):
    """Markup that is already safe. Never wrap user input in Html directly; pass it to a helper."""


Content = str | int | float | Html | None


def esc(value: Content) -> Html:
    if value is None:
        return Html("")
    if isinstance(value, Html):
        return value
    return Html(_html.escape(str(value), quote=True))


def join(*parts: Content, sep: str = "") -> Html:
    return Html(esc(sep).join(esc(p) for p in parts if p not in (None, "")))


def _wrap(tag: str, *parts: Content, attrs: str = "") -> Html:
    return Html(f"<{tag}{attrs}>{join(*parts)}</{tag}>")


# Inline styles. Each has one job; see references/rich-messages.md.
def b(*parts: Content) -> Html: return _wrap("b", *parts)
def i(*parts: Content) -> Html: return _wrap("i", *parts)
def u(*parts: Content) -> Html: return _wrap("u", *parts)
def s(*parts: Content) -> Html: return _wrap("s", *parts)
def code(*parts: Content) -> Html: return _wrap("code", *parts)
def mark(*parts: Content) -> Html: return _wrap("mark", *parts)
def spoiler(*parts: Content) -> Html: return _wrap("tg-spoiler", *parts)
def sub(*parts: Content) -> Html: return _wrap("sub", *parts)
def sup(*parts: Content) -> Html: return _wrap("sup", *parts)


def link(url: str, *parts: Content) -> Html:
    return _wrap("a", *(parts or (url,)), attrs=f' href="{esc(url)}"')


def time(unix: int, fmt: str = "", fallback: Content = "") -> Html:
    """A date or time shown in the reader's time zone. fmt: r (relative), or w? d|D? t|T?"""
    if fmt not in TIME_FORMATS:
        raise ValueError(f"tg-time format {fmt!r} must match r|w?[dD]?[tT]?")
    return Html(f'<tg-time unix="{int(unix)}" format="{fmt}">{esc(fallback) or int(unix)}</tg-time>')


# Blocks
def heading(text: Content, level: int = 4) -> Html:
    if not 1 <= level <= 6:
        raise ValueError("heading level must be 1-6")
    return _wrap(f"h{level}", text)


def title(text: Content, level: int = 3) -> Html:
    return heading(text, level)


def para(*parts: Content) -> Html:
    return _wrap("p", *parts)


def status(state: Content, *context: Content) -> Html:
    return para(b(state), *[join(" · ", c) for c in context if c not in (None, "")])


def facts(rows: Iterable[tuple[Content, Content]], caption: Content = None) -> Html:
    body = "".join(f"<tr><td>{b(label)}</td><td>{esc(value)}</td></tr>" for label, value in rows)
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return Html(f"<table bordered compact>{cap}{body}</table>")


def table(headers: Sequence[Content], rows: Iterable[Sequence[Content]], align: Sequence[str] | None = None,
          caption: Content = None, striped: bool = False, bordered: bool = True,
          total: Sequence[Content] | None = None) -> Html:
    """A bordered data table with a header row. Right-align numbers and money. A total row is bold.
    Only for items whose fields the user needs to compare; never for what the buttons already list."""
    rows = [list(r) for r in rows]
    if len(headers) > COLUMN_LIMIT:
        raise ValueError(f"tables allow {COLUMN_LIMIT} columns")
    align = list(align or [])

    def cell(tag: str, value: Content, col: int, span: int = 1) -> str:
        a = align[col] if col < len(align) and align[col] in ("center", "right") else ""
        attrs = (f' colspan="{span}"' if span > 1 else "") + (f' align="{a}"' if a else "")
        # Telegram hides a cell with no text, which breaks the bordered grid, so empty values show a dash.
        return f"<{tag}{attrs}>{esc(value) if value not in (None, '') else '—'}</{tag}>"

    flags = [f for f, on in (("bordered", bordered), ("striped", striped)) if on]
    out = [f"<table{' ' + ' '.join(flags) if flags else ''}>"]
    if caption:
        out.append(f"<caption>{esc(caption)}</caption>")
    out.append("<tr>" + "".join(cell("th", h, n) for n, h in enumerate(headers)) + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join(cell("td", v, n) for n, v in enumerate(r)) + "</tr>")
    if total:
        # The label spans the empty cells after it: ["Total", None, "450"] -> Total over two columns.
        cells, n = [], 0
        while n < len(total):
            span = 1
            while n + span < len(total) and total[n + span] in (None, ""):
                span += 1
            cells.append(cell("td", b(total[n]) if total[n] not in (None, "") else None, n, span))
            n += span
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return Html("".join(out))


def bullets(items: Iterable[Content]) -> Html:
    return Html("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>")


def numbered(items: Iterable[Content], start: int = 1) -> Html:
    attr = f' start="{int(start)}"' if start != 1 else ""
    return Html(f"<ol{attr}>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ol>")


def checklist(items: Iterable[tuple[Content, bool]]) -> Html:
    return Html("<ul>" + "".join(
        f'<li><input type="checkbox"{" checked" if done else ""}>{esc(label)}</li>' for label, done in items) + "</ul>")


def section(name: Content, *blocks: Content) -> Html:
    return join(heading(name, 4), *blocks)


def details(summary: Content, *blocks: Content, open: bool = False) -> Html:
    return Html(f"<details{' open' if open else ''}><summary>{esc(summary)}</summary>{join(*blocks)}</details>")


def note(*parts: Content, expandable: bool = False) -> Html:
    return _wrap("blockquote", *parts, attrs=" expandable" if expandable else "")


def quote(text: Content, cite: Content = None) -> Html:
    return _wrap("blockquote", text, Html(f"<cite>{esc(cite)}</cite>") if cite else None)


def pull(text: Content, cite: Content = None) -> Html:
    return _wrap("aside", text, Html(f"<cite>{esc(cite)}</cite>") if cite else None)


def pre(source: Content, language: str | None = None) -> Html:
    if language:
        return Html(f'<pre><code class="language-{esc(language)}">{esc(source)}</code></pre>')
    return _wrap("pre", source)


def footer(*parts: Content) -> Html:
    return _wrap("footer", *parts)


def divider() -> Html:
    return Html("<hr/>")


def screen(*blocks: Content) -> Html:
    html = join(*blocks)
    problems = check(html)
    if problems:
        raise ValueError("; ".join(problems))
    return html


class _Counter(HTMLParser):
    VOID = {"hr", "br", "img", "input", "tg-map"}
    BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "footer", "hr", "ul", "ol", "li", "blockquote",
              "aside", "table", "tr", "details", "figure", "tg-collage", "tg-slideshow", "tg-map",
              "tg-math-block", "tg-button-row", "img", "video", "audio", "tg-document"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.blocks = 0
        self.depth = 0
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS:
            self.blocks += 1
        if tag not in self.VOID:
            self.stack.append(tag)
            self.depth = max(self.depth, len(self.stack))

    def handle_startendtag(self, tag, attrs):
        if tag in self.BLOCKS:
            self.blocks += 1

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unbalanced </{tag}>")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()


def check(html: str) -> list[str]:
    """Limit and balance problems in a rich HTML string; empty when it is fine to send."""
    parser = _Counter()
    parser.feed(html)
    parser.close()
    problems = list(parser.errors)
    if parser.stack:
        problems.append(f"unclosed tags: {', '.join(parser.stack)}")
    if len(html) > RICH_LIMIT:
        problems.append(f"{len(html)} characters (limit {RICH_LIMIT})")
    if parser.blocks > BLOCK_LIMIT:
        problems.append(f"{parser.blocks} blocks (limit {BLOCK_LIMIT})")
    if parser.depth > NESTING_LIMIT:
        problems.append(f"nesting depth {parser.depth} (limit {NESTING_LIMIT})")
    return problems
