#!/usr/bin/env python3
"""Lint Telegram message screens offline (Python 3.9+, standard library).

  tg_lint.py screens.json [--json] [--strict]
  tg_lint.py --capture .tg-lint [--report out.json] [--json] [--strict] [--min-button-coverage 0.8]
             [--source PROJECT] [--require-coverage]

Input is one object or a list. Either a screen or a raw Bot API payload:

  {"id": "orders", "kind": "list", "text": "<b>Orders</b>", "parse_mode": "HTML",
   "reply_markup": {"inline_keyboard": [[{"text": "Back", "callback_data": "home"}]]}}

Optional `kind`: root, menu, list, detail, form, confirm, result, error,
notification, caption, callback_answer. `caption` is accepted in place of `text`.

--capture reads the outgoing Bot API calls recorded by the quality-gate adapters
(a file, or a directory of capture-*.json) and also checks each simulated
interaction: unanswered callbacks, handler exceptions, and which offered buttons
tests never pressed. Coverage separates confirmed gaps (registered handlers that
never ran, callbacks sent without any captured screen offering them) from
uncertain ones (callback_data in the source that no capture showed).

Errors are objectively invalid payloads or clearly broken behavior. Warnings are
UX signals that need judgment; a warning can be right to ignore. Passing proves
neither rendering, quality, nor correct navigation on untested paths.
Exit codes: 0 clean, 1 errors (or warnings with --strict, or coverage below the
minimum), 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
CALLBACK_ANSWER_LIMIT = 200
CALLBACK_DATA_LIMIT = 64
LONG_LABEL = 32
ROW_CHARS = 36
MAX_ROWS = 8

ACTION_FIELDS = {
    "url", "callback_data", "web_app", "login_url", "switch_inline_query",
    "switch_inline_query_current_chat", "switch_inline_query_chosen_chat",
    "copy_text", "callback_game", "pay", "disabled",
}
REPLY_ACTION_FIELDS = {"request_users", "request_chat", "request_managed_bot", "request_contact", "request_location", "request_poll", "web_app"}
INLINE_ONLY_METHODS = {"editMessageText", "editMessageCaption", "editMessageMedia", "editMessageReplyMarkup", "editMessageLiveLocation", "stopMessageLiveLocation", "stopPoll", "sendGame"}
STYLES = {"primary", "success", "danger"}
HTML_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span", "tg-spoiler",
    "a", "tg-emoji", "tg-time", "code", "pre", "blockquote",
}
NAMED_ENTITIES = {"lt", "gt", "amp", "quot"}
MDV2_RESERVED = set("_*[]()~`>#+-=|{}.!")

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿⏩-⏺️⃣]+"
)
RULE_RE = re.compile(r"^\s*([━═─—–\-_=~*•·▬▪.]\s?){5,}\s*$")
BOILERPLATE = [
    (re.compile(r"\bwelcome to\b", re.I), "a generic welcome; say what the bot does for this user"),
    (re.compile(r"\b(i'?m|i am) (here|your|an?) .{0,30}(assistant|help)", re.I), "assistant boilerplate"),
    (re.compile(r"\bfeel free to\b|\bdon'?t hesitate\b", re.I), "filler phrase"),
    (re.compile(r"\bunlock\b|\bseamless(ly)?\b|\bsupercharge\b|\beffortless(ly)?\b", re.I), "marketing filler"),
    (re.compile(r"\bsomething went wrong\b|\ban error occurred\b", re.I), "error without a cause or next step"),
    (re.compile(r"\bplease wait\b", re.I), "say what is happening, or use a chat action"),
    (re.compile(r"\boops\b|\bwhoops\b", re.I), "casual error tone; state what happened"),
]
GENERIC_LABEL = re.compile(r"^(ok|okay|yes|no|click here|press here|tap here|click|submit|button\s*\d*|option\s*\d+|item\s*\d+)$", re.I)
BACK_WORDS = re.compile(r"\b(back|go back|return|home|main menu|menu|close|done|cancel)\b|назад|меню|отмена", re.I)
BACK_LABEL_FAMILY = re.compile(r"^(?:[^\w]*)(back|go back|return)(?:[^\w]*)$", re.I)
DESTRUCTIVE = re.compile(r"\b(delete|remove|erase|wipe|ban|kick|unsubscribe|cancel subscription|refund|reset)\b|удалить", re.I)
CONFIRM_DATA = re.compile(r"confirm|sure|yes|ask", re.I)


class TelegramHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.errors: list[tuple[str, str]] = []
        self.stack: list[str] = []
        self.text: list[str] = []
        self.bold_chars = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag not in HTML_TAGS:
            self.errors.append(("html-tag", f"<{tag}> is not supported by Telegram HTML"))
        elif tag == "span" and values.get("class") != "tg-spoiler":
            self.errors.append(("html-tag", '<span> needs class="tg-spoiler"'))
        elif tag == "a" and not values.get("href"):
            self.errors.append(("html-attr", "<a> needs href"))
        elif tag == "tg-emoji" and not values.get("emoji-id"):
            self.errors.append(("html-attr", "<tg-emoji> needs emoji-id"))
        elif tag == "tg-time" and not values.get("unix"):
            self.errors.append(("html-attr", "<tg-time> needs unix"))
        if tag == "blockquote" and "blockquote" in self.stack:
            self.errors.append(("html-nesting", "blockquotes cannot be nested"))
        if tag in ("code", "pre") and any(t in self.stack for t in ("code",)):
            self.errors.append(("html-nesting", f"<{tag}> cannot sit inside <code>"))
        if tag not in ("code",) and "pre" in self.stack:
            self.errors.append(("html-nesting", f"<{tag}> cannot sit inside <pre>"))
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.stack:
            self.errors.append(("html-balance", f"</{tag}> has no opening tag"))
            return
        if self.stack[-1] != tag:
            self.errors.append(("html-balance", f"</{tag}> closes across <{self.stack[-1]}>"))
        while self.stack and self.stack.pop() != tag:
            pass

    def handle_data(self, data: str) -> None:
        if "<" in data or ">" in data:
            self.errors.append(("html-escape", "raw < or > in text must be &lt; or &gt;"))
        self._add(data)

    def handle_entityref(self, name: str) -> None:
        if name not in NAMED_ENTITIES:
            self.errors.append(("html-entity", f"&{name}; is not supported; use a numeric entity"))
        self._add(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self._add(unescape(f"&#{name};"))

    def _add(self, data: str) -> None:
        self.text.append(data)
        if any(t in self.stack for t in ("b", "strong")):
            self.bold_chars += len(data)

    def finish(self) -> None:
        for tag in self.stack:
            self.errors.append(("html-balance", f"<{tag}> is never closed"))


BARE_AMP = re.compile(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);)")


def utf16_len(text: str) -> int:
    """Conservative length: UTF-16 units are never fewer than code points."""
    return len(text.encode("utf-16-le")) // 2


def parse_html(text: str) -> tuple[str, int, list[tuple[str, str]]]:
    errors = []
    if BARE_AMP.search(text):
        errors.append(("html-escape", "raw & in text must be &amp;"))
    if re.search(r"<(?![a-zA-Z/])", text):
        errors.append(("html-escape", "raw < in text must be &lt;"))
    parser = TelegramHTML()
    parser.feed(text)
    parser.close()
    parser.finish()
    return "".join(parser.text), parser.bold_chars, errors + parser.errors


def parse_markdown_v2(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Check escaping outside code spans. A preflight, not a full parser."""
    errors: list[tuple[str, str]] = []
    visible: list[str] = []
    counts = {"*": 0, "_": 0, "~": 0, "`": 0}
    i = 0
    in_code = False
    depth = {"[": 0, "(": 0}
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            visible.append(text[i + 1])
            i += 2
            continue
        if ch == "`":
            counts["`"] += 1
            in_code = not in_code
        elif in_code:
            visible.append(ch)
        elif ch in counts:
            counts[ch] += 1
        elif ch == "|" and text[i : i + 2] == "||":
            i += 1
        elif ch == "[":
            depth["["] += 1
        elif ch == "]":
            depth["["] -= 1
        elif ch == "(" and i and text[i - 1] == "]":
            depth["("] += 1
            end = text.find(")", i)
            if end == -1:
                errors.append(("mdv2-balance", "link target is never closed"))
                break
            i = end
            depth["("] -= 1
        elif ch == ">" and (i == 0 or text[i - 1] == "\n"):
            pass
        elif ch in MDV2_RESERVED:
            errors.append(("mdv2-escape", f"{ch!r} at offset {i} must be escaped as \\{ch}"))
            visible.append(ch)
        else:
            visible.append(ch)
        i += 1
    for mark, count in counts.items():
        if count % 2:
            errors.append(("mdv2-balance", f"unbalanced {mark!r}"))
    if depth["["] != 0:
        errors.append(("mdv2-balance", "unbalanced [ ]"))
    return "".join(visible), errors


