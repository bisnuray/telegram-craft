"""MTProto credential protection: ignore rules, exposure checks, and redaction. Nothing is deleted or revoked."""
import importlib.util
import io
import json
import logging
import random
import shutil
import string
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "telegram-craft"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "assets/quality-gate/python"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


secure = load("secure_mtproto_project", SKILL / "scripts/secure_mtproto_project.py")
audit = load("tg_audit_for_session_tests", SKILL / "scripts/tg_audit.py")
runtime = load("mtproto_runtime_for_session_tests", SKILL / "assets/mtproto_runtime.py")

RNG = random.Random(7)
SESSION = "1" + "".join(RNG.choice(string.ascii_letters + string.digits + "-_") for _ in range(352)) + "="
HASH = "".join(RNG.choice("0123456789abcdef") for _ in range(32))
CLIENT = "from telethon import TelegramClient\nfrom telethon.sessions import StringSession\nimport os\n\nclient = TelegramClient(StringSession(os.environ['TG_SESSION']), int(os.environ['TG_API_ID']), os.environ['TG_API_HASH'])\n"
GIT = shutil.which("git")
needs_git = pytest.mark.skipif(not GIT, reason="git not installed")


def project(tmp_path, gitignore=None, init_git=False):
    (tmp_path / "client.py").write_text(CLIENT)
    (tmp_path / "anon.session").write_bytes(b"SQLite format 3\0")
    (tmp_path / "anon.session-journal").write_bytes(b"")
    (tmp_path / ".env").write_text("TG_API_HASH=x\n")
    (tmp_path / ".env.example").write_text("TG_API_HASH=\n")
    if gitignore is not None:
        (tmp_path / ".gitignore").write_text(gitignore)
    if init_git:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args], capture_output=True, text=True)


def ignored(root, name):
    return git(root, "check-ignore", "-q", name).returncode == 0


@needs_git
class TestIgnoreRules:
    def test_new_project_gets_rules_that_git_honors(self, tmp_path):
        root = project(tmp_path, init_git=True)
        assert secure.main([str(root)]) == 0
        for name in ("anon.session", "anon.session-journal", "anon.session-wal", "anon.session-shm", "x.session.enc", ".env", ".env.production", "tdata/key_datas"):
            assert ignored(root, name), name
        assert not ignored(root, ".env.example") and not ignored(root, "client.py")

    def test_existing_rules_are_kept_and_not_duplicated(self, tmp_path):
        original = "# mine\nnode_modules/\n*.session*\n.env\n"
        root = project(tmp_path, gitignore=original, init_git=True)
        secure.main([str(root)])
        text = (root / ".gitignore").read_text()
        assert text.startswith(original)
        assert "\n*.session\n" not in text and text.count("\n.env\n") == 1  # already covered by the user's rules
        secure.main([str(root)])
        assert (root / ".gitignore").read_text() == text  # second run is a no-op

    def test_negation_only_comes_with_our_own_env_rule(self, tmp_path):
        root = project(tmp_path, gitignore=".env*\n", init_git=True)
        secure.main([str(root)])
        assert "!.env.example" not in (root / ".gitignore").read_text()
        assert ignored(root, ".env.example")  # the user's choice is unchanged

    def test_check_mode_changes_nothing_and_fails(self, tmp_path):
        root = project(tmp_path, gitignore="build/\n")
        assert secure.main([str(root), "--check"]) == 1
        assert (root / ".gitignore").read_text() == "build/\n"
        assert secure.main([str(root)]) == 0 and secure.main([str(root), "--check"]) == 0

    def test_tracked_session_is_reported_never_removed(self, tmp_path, capsys):
        root = project(tmp_path, init_git=True)
        git(root, "add", "anon.session", "client.py")
        git(root, "commit", "-q", "-m", "oops")
        assert secure.main([str(root)]) == 1
        out = capsys.readouterr().out
        assert "anon.session [session-file-tracked]" in out and "git rm --cached anon.session" in out
        assert (root / "anon.session").exists()
        assert "anon.session" in git(root, "ls-files").stdout  # still tracked: the owner decides


