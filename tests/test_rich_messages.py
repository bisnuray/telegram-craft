"""Rich messages are the default screen type, so the linter and the gate treat them as first-class screens."""
import json
import subprocess
import sys

from test_quality_gate import SKILL, core as lint

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