def lint_labels(rows: list, add) -> None:
    """UX checks that apply to any keyboard layout."""
    if len(rows) > MAX_ROWS:
        add("warning", "keyboard-tall", f"{len(rows)} rows; paginate or split the screen")
    labelled = []
    for row in rows:
        labels = [b.get("text", "") if isinstance(b, dict) else "" for b in row]
        labelled += [label for label in labels if isinstance(label, str) and label]
        for label in labels:
            if isinstance(label, str) and len(label) > LONG_LABEL:
                add("warning", "label-long", f"{label!r} may truncate on phones; shorten it")
            if isinstance(label, str) and GENERIC_LABEL.match(EMOJI_RE.sub("", label).strip()):
                add("warning", "generic-label", f"{label!r} does not say what happens; name the action")
        total = sum(len(label) for label in labels if isinstance(label, str))
        if len(row) > 1 and total > ROW_CHARS:
            add("warning", "row-crowded", f"row labels total {total} characters across {len(row)} buttons; stack them")
        if len(row) > 3 and not all(isinstance(x, str) and len(x) <= 3 for x in labels):
            add("warning", "row-wide", f"{len(row)} word buttons in a row are hard to tap")
    if len(labelled) >= 3 and all(EMOJI_RE.match(label) for label in labelled):
        add("warning", "emoji-labels", "every button starts with an emoji; keep icons only where they aid scanning")


def check_rows(rows: Any, add, code: str) -> list:
    """Return usable rows, reporting structural problems."""
    if not isinstance(rows, list):
        add("error", code, "keyboard must be an array of button rows")
        return []
    usable = []
    for row in rows:
        if not isinstance(row, list):
            add("error", code, "each keyboard row must be an array of buttons")
        elif not row:
            add("warning", "empty-row", "keyboard contains an empty row")
        else:
            bad = [b for b in row if not isinstance(b, dict)]
            if bad:
                add("error", code, f"button must be an object, got {type(bad[0]).__name__}")
            good = [b for b in row if isinstance(b, dict)]
            if good:
                usable.append(good)
    return usable


