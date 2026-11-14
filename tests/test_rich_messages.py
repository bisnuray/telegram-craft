"""Rich messages are the default screen type, so the linter and the gate treat them as first-class screens."""
import json
import subprocess
import sys

from test_quality_gate import SKILL
from test_quality_gate import core as lint

LINT = str(SKILL / "scripts/tg_lint.py")
MENU = {"inline_keyboard": [[{"text": "⚙️ Settings", "callback_data": "v1:settings"}]]}
SCREEN = '<h3>📡 Media relay</h3><p>🟢 <b>Running</b></p><ul><li>Travel group</li></ul>'


def codes(findings):
    return [f["code"] for f in findings]


def test_rich_screen_in_screens_file_is_valid(tmp_path):
    path = tmp_path / "screens.json"
    path.write_text(json.dumps([{"id": "home", "rich_message": {"html": SCREEN}, "reply_markup": MENU}]))
    result = subprocess.run([sys.executable, LINT, str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
    assert "text-missing" not in result.stdout


def test_rich_screen_keyboard_is_still_checked():
    bad = {"inline_keyboard": [[{"text": "Go", "callback_data": "y" * 80}]]}
    assert "callback-bytes" in codes(lint.lint_screen({"id": "s", "rich_message": {"html": SCREEN}, "reply_markup": bad}))


def test_rich_edit_checks_its_keyboard():
    bad = {"inline_keyboard": [[{"text": "Go", "callback_data": "y" * 80}]]}
    params = {"chat_id": 1, "message_id": 2, "rich_message": {"html": SCREEN}, "reply_markup": bad}
    assert "callback-bytes" in codes(lint.lint_call("editMessageText", params, "e"))


def test_buttons_inside_rich_content_are_offered_and_size_checked():
    rich = {"html": '<tg-button type="callback_data" data="v1:a&amp;b">A</tg-button>'
                    "<tg-button data='" + "x" * 70 + "' type=\"callback_data\">B</tg-button>"
                    '<tg-button type="url" url="https://t.me">C</tg-button>'}
    assert lint.rich_callbacks(rich) == ["v1:a&b", "x" * 70]
    assert lint.rich_callbacks({"blocks": [{"buttons": [[{"text": "Z", "callback_data": "v1:z"}]]}]}) == ["v1:z"]
    assert "callback-bytes" in codes(lint.lint_call("sendRichMessage", {"chat_id": 1, "rich_message": rich}, "s"))
    call = {"method": "sendRichMessage", "params": {"chat_id": 1, "rich_message": rich, "reply_markup": MENU}}
    assert set(lint.offered_callbacks(call)) == {"v1:settings", "v1:a&b", "x" * 70}


def test_callback_that_sends_a_new_rich_menu_is_flagged():
    interaction = {"scenario": "s", "kind": "callback", "value": "v1:settings", "calls": [
        {"method": "answerCallbackQuery", "params": {"callback_query_id": "1"}},
        {"method": "sendRichMessage", "params": {"chat_id": 1, "rich_message": {"html": SCREEN}, "reply_markup": MENU}}]}
    assert "callback-new-message" in codes(lint.lint_capture([interaction]))
    interaction["calls"][1] = {"method": "editMessageText", "params": {"chat_id": 1, "message_id": 5, "rich_message": {"html": SCREEN}, "reply_markup": MENU}}
    assert "callback-new-message" not in codes(lint.lint_capture([interaction]))


# Design guidance: references/rich-messages.md, assets/rich_html.py, and the rich-* warnings.
import importlib.util
import re

RICH_DOC = SKILL / "references/rich-recipes.md"
_spec = importlib.util.spec_from_file_location("rich_html", SKILL / "assets/rich_html.py")
rich_html = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rich_html)


def doc_examples():
    return re.findall(r"```html\n(.*?)```", RICH_DOC.read_text(), re.DOTALL)


def rich_codes(html):
    return codes(lint.lint_call("sendRichMessage", {"chat_id": 1, "rich_message": {"html": html}}, "s"))


def test_builder_self_test_passes():
    result = subprocess.run([sys.executable, str(SKILL / "assets/rich_html.py"), "--self-test"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_builder_escapes_user_text_and_builds_a_standard_screen():
    h = rich_html
    evil = '<tg-button type="callback_data" data="v1:admin">x</tg-button>'
    html = h.screen(h.title("Media relay", level=2), h.status("Running", "3 sources"),
                    h.facts([("Target", evil), ("Mode", "Copy")]),
                    h.section("Sources", h.table(["Chat", "Posts"], [[evil, 4]], align=["left", "right"])))
    assert "<tg-button" not in html and lint.rich_callbacks({"html": html}) == []
    assert "<table bordered" in html
    assert rich_codes(html) == []


def test_reference_has_recipes_for_every_screen_type():
    text = RICH_DOC.read_text()
    for recipe in ("Home or dashboard", "Picker", "Detail view", "Data list", "Settings", "Help",
                   "Receipt", "Report", "Problem", "Confirmation", "Progress", "Messy versus standard"):
        assert f"## {recipe}" in text


MESSY_KEYBOARD = {"inline_keyboard": [[{"text": "Travel group", "callback_data": "v1:s:1"}],
                                      [{"text": "Photo drops", "callback_data": "v1:s:2"}]]}


def test_reference_examples_are_valid_and_only_the_messy_one_warns():
    examples = doc_examples()
    assert len(examples) >= 12
    for html in examples:
        assert rich_html.check(html) == [], html[:60]
    messy, recipes = examples[-1], examples[:-1]
    assert {"rich-emoji", "rich-table-unbordered", "rich-repeats-keyboard"} <= set(
        codes(lint.lint_call("sendRichMessage", {"chat_id": 1, "rich_message": {"html": messy}, "reply_markup": MESSY_KEYBOARD}, "s")))
    for html in recipes:
        assert rich_codes(html) == [], html[:60]
        assert "<table>" not in html and "<table compact>" not in html


def test_messy_rich_screens_warn_but_never_error():
    cases = {
        "rich-no-title": "<p>Added</p><h3>Relay</h3><table bordered><tr><th>A</th></tr><tr><td>1</td></tr></table>",
        "rich-one-row-table": "<h3>Relay</h3><table bordered compact><tr><td><b>Target</b></td><td>X</td></tr></table>",
        "rich-fake-structure": "<h3>Relay</h3><p>━━━━━━</p><p>• one<br>• two</p>",
        "rich-many-quotes": "<h3>Relay</h3><blockquote>a</blockquote><blockquote>b</blockquote>",
        "rich-many-marks": "<h3>Relay</h3><p><mark>a</mark> <mark>b</mark></p>",
        "rich-emoji": "<h3>📡 Relay</h3><p><b>Running</b></p>",
        "rich-table-unbordered": "<h3>Relay</h3><table><tr><th>A</th></tr><tr><td>1</td></tr></table>",
        "rich-busy": "<h3>Relay</h3>" + "<p>x</p>" * 9,
    }
    for code, html in cases.items():
        findings = lint.lint_call("sendRichMessage", {"chat_id": 1, "rich_message": {"html": html}}, "s")
        assert code in codes(findings), code
        assert all(f["level"] == "warning" for f in findings if f["code"].startswith("rich-")), code
    picker = "<h3>Add a source</h3><ul><li>Travel group</li><li>📷 Photo drops</li></ul>"
    params = {"chat_id": 1, "rich_message": {"html": picker}, "reply_markup": MESSY_KEYBOARD}
    assert "rich-repeats-keyboard" in codes(lint.lint_call("sendRichMessage", params, "s"))
    assert "rich-repeats-keyboard" in codes(lint.lint_call("editMessageText", {**params, "message_id": 2}, "e"))
    assert "rich-emoji" not in rich_codes("<h3>Plan</h3><p><b>Pro</b> · 350 ⭐</p>"), "the Stars sign is a currency"


def test_one_divider_between_summary_and_body_is_fine_misuse_warns():
    good = ("<h2>Media relay</h2><p><b>Running</b></p><table bordered compact><tr><td><b>A</b></td><td>1</td></tr>"
            "<tr><td><b>B</b></td><td>2</td></tr></table><hr/><h4>Sources</h4><ul><li>Travel group</li></ul>")
    assert "rich-divider" not in rich_codes(good)
    for bad in ("<h3>Relay</h3><hr/><p>x</p>",                      # right after the title
                "<h3>Relay</h3><p>x</p><hr/>",                      # last
                "<h3>Relay</h3><p>a</p><hr/><hr/><p>b</p>",         # doubled
                "<h3>R</h3><p>a</p><hr/><p>b</p><hr/><p>c</p><hr/><p>d</p>"):  # more than two
        assert "rich-divider" in rich_codes(bad), bad
    assert "<hr/>" in doc_examples()[0], "the home recipe shows the divider"


def test_empty_cells_and_parse_mode_with_rich_warn():
    assert "rich-empty-cell" in rich_codes("<h3>Order</h3><table bordered><tr><th>A</th><th>B</th></tr><tr><td>1</td><td></td></tr></table>")
    assert "rich-empty-cell" not in rich_codes('<h3>Order</h3><table bordered><tr><th>A</th><th>B</th></tr><tr><td colspan="2">1</td></tr></table>')
    edit = {"chat_id": 1, "message_id": 2, "rich_message": {"html": "<h3>T</h3><p>x</p>"}, "parse_mode": "HTML"}
    assert "rich-parse-mode" in codes(lint.lint_call("editMessageText", edit, "e"))
    assert "rich-parse-mode" in codes(lint.lint_call("sendRichMessage", edit, "s"))
    edit.pop("parse_mode")
    assert "rich-parse-mode" not in codes(lint.lint_call("editMessageText", edit, "e"))


def test_builder_never_emits_invisible_cells():
    html = rich_html.table(["Item", "Qty", "Price"], [["A", None, 5]], total=["Total", None, 5])
    assert "rich-empty-cell" not in rich_codes("<h3>T</h3>" + html)
    assert 'colspan="2"' in html


# Full rich HTML validation: what Telegram rejects is an error, before any request is sent.
OFFICIAL_SAMPLE = """<a name="chapter-0"></a><b>b</b> <i>i</i> <u>u</u> <s>s</s> <code>c</code> <mark>m</mark> <sub>x</sub> <sup>y</sup>
<tg-spoiler>s</tg-spoiler> <a href="#note-1">Reference</a> <tg-reference name="note-1">Referenced</tg-reference>
<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji> <img src="tg://emoji?id=5368324170671202286" alt="👍"/>
<tg-time unix="1647531900" format="wDT">22:45 tomorrow</tg-time> <tg-math>x^2</tg-math> &mdash; &hellip; &#169;
<h4>H</h4><p>P</p><pre><code class="language-python">print(1)</code></pre><footer>F</footer><hr/>
<ol start="3" type="a" reversed><li>o</li></ol><ul><li><input type="checkbox" checked>Done</li></ul>
<blockquote>Q<br>Q<cite>A</cite></blockquote><blockquote expandable>E</blockquote><aside>P<cite>A</cite></aside>
<figure><img src="https://telegram.org/example/photo.jpg" tg-spoiler/><figcaption>C<cite>C</cite></figcaption></figure>
<tg-map lat="41.9" long="12.5" zoom="14"/><tg-collage><img src="https://telegram.org/a.jpg"/><video src="https://telegram.org/a.mp4"/></tg-collage>
<table bordered striped compact><caption>T</caption><tr><td colspan="2" rowspan="2" align="left">V</td><td align="center">V2</td></tr>
<tr><td valign="top">V4</td></tr></table><details open><summary>S</summary>C</details><tg-math-block>E = mc^2</tg-math-block>
<tg-button-row align="left"><tg-button type="url" style="success" url="https://t.me">u</tg-button>
<tg-button type="callback_data" style="link" data="cb">c</tg-button><tg-button type="copy_text" text="x">Copy</tg-button>
<tg-button type="disabled">D</tg-button></tg-button-row>"""


def rich_errors(html, method="sendRichMessage", **extra):
    findings = lint.lint_call(method, {"chat_id": 1, "rich_message": {"html": html, **extra}}, "s")
    return [f["code"] for f in findings if f["level"] == "error"]


def test_documented_rich_html_passes_validation():
    assert rich_errors(OFFICIAL_SAMPLE) == []
    for html in doc_examples():
        assert rich_errors(html) == [], html[:60]
    assert rich_errors("<tg-thinking>Thinking…</tg-thinking>", "sendRichMessageDraft") == []


def test_rich_html_that_telegram_rejects_is_an_error():
    cases = {
        "rich-tag": ["<table bordered><thead><tr><th>A</th></tr></thead></table>", "<span>x</span>", "<div>x</div>",
                     "<tg-thinking>x</tg-thinking>"],
        "rich-entity": ["<p>&copy; 2026</p>", "<p>a &rarr; b</p>"],
        "rich-nesting": ["<li>x</li>", "<table><td>x</td></table>", "<ul><p>x</p></ul>", "<p><input type=\"checkbox\">x</p>",
                         "<tg-button-row><b>x</b></tg-button-row>"],
        "rich-unbalanced": ["<p><b>x</p>", "<p>x", "</p>"],
        "rich-attr": ['<tg-time unix="1" format="X">x</tg-time>', '<tg-time format="t">x</tg-time>',
                      '<table><tr><td align="middle">x</td></tr></table>', "<a>x</a>", '<ol type="z"><li>x</li></ol>'],
        "rich-button": ['<tg-button type="callback">x</tg-button>', '<tg-button type="callback_data">x</tg-button>',
                        '<tg-button type="url" url="https://t.me" style="red">x</tg-button>'],
        "rich-media": ['<img src="ftp://x/a.jpg"/>', '<img src="tg://photo?id=cover"/>'],
        "rich-columns": ["<table><tr>" + "<td>x</td>" * 21 + "</tr></table>"],
    }
    for code, samples in cases.items():
        for html in samples:
            assert code in rich_errors(html), (code, html)


def test_rich_media_references_must_match_the_media_list():
    media = [{"id": "cover", "media": {"type": "photo", "media": "attach://cover"}}]
    assert rich_errors('<img src="tg://photo?id=cover"/>', media=media) == []
    findings = lint.lint_call("sendRichMessage", {"chat_id": 1, "rich_message": {"html": "<p>x</p>", "media": media}}, "s")
    assert "rich-media-unused" in codes(findings)
    assert "rich-media" in rich_errors("<p>x</p>", media=[{"id": "bad id!", "media": {}}])
    too_many = "".join(f'<img src="https://t.me/{n}.jpg"/>' for n in range(51))
    assert "rich-media" in rich_errors(too_many)