class TestExposureChecks:
    def leads(self, root):
        return {(lead.rule, lead.path) for lead in audit.audit(root)}

    def test_session_string_and_logging_and_api_hash(self, tmp_path):
        (tmp_path / "bad.py").write_text(f'SESSION = "{SESSION}"\napi_hash = "{HASH}"\nprint(client.session.save())\nlogger.info("s=%s", StringSession.save(client.session))\n')
        found = self.leads(tmp_path)
        assert {("session-string-literal", "bad.py"), ("api-hash-in-source", "bad.py"), ("session-logged", "bad.py")} <= found

    def test_unignored_session_file_and_missing_rule(self, tmp_path):
        root = project(tmp_path, gitignore="build/\n")
        found = self.leads(root)
        assert ("session-file-not-ignored", "anon.session") in found and ("session-not-ignored", ".gitignore") in found
        secure.main([str(root)])
        assert not {r for r, _ in self.leads(root)} & {"session-file-not-ignored", "session-not-ignored"}

    def test_safe_project_is_clean(self, tmp_path):
        (tmp_path / "client.py").write_text(CLIENT)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests/test_client.py").write_text('api_hash = "0123456789abcdef0123456789abcdef"\n')
        (tmp_path / ".gitignore").write_text("*.session\n")
        assert not [lead for lead in audit.audit(tmp_path) if lead.rule.startswith(("session", "api-hash"))]

    def test_directory_rule_covers_session_files(self, tmp_path):
        (tmp_path / "sessions").mkdir()
        (tmp_path / "sessions/main.session").write_bytes(b"")
        (tmp_path / ".gitignore").write_text("sessions/\n")
        assert ("session-file-not-ignored", "sessions/main.session") not in self.leads(tmp_path)

    def test_json_output(self, tmp_path, capsys):
        root = project(tmp_path)
        assert secure.main([str(root), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert "*.session" in data["added_rules"] and data["problems"] == []


class TestRedaction:
    def test_redact_removes_credentials(self):
        text = runtime.redact(f"s={SESSION} token=123456789:{'A' * 35} api_hash='{HASH}' phone +15551234567 code=12345")
        assert SESSION not in text and HASH not in text and "+15551234567" not in text and "12345" not in text.replace("123456789", "")
        assert "<session string>" in text and "<bot token>" in text and "<api_hash>" in text and "<phone>" in text

    def test_logging_filter_redacts_messages_args_and_tracebacks(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(runtime.RedactingFilter())
        log = logging.getLogger("redaction-test")
        log.addHandler(handler)
        log.propagate = False
        log.warning("saved %s", SESSION)
        try:
            raise RuntimeError(f"bad session {SESSION}")
        except RuntimeError:
            log.exception("failed")
        log.removeHandler(handler)
        assert SESSION not in stream.getvalue() and stream.getvalue().count("<session string>") == 2

    def test_gate_capture_never_contains_a_session_string(self, tmp_path):
        from tg_quality import Recorder

        recorder = Recorder("aiogram")
        recorder.begin("text", SESSION, "private")
        saved = recorder.save(tmp_path).read_text()
        assert SESSION not in saved and "<session string>" in saved


@needs_git
class TestCredentialsWorkflow:
    def step(self, root):
        yaml = pytest.importorskip("yaml")
        data = yaml.safe_load((root / ".github/workflows/telegram-credentials.yml").read_text())
        return data["jobs"]["telegram-credentials"]["steps"][-1]["run"]

    def run_step(self, root):
        return subprocess.run(["bash", "-c", self.step(root)], cwd=root, capture_output=True, text=True).returncode

    def test_writes_once_and_keeps_existing(self, tmp_path):
        root = project(tmp_path, init_git=True)
        assert secure.main([str(root), "--ci"]) == 0
        workflow = root / ".github/workflows/telegram-credentials.yml"
        workflow.write_text("mine\n")
        secure.main([str(root), "--ci"])
        assert workflow.read_text() == "mine\n"

    def test_ci_step_passes_clean_and_fails_on_tracked_session_or_string(self, tmp_path):
        root = project(tmp_path, init_git=True)
        secure.main([str(root), "--ci"])
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "clean")
        assert self.run_step(root) == 0  # session files exist on disk but are ignored
        git(root, "add", "-f", "anon.session")
        assert self.run_step(root) == 1
        git(root, "rm", "-q", "--cached", "anon.session")
        (root / "config.py").write_text(f'S = "{SESSION}"\n')
        git(root, "add", "config.py")
        assert self.run_step(root) == 1