def lint_inline_keyboard(rows: Any, add, chat_type: str = "", method: str = "") -> list[dict[str, Any]]:
    usable = check_rows(rows, add, "inline-structure")
    buttons: list[dict[str, Any]] = []
    for row_index, row in enumerate(usable):
        for column, button in enumerate(row):
            buttons.append(button)
            label = button.get("text", "")
            actions = ACTION_FIELDS & set(button)
            if not isinstance(label, str) or not label.strip():
                add("error", "button-text", "button text is empty")
                label = str(label)
            if len(actions) != 1:
                add("error", "button-action", f"{label!r} needs exactly one action field, found {sorted(actions)}")
            data = button.get("callback_data")
            if data is not None:
                size = len(str(data).encode("utf-8"))
                if not 1 <= size <= CALLBACK_DATA_LIMIT:
                    add("error", "callback-bytes", f"{label!r} callback_data is {size} bytes (limit 1-{CALLBACK_DATA_LIMIT})")
            url = button.get("url")
            if url is not None and not re.match(r"(https?|tg)://", str(url)):
                add("error", "button-url", f"{label!r} url must be http(s):// or tg://")
            style = button.get("style")
            if style is not None and style not in STYLES:
                add("error", "button-style", f"{label!r} style must be one of {sorted(STYLES)}")
            if "web_app" in button:
                check_web_app(button["web_app"], label, add, chat_type)
            if "copy_text" in button:
                text = button["copy_text"].get("text") if isinstance(button["copy_text"], dict) else None
                if not isinstance(text, str) or not 1 <= len(text) <= 256:
                    add("error", "copy-text", f"{label!r} copy_text.text must be 1-256 characters")
            if button.get("pay"):
                if (row_index, column) != (0, 0):
                    add("error", "pay-position", f"{label!r} pay button must be the first button in the first row")
                if method and method != "sendInvoice":
                    add("error", "pay-method", f"{label!r} pay buttons are only valid on invoices, not {method}")
    lint_labels(usable, add)
    if sum(1 for b in buttons if b.get("style") == "primary") > 1:
        add("warning", "multiple-primary", "more than one primary button; a screen should have one main action")
    return buttons


def check_web_app(value: Any, label: str, add, chat_type: str) -> None:
    url = value.get("url") if isinstance(value, dict) else None
    if not isinstance(url, str) or not url.startswith("https://"):
        add("error", "web-app-url", f"{label!r} web_app.url must be an HTTPS URL")
    if chat_type and chat_type != "private":
        add("error", "web-app-chat", f"{label!r} web_app buttons work only in private chats, not {chat_type}")


def lint_reply_keyboard(markup: dict, add, chat_type: str = "") -> None:
    usable = check_rows(markup.get("keyboard"), add, "reply-structure")
    if not usable:
        add("error", "reply-structure", "reply keyboard has no buttons")
    for row in usable:
        for button in row:
            label = button.get("text", "")
            if not isinstance(label, str) or not label.strip():
                add("error", "button-text", "reply keyboard button text is empty")
                label = str(label)
            wrong = sorted(set(button) & {"callback_data", "url", "pay", "login_url", "copy_text"})
            if wrong:
                add("error", "reply-button-field", f"{label!r}: {wrong} are inline-keyboard fields and do nothing on a reply keyboard")
            special = sorted(set(button) & REPLY_ACTION_FIELDS)
            if len(special) > 1:
                add("error", "button-action", f"{label!r} can use at most one of {special}")
            if "web_app" in button:
                check_web_app(button["web_app"], label, add, chat_type)
            elif special and chat_type and chat_type != "private":
                add("error", "reply-private-only", f"{label!r}: {special[0]} works only in private chats, not {chat_type}")
            style = button.get("style")
            if style is not None and style not in STYLES:
                add("error", "button-style", f"{label!r} style must be one of {sorted(STYLES)}")
    placeholder = markup.get("input_field_placeholder")
    if placeholder is not None and not (isinstance(placeholder, str) and 1 <= len(placeholder) <= 64):
        add("error", "placeholder-length", "input_field_placeholder must be 1-64 characters")
    lint_labels(usable, add)


def lint_markup(markup: Any, add, chat_type: str = "", method: str = "") -> list[dict[str, Any]]:
    """Validate any reply_markup and return inline buttons for navigation checks."""
    if not markup:
        return []
    if not isinstance(markup, dict):
        add("error", "markup-type", f"reply_markup must be an object, got {type(markup).__name__}")
        return []
    kinds = [k for k in ("inline_keyboard", "keyboard", "remove_keyboard", "force_reply") if k in markup]
    if len(kinds) != 1:
        add("error", "markup-kind", f"reply_markup needs exactly one keyboard type, found {kinds}")
        return []
    if method in INLINE_ONLY_METHODS and kinds[0] != "inline_keyboard":
        add("error", "markup-edit", f"{method} accepts only an inline keyboard, not {kinds[0]}")
        return []
    if kinds[0] == "inline_keyboard":
        return lint_inline_keyboard(markup["inline_keyboard"], add, chat_type, method)
    if kinds[0] == "keyboard":
        lint_reply_keyboard(markup, add, chat_type)
    elif markup[kinds[0]] is not True:
        add("error", "markup-kind", f"{kinds[0]} must be true")
    if kinds[0] == "force_reply":
        placeholder = markup.get("input_field_placeholder")
        if placeholder is not None and not (isinstance(placeholder, str) and 1 <= len(placeholder) <= 64):
            add("error", "placeholder-length", "input_field_placeholder must be 1-64 characters")
    return []


def lint_copy(visible: str, bold_chars: int, has_keyboard: bool, add) -> None:
    lines = [line for line in visible.splitlines() if line.strip()]
    words = max(len(visible.split()), 1)
    emoji = len(EMOJI_RE.findall(visible))
    if emoji > max(2, words // 12):
        add("warning", "emoji-heavy", f"{emoji} emoji in {words} words")
    if len(lines) >= 4 and sum(1 for line in lines if EMOJI_RE.match(line.strip())) >= len(lines) * 0.75:
        add("warning", "emoji-bullets", "nearly every line starts with an emoji")
    if any(RULE_RE.match(line) for line in lines):
        add("warning", "decorative-rule", "decorative divider line; use spacing or bold labels")
    for line in lines:
        letters = [c for c in line if c.isalpha()]
        if len(line.split()) >= 3 and len(letters) >= 8 and all(c.isupper() for c in letters):
            add("warning", "all-caps", f"all-caps line: {line.strip()[:40]!r}")
    if visible.count("!") >= 3:
        add("warning", "exclamations", f"{visible.count('!')} exclamation marks")
    if len(visible) >= 40 and bold_chars / max(len(visible), 1) > 0.5:
        add("warning", "bold-heavy", "over half the text is bold, so nothing stands out")
    if has_keyboard and len(visible) > 900:
        add("warning", "long-with-keyboard", f"{len(visible)} characters above a keyboard push the buttons off screen")
    if len(visible) >= 500 and "\n\n" not in visible.strip() and bold_chars == 0:
        add("warning", "poor-hierarchy", f"{len(visible)} characters with no title or paragraph break")
    elif any(len(line) > 400 for line in lines):
        add("warning", "poor-hierarchy", "a single line over 400 characters is hard to read on a phone")
    for pattern, why in BOILERPLATE:
        if pattern.search(visible):
            add("warning", "boilerplate", f"{pattern.search(visible).group(0)!r}: {why}")


def lint_screen(screen: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append({"screen": str(screen.get("id", "?")), "level": level, "code": code, "message": message})

    kind = screen.get("kind", "")
    is_caption = "caption" in screen and "text" not in screen or kind == "caption"
    raw = screen.get("caption" if "caption" in screen else "text")
    markup = screen.get("reply_markup") or screen.get("keyboard") and {"inline_keyboard": screen["keyboard"]}
    if not isinstance(raw, str):
        if is_caption:
            raw = ""
        else:
            add("error", "text-missing", "screen has no text")
            return findings

    mode = str(screen.get("parse_mode") or "").lower()
    bold = 0
    if mode == "html":
        visible, bold, errors = parse_html(raw)
    elif mode == "markdownv2":
        visible, errors = parse_markdown_v2(raw)
    elif mode == "markdown":
        visible, errors = raw, []
        add("warning", "legacy-markdown", "parse_mode Markdown is legacy; use HTML or MarkdownV2")
    elif mode == "":
        visible, errors = raw, []
    else:
        visible, errors = raw, [("parse-mode", f"unknown parse_mode {screen.get('parse_mode')!r}")]
    for code, message in errors:
        add("error", code, message)

    length = utf16_len(visible)
    if kind == "callback_answer":
        if length > CALLBACK_ANSWER_LIMIT:
            add("error", "length", f"callback answer is {length} characters (limit {CALLBACK_ANSWER_LIMIT})")
        return findings
    limit = CAPTION_LIMIT if is_caption else TEXT_LIMIT
    entities = screen.get("entities")
    if entities:
        check_entities(entities, length, bool(mode), add)
    if not visible.strip() and not is_caption and kind != "draft":
        add("error", "text-empty", "text is empty after entity parsing")
    if length > limit:
        add("error", "length", f"{length} characters after parsing (limit {limit}); split it or use a rich message")

    buttons = lint_markup(markup, add, str(screen.get("chat_type") or ""), str(screen.get("method") or ""))
    lint_copy(visible, bold, bool(buttons), add)

    if kind in ("menu", "list", "detail", "form") and buttons:
        exits = [b for b in buttons if BACK_WORDS.search(b.get("text", "")) or BACK_WORDS.search(str(b.get("callback_data", "")))]
        if not exits:
            add("warning", "dead-end", "no Back, Menu, or Cancel on a navigable screen")
    if kind != "confirm":
        for button in buttons:
            label = button.get("text", "")
            if DESTRUCTIVE.search(label) and not CONFIRM_DATA.search(str(button.get("callback_data", ""))):
                add("warning", "unconfirmed-destructive", f"{label!r} looks destructive; route it through a confirm screen")
    return findings


def check_entities(entities: Any, length: int, has_mode: bool, add) -> None:
    if has_mode:
        add("warning", "entities-and-parse-mode", "entities are given, so parse_mode is ignored; send only one")
    if not isinstance(entities, list):
        add("error", "entities-type", "entities must be an array")
        return
    for entity in entities:
        if not isinstance(entity, dict) or not isinstance(entity.get("offset"), int) or not isinstance(entity.get("length"), int):
            add("error", "entities-type", "each entity needs integer offset and length")
        elif entity["length"] < 1 or entity["offset"] < 0 or entity["offset"] + entity["length"] > length:
            add("error", "entity-range", f"entity {entity.get('type')} at {entity['offset']}+{entity['length']} is outside the {length} UTF-16 unit text")


def lint_screens(screens: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings = [item for screen in screens for item in lint_screen(screen)]
    back_labels: set[str] = set()
    for screen in screens:
        markup = screen.get("reply_markup") or {"inline_keyboard": screen.get("keyboard") or []}
        for row in markup.get("inline_keyboard", []):
            for button in row:
                if BACK_LABEL_FAMILY.match(button.get("text", "")):
                    back_labels.add(button["text"])
    if len(back_labels) > 1:
        findings.append({
            "screen": "*", "level": "warning", "code": "inconsistent-back",
            "message": f"one action has several labels: {sorted(back_labels)}",
        })
    return findings


TEXT_METHODS = {"sendMessage", "editMessageText", "editEphemeralMessageText"}
CAPTION_METHODS = {
    "sendPhoto", "sendVideo", "sendAudio", "sendDocument", "sendAnimation", "sendVoice", "sendLivePhoto",
    "sendPaidMedia", "copyMessage", "editMessageCaption", "editEphemeralMessageCaption", "sendWidget",
}
WIDGET_DATA_METHODS = {"sendWidget", "editMessageWidgetData", "editSharedWidgetData", "answerWidgetQuery"}
MARKUP_METHODS = {"editMessageReplyMarkup", "editMessageMedia", "editEphemeralMessageReplyMarkup", "sendSticker", "sendVideoNote", "sendLocation", "sendVenue", "sendContact", "sendPoll", "sendDice"}
JSON_FIELDS = ("reply_markup", "media", "prices", "entities", "caption_entities", "commands", "rich_message", "link_preview_options")
RICH_LIMIT = 32768


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Some libraries hand over JSON strings for complex fields."""
    clean = dict(params)
    for field in JSON_FIELDS:
        value = clean.get(field)
        if isinstance(value, str) and value[:1] in "[{":
            try:
                clean[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return clean


def check_invoice(method: str, params: dict[str, Any], add) -> None:
    title, description, payload = params.get("title"), params.get("description"), params.get("payload")
    if not isinstance(title, str) or not 1 <= len(title) <= 32:
        add("error", "invoice-title", "title must be 1-32 characters")
    if not isinstance(description, str) or not 1 <= len(description) <= 255:
        add("error", "invoice-description", "description must be 1-255 characters")
    if not isinstance(payload, str) or not 1 <= len(payload.encode("utf-8")) <= 128:
        add("error", "invoice-payload", "payload must be 1-128 bytes")
    prices = params.get("prices")
    if not isinstance(prices, list) or not prices:
        add("error", "invoice-prices", "prices must be a non-empty list")
        prices = []
    if params.get("currency") == "XTR":
        if len(prices) != 1:
            add("error", "stars-prices", "Telegram Stars invoices need exactly one price item")
        if params.get("provider_token"):
            add("error", "stars-provider", "Telegram Stars invoices must have an empty provider_token")
    period = params.get("subscription_period")
    if period is not None:
        if method != "createInvoiceLink":
            add("error", "subscription-method", "subscription_period exists only on createInvoiceLink")
        if period != 2592000 or params.get("currency") != "XTR":
            add("error", "subscription-period", "subscriptions need currency XTR and subscription_period 2592000")
        if prices and isinstance(prices[0], dict) and prices[0].get("amount", 0) > 10000:
            add("error", "subscription-price", "subscription price must not exceed 10000 Stars")


def check_widget(method: str, params: dict[str, Any], chat_type: str, add) -> None:
    """Bot API 10.4 HTML widgets: byte limits on the HTML and on each data field."""
    import zlib
    if method == "sendWidget":
        html = params.get("html")
        size = len(html.encode("utf-8")) if isinstance(html, str) else 0
        if not 1 <= size <= 32768:
            add("error", "widget-html", f"widget html must be 1-32768 bytes, got {size}")
        elif len(zlib.compress(html.encode("utf-8"), 9)) > 4096:
            add("error", "widget-html-compressed", "widget html must be at most 4096 bytes after maximum zlib compression")
        if chat_type and chat_type != "private":
            add("error", "widget-chat", "in production, widgets can be sent only to private chats")
    for field in ("public_data", "chat_data", "data"):
        value = params.get(field)
        if isinstance(value, str) and len(value.encode("utf-8")) > 1024:
            add("error", "widget-data", f"{field} must be at most 1024 bytes")
    cache_time = params.get("cache_time")
    if method == "editSharedWidgetData" and cache_time is not None and not 5 <= int(cache_time) <= 3600:
        add("error", "widget-cache-time", "cache_time must be 5-3600 seconds")


def lint_call(method: str, params: dict[str, Any], location: str, chat_type: str = "") -> list[dict[str, str]]:
    """Validate one captured Bot API call. Unknown methods are ignored, never guessed at."""
    params = normalize_params(params)
    findings: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append({"screen": location, "level": level, "code": code, "message": message})

    common = {"id": location, "method": method, "chat_type": chat_type, "reply_markup": params.get("reply_markup")}
    if method in WIDGET_DATA_METHODS:
        check_widget(method, params, chat_type, add)
        if method != "sendWidget":
            return findings
    if method in TEXT_METHODS or method == "sendMessageDraft":
        if method == "editMessageText" and "rich_message" in params and "text" not in params:
            check_rich(params.get("rich_message"), add)
            return findings
        kind = "draft" if method == "sendMessageDraft" else ""
        return lint_screen({**common, "text": params.get("text"), "parse_mode": params.get("parse_mode"), "entities": params.get("entities"), "kind": kind})
    if method in CAPTION_METHODS:
        return findings + lint_screen({**common, "caption": params.get("caption") or "", "parse_mode": params.get("parse_mode"), "entities": params.get("caption_entities"), "kind": "caption"})
    if method == "answerCallbackQuery":
        if not params.get("callback_query_id"):
            add("error", "callback-id", "answerCallbackQuery needs callback_query_id")
        return findings + lint_screen({"id": location, "text": params.get("text") or "", "kind": "callback_answer"})
    if method in MARKUP_METHODS:
        lint_markup(params.get("reply_markup"), add, chat_type, method)
    elif method == "sendMediaGroup":
        media = params.get("media")
        if not isinstance(media, list) or not 2 <= len(media) <= 10:
            add("error", "media-group-size", "sendMediaGroup needs 2-10 items")
            media = []
        for item in media:
            if isinstance(item, dict) and item.get("caption"):
                findings += lint_screen({"id": location, "caption": item["caption"], "parse_mode": item.get("parse_mode"), "kind": "caption"})
    elif method in ("sendInvoice", "createInvoiceLink"):
        check_invoice(method, params, add)
        if method == "sendInvoice":
            lint_markup(params.get("reply_markup"), add, chat_type, method)
    elif method == "answerPreCheckoutQuery":
        if params.get("ok") is False and not params.get("error_message"):
            add("error", "precheckout-message", "error_message is required when ok is false")
    elif method in ("sendRichMessage", "sendRichMessageDraft"):
        check_rich(params.get("rich_message"), add)
        lint_markup(params.get("reply_markup"), add, chat_type, method)
    elif method == "setMyCommands":
        commands = params.get("commands")
        if not isinstance(commands, list) or len(commands) > 100:
            add("error", "commands-count", "commands must be a list of at most 100")
            commands = []
        for command in commands:
            name, text = command.get("command", ""), command.get("description", "")
            if not re.fullmatch(r"[a-z0-9_]{1,32}", str(name)):
                add("error", "command-name", f"{name!r} must be 1-32 lowercase letters, digits, or underscores")
            if not 1 <= len(str(text)) <= 256:
                add("error", "command-description", f"{name!r} description must be 1-256 characters")
    return findings


def check_rich(rich: Any, add) -> None:
    if not isinstance(rich, dict):
        add("error", "rich-type", "rich_message must be an object")
        return
    used = [k for k in ("html", "markdown", "blocks") if k in rich]
    if len(used) != 1:
        add("error", "rich-content", f"rich_message needs exactly one of html, markdown, blocks; found {used}")
    for field in ("html", "markdown"):
        if isinstance(rich.get(field), str) and utf16_len(rich[field]) > RICH_LIMIT:
            add("error", "length", f"rich message source exceeds {RICH_LIMIT} characters")


def load_capture(path: Path) -> list[dict[str, Any]]:
    """Return interactions from one capture file or a directory of them."""
    files = sorted(path.glob("capture-*.json")) if path.is_dir() else [path]
    interactions: list[dict[str, Any]] = []
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        for item in data.get("interactions", []):
            interactions.append({**item, "framework": data.get("framework", "unknown")})
    return interactions


def load_handlers(path: Path) -> list[dict[str, Any]] | None:
    """Merge the handler registries saved by adapters that can inspect their framework."""
    files = sorted(path.glob("capture-*.json")) if path.is_dir() else [path]
    merged: dict[str, dict[str, Any]] = {}
    seen_registry = False
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        if "handlers" not in data:
            continue
        seen_registry = True
        for handler in data["handlers"]:
            entry = merged.setdefault(handler["key"], {**handler, "runs": 0})
            entry["runs"] += int(handler.get("runs", 0))
    return list(merged.values()) if seen_registry else None


SOURCE_SKIP = {".git", ".venv", "venv", "node_modules", "site-packages", "tg_quality", "tests", "test", "__pycache__", ".tg-lint", ".claude", "dist", "build"}
SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".ts"}
_LITERAL = r"(f?)(\"|')((?:\\.|(?!\2).)*)\2"
_CALLBACK_LITERAL = re.compile(r"callback_data[\"']?\s*[=:]\s*" + _LITERAL)
_CALLBACK_ANY = re.compile(r"callback_data[\"']?\s*[=:]\s*([^,)}\n]+)")
_GRAMMY_TEXT = re.compile(r"\.text\(\s*(?:\"[^\"]*\"|'[^']*'|`[^`]*`|[\w.]+)\s*,\s*(\"|'|`)((?:\\.|(?!\1).)*)\1")
_CALLBACK_FACTORY = re.compile(r"class\s+\w+\(\s*CallbackData\s*,\s*prefix\s*=\s*[\"'](\w+)[\"']")


def source_callbacks(root: Path, limit: int = 400) -> dict[str, list[dict[str, Any]]]:
    """Find callback_data the source can build. Regex-based and uncertain by design."""
    literal: list[dict[str, Any]] = []
    dynamic: list[dict[str, Any]] = []
    files = [p for p in sorted(root.rglob("*")) if p.suffix in SOURCE_SUFFIXES and p.is_file()
             and not SOURCE_SKIP & set(p.relative_to(root).parts[:-1])
             and not p.name.startswith("test_") and ".test." not in p.name and not p.name.endswith("_test.py") and p.name != "conftest.py"]
    for file in files[:limit]:
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        where = str(file.relative_to(root))
        for number, line in enumerate(lines, 1):
            found = False
            for match in _CALLBACK_LITERAL.finditer(line):
                found = True
                value = match.group(3)
                prefix = re.split(r"\{", value, 1)[0] if match.group(1) else value
                literal.append({"file": where, "line": number, "pattern": prefix, "exact": not match.group(1)})
            for match in _GRAMMY_TEXT.finditer(line):
                found = True
                value = match.group(2)
                exact = "${" not in value
                literal.append({"file": where, "line": number, "pattern": value.split("${", 1)[0], "exact": exact})
            for match in _CALLBACK_FACTORY.finditer(line):
                found = True
                literal.append({"file": where, "line": number, "pattern": match.group(1) + ":", "exact": False})
            if not found:
                for match in _CALLBACK_ANY.finditer(line):
                    expression = match.group(1).strip()
                    if expression and expression not in ("None",) and not expression.startswith(("'", '"')):
                        dynamic.append({"file": where, "line": number, "expression": expression[:60]})
    return {"literal": literal, "dynamic": dynamic}


def pattern_of(value: str) -> str:
    """Group dynamic callback data, so open:12 and open:13 are one route."""
    return re.sub(r"\d+", "#", value)


def offered_callbacks(call: dict[str, Any]) -> list[str]:
    markup = normalize_params(call.get("params", {})).get("reply_markup")
    rows = markup.get("inline_keyboard") if isinstance(markup, dict) else None
    found = []
    for row in rows if isinstance(rows, list) else []:
        for button in row if isinstance(row, list) else []:
            if isinstance(button, dict) and button.get("callback_data"):
                found.append(str(button["callback_data"]))
    return found


def route_stem(value: str) -> str:
    """The fixed part of callback data, up to its last separator: product:12 and product:abc share product:."""
    match = re.match(r"^(.*[:|/])", value)  # not - or _, which appear inside slugs
    return match.group(1) if match else value


def coverage_report(interactions: list[dict[str, Any]], handlers: list[dict[str, Any]] | None = None,
                    sources: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Describe what the tests exercised, and what they provably or possibly missed.

    Confirmed gaps come from the capture and the framework's own handler registry.
    Static findings come from a regex scan of the source and may be dead code.
    """
    offered: set[str] = set()
    offered_raw: set[str] = set()
    pressed: set[str] = set()
    paths: dict[tuple, dict[str, Any]] = {}
    for item in interactions:
        trigger = f"{item.get('kind')}:{pattern_of(str(item.get('value')))}"
        if item.get("kind") == "callback":
            pressed.add(pattern_of(str(item.get("value"))))
        produced: list[str] = []
        for call in item.get("calls", []):
            data = offered_callbacks(call)
            offered_raw.update(data)
            produced += [pattern_of(d) for d in data]
        offered.update(produced)
        key = (trigger, tuple(item.get("handlers", [])), tuple(sorted(set(produced))))
        path = paths.setdefault(key, {"trigger": trigger, "handlers": list(key[1]), "offers": list(key[2]), "count": 0,
                                      "replies": sorted({str(c.get("method")) for c in item.get("calls", [])})})
        path["count"] += 1
    not_pressed = sorted(offered - pressed)
    offered_stems = {route_stem(d) for d in offered_raw}
    # With a separator, a shown route's stem covers stale or edge-case values (product:abc, cancel:). Without one, only an exact match does.
    pressed_unoffered = sorted(p for p in pressed - offered if not re.search(r"[:|/]", p) or route_stem(p) not in offered_stems)
    report: dict[str, Any] = {
        "interactions": len(interactions),
        "scenarios": sorted({str(i.get("scenario", "")) for i in interactions}),
        "commands": sorted({str(i.get("value")).split()[0] for i in interactions if i.get("kind") == "command"}),
        "kinds": sorted({str(i.get("kind")) for i in interactions}),
        "buttons_offered": len(offered),
        "buttons_pressed": len(offered & pressed),
        "button_coverage": round(len(offered & pressed) / len(offered), 3) if offered else None,
        "offered_never_pressed": not_pressed,
        "pressed_never_offered": pressed_unoffered,
        "paths": sorted(paths.values(), key=lambda p: p["trigger"]),
        "handlers": None,
        "static": None,
    }
    confirmed: list[str] = []
    uncertain: list[str] = []
    direct_only: list[str] = []
    for route in pressed_unoffered:
        builders = [s for s in (sources or {}).get("literal", [])
                    if (s["exact"] and pattern_of(s["pattern"]) == route) or (not s["exact"] and s["pattern"] and route.startswith(pattern_of(s["pattern"])))]
        if builders:
            site = builders[0]
            confirmed.append(f"callback {route!r} was only sent directly; no captured screen offered it, though {site['file']}:{site['line']} builds it")
        else:
            direct_only.append(route)
    report["sent_directly_only"] = direct_only
    if handlers is not None:
        ran = sorted(h["key"] for h in handlers if h["runs"])
        never = sorted(handlers, key=lambda h: h["key"])
        never = [h for h in never if not h["runs"]]
        report["handlers"] = {"known": len(handlers), "ran": ran, "never_ran": [{k: h[k] for k in ("key", "event", "detail") if k in h} for h in never]}
        confirmed += [f"handler {h['key']} ({h.get('detail') or h.get('event')}) never ran" for h in never]
    if sources is not None:
        unreached = []
        for site in sources["literal"]:
            pattern = site["pattern"]
            hit = (pattern in offered_raw) if site["exact"] else (bool(pattern) and any(d.startswith(pattern) for d in offered_raw))
            if not hit and pattern:
                unreached.append(site)
        report["static"] = {"callback_sites": len(sources["literal"]), "never_captured": unreached, "dynamic": sources["dynamic"]}
        uncertain += [f"{s['file']}:{s['line']} builds callback_data {s['pattern']!r}{'' if s['exact'] else '...'}, never seen on a captured keyboard"
                      for s in unreached]
        uncertain += [f"{s['file']}:{s['line']} builds callback_data from {s['expression']}; cannot be checked statically" for s in sources["dynamic"]]
    if direct_only:
        uncertain.append(f"callbacks sent only directly and not built anywhere the scan can see (stale or forged test data?): {direct_only[:8]}")
    report["confirmed_gaps"] = confirmed
    report["uncertain_gaps"] = uncertain
    report["note"] = ("Covers only simulated interactions; screens no test reached are not checked. A handler that ran may have taken only one branch, such as a refusal. "
                      "Pressing every observed button does not prove every screen was reached."
                      + ("" if handlers is not None else " Handler inspection is unavailable for this framework."))
    return report


def finding_line(f: dict[str, Any]) -> str:
    """One printable line per finding, naming every place a repeated problem occurred."""
    line = f"{f['level']:7} {f['screen']}: [{f['code']}] {f['message']}"
    if f.get("count", 1) > 1:
        others = f["screens"][1:6]
        line += f" (x{f['count']}; also {', '.join(others)}{', ...' if len(f['screens']) > 6 else ''})"
    return line


def coverage_lines(coverage: dict[str, Any], limit: int = 12) -> list[str]:
    """Human-readable coverage summary shared by the CLI and the pytest plugin."""
    lines = [f"{coverage['interactions']} interactions, {len(coverage['scenarios'])} scenarios; "
             f"pressed {coverage['buttons_pressed']}/{coverage['buttons_offered']} offered button routes"]
    if coverage.get("handlers"):
        known = coverage["handlers"]["known"]
        lines.append(f"handlers run {known - len(coverage['handlers']['never_ran'])}/{known} registered")
    if coverage["offered_never_pressed"]:
        lines.append(f"never pressed: {coverage['offered_never_pressed'][:limit]}")
    for gap in coverage.get("confirmed_gaps", [])[:limit]:
        lines.append(f"coverage gap: {gap}")
    for gap in coverage.get("uncertain_gaps", [])[:limit]:
        lines.append(f"possible gap (static, unverified): {gap}")
    lines.append(coverage["note"])
    return lines


def lint_capture(interactions: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    screens: list[dict[str, Any]] = []
    openings: dict[str, set[str]] = {}  # opening line -> distinct full texts
    repeats: dict[str, set[str]] = {}
    for index, item in enumerate(interactions):
        where = f"{item.get('scenario', '?')}#{index}"
        trigger = f"{item.get('kind')}:{pattern_of(str(item.get('value')))}"
        calls = item.get("calls", [])
        chat_type = str(item.get("chat_type") or "")
        for call in calls:
            location = f"{where}:{call.get('method')}"
            findings += lint_call(str(call.get("method")), call.get("params") or {}, location, chat_type)
            params = normalize_params(call.get("params") or {})
            text = params.get("text") if call.get("method") in TEXT_METHODS else None
            if isinstance(text, str) and text.strip():
                screens.append({"id": location, "text": text, "reply_markup": params.get("reply_markup")})
                visible = re.sub(r"<[^>]+>", "", text).strip()
                if not visible:
                    continue
                if not offered_callbacks(call):  # a menu reached from several places is normal
                    repeats.setdefault(visible, set()).add(trigger)
                first = visible.splitlines()[0].strip()
                if len(first) >= 12 and first != visible:
                    openings.setdefault(first, set()).add(visible)
        if item.get("error") and not item.get("expected_error"):
            findings.append({"screen": where, "level": "error", "code": "handler-exception", "message": f"handler raised during {trigger}: {str(item['error'])[:160]}"})
        methods = [str(c.get("method")) for c in calls]
        if item.get("kind") == "callback":
            if "answerCallbackQuery" not in methods:
                findings.append({"screen": where, "level": "error", "code": "callback-unanswered", "message": f"{trigger} was never answered, so the button keeps spinning"})
            sent_keyboard = any(c.get("method") == "sendMessage" and offered_callbacks(c) for c in calls)
            if sent_keyboard and not any(m.startswith("edit") for m in methods):
                findings.append({"screen": where, "level": "warning", "code": "callback-new-message", "message": f"{trigger} sent a new menu instead of editing the current message"})
        elif item.get("kind") in ("command", "text") and not calls and not item.get("expected_silence"):
            findings.append({"screen": where, "level": "warning", "code": "no-response", "message": f"{trigger} produced no outgoing message"})
    for visible, triggers in repeats.items():
        if len(triggers) >= 3 and len(visible) >= 20:
            findings.append({"screen": "*", "level": "warning", "code": "repeated-text", "message": f"same text from {len(triggers)} different actions: {visible[:50]!r}"})
    for first, texts in openings.items():
        if len(texts) >= 3:
            findings.append({"screen": "*", "level": "warning", "code": "repeated-opening", "message": f"{len(texts)} different messages open with {first[:50]!r}"})
    # Cross-screen label consistency, reusing the screen-level rule.
    findings += [f for f in lint_screens(screens) if f["code"] == "inconsistent-back"]
    # One entry per distinct problem, keeping every place it occurred.
    unique: dict[tuple, dict[str, Any]] = {}
    for f in findings:
        entry = unique.setdefault((f["level"], f["code"], f["message"]), {**f, "count": 0, "screens": []})
        entry["count"] += 1
        if f["screen"] not in entry["screens"]:
            entry["screens"].append(f["screen"])
    return list(unique.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", help="JSON file of screens, or - for stdin")
    parser.add_argument("--capture", help="capture file or directory from the quality-gate adapters")
    parser.add_argument("--report", help="also write the full result to this JSON file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    parser.add_argument("--min-button-coverage", type=float, default=0.0, help="exit 1 if fewer offered buttons were pressed")
    parser.add_argument("--source", help="project directory to scan for callback_data that tests never showed")
    parser.add_argument("--require-coverage", action="store_true", help="exit 1 on confirmed coverage gaps")
    args = parser.parse_args(argv)
    if bool(args.path) == bool(args.capture):
        print("bad input: give either a screens file or --capture", file=sys.stderr)
        return 2
    coverage = None
    try:
        if args.capture:
            interactions = load_capture(Path(args.capture))
            findings = lint_capture(interactions)
            sources = source_callbacks(Path(args.source)) if args.source else None
            coverage = coverage_report(interactions, load_handlers(Path(args.capture)), sources)
            count = len(interactions)
        else:
            raw = sys.stdin.read() if args.path == "-" else Path(args.path).read_text(encoding="utf-8")
            data = json.loads(raw)
            screens = data if isinstance(data, list) else [data]
            if not all(isinstance(s, dict) for s in screens):
                print("bad input: expected an object or a list of objects", file=sys.stderr)
                return 2
            findings = lint_screens(screens)
            count = len(screens)
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 2

    errors = sum(f["level"] == "error" for f in findings)
    warnings = len(findings) - errors
    low_coverage = bool(coverage and coverage["button_coverage"] is not None and coverage["button_coverage"] < args.min_button_coverage)
    low_coverage = low_coverage or bool(coverage and args.require_coverage and coverage["confirmed_gaps"])
    result = {"errors": errors, "warnings": warnings, "findings": findings, "coverage": coverage}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for f in sorted(findings, key=lambda item: item["level"]):
            print(finding_line(f))
        unit = "interaction" if coverage else "screen"
        print(f"{count} {unit}(s): {errors} error(s), {warnings} warning(s)")
        if coverage:
            print("\n".join(coverage_lines(coverage)))
    return 1 if errors or low_coverage or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
