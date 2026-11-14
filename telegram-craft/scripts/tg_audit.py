#!/usr/bin/env python3
"""Scan a Telegram project for likely defects (Python 3.9+, standard library).

  tg_audit.py PROJECT_DIR [--json]

The output is LEADS, not findings. Open each location and confirm it before
reporting or changing it: a static scan cannot see middleware, helpers in other
files, or deployment settings. A clean run proves nothing about correctness.

The scan reads files only and never imports or runs project code.
Exit codes: 0 no high-severity leads, 1 high-severity leads, 2 bad input.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build",
    ".next", ".nuxt", "coverage", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages",
}
SCRIPT_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte"}
TEXT_SUFFIXES = SCRIPT_SUFFIXES | {".py", ".env", ".json", ".yml", ".yaml", ".toml", ".ini", ".html", ".md", ".txt", ".sh"}
MAX_BYTES = 1_500_000

TOKEN_RE = re.compile(r"\b(\d{8,12}):([A-Za-z0-9_-]{35})\b")
PLACEHOLDER_RE = re.compile(r"(?i)^(a{5,}|x{5,}|abc|test|example|your|dummy|fake|0{5,})")
BLOCKING = {
    "time.sleep": "use asyncio.sleep",
    "requests.get": "use an async HTTP client", "requests.post": "use an async HTTP client",
    "requests.put": "use an async HTTP client", "requests.delete": "use an async HTTP client",
    "requests.request": "use an async HTTP client", "urllib.request.urlopen": "use an async HTTP client",
    "subprocess.run": "use asyncio.create_subprocess_exec", "subprocess.call": "use asyncio.create_subprocess_exec",
    "subprocess.check_output": "use asyncio.create_subprocess_exec", "subprocess.check_call": "use asyncio.create_subprocess_exec",
    "os.system": "use asyncio.create_subprocess_exec",
}
SEND_METHODS = {
    "answer", "reply", "reply_text", "send_message", "edit_text", "edit_message_text",
    "reply_html", "edit_caption", "send_photo", "send_document", "send_audio", "send_video", "answer_photo",
}
ESCAPERS = re.compile(r"escape|quote|sanitize|html_decoration|markdown_decoration|\.html_text|\.md_text|mention_html")
TAG_IN_TEXT = re.compile(r"</?(b|i|u|s|a|code|pre|blockquote|strong|em)\b")
SECRET_NAME = re.compile(r"(?i)token|secret|api[_-]?key|password")
TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|conftest\.py$)")

# MTProto credentials. A Telethon StringSession is "1" plus about 350 base64 characters and grants full account access.
SESSION_STRING_RE = re.compile(r"(?<![A-Za-z0-9_+/-])1[A-Za-z0-9_+/-]{300,}={0,2}")
SESSION_LOG_RE = re.compile(r"\b(?:print|\w*log\w*\.(?:debug|info|warning|warn|error|exception|critical|log))\([^\n]*"
                            r"(?:session\.save\(\)|StringSession\.save\(|session_string|string_session)")
API_HASH_RE = re.compile(r"api_hash[\"']?\s*[=:]\s*[\"']([0-9a-f]{32})[\"']")
MTPROTO_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(?:telethon|pyrogram)\b", re.M)
SESSION_FILE_SUFFIXES = (".session", ".session-journal", ".session-wal", ".session-shm", ".session.enc")
SESSION_IGNORE_RULES = ["*.session", "*.session-journal", "*.session-wal", "*.session-shm", "*.session.enc",
                        ".env", ".env.*", "!.env.example", "tdata/"]


def ignore_rules(root: Path) -> set[str]:
    file = root / ".gitignore"
    if not file.exists():
        return set()
    return {line.strip() for line in file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.startswith("#")}


def session_ignored(rel: str, rules: set[str]) -> bool:
    """Approximate .gitignore matching: file name, any parent directory, or the whole path.

    Enough to flag a missing rule. It ignores negations and nested .gitignore files, so
    secure_mtproto_project.py asks git itself when a repository exists.
    """
    from fnmatch import fnmatch
    parts = rel.split("/")
    for rule in rules:
        if rule.startswith("!"):
            continue
        pattern = rule.strip("/")
        if fnmatch(parts[-1], pattern) or fnmatch(rel, pattern) or any(fnmatch(part, pattern) for part in parts[:-1]):
            return True
    return False


def session_files(root: Path, limit: int = 200) -> list[str]:
    found = []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
        found += [(Path(directory) / name).relative_to(root).as_posix() for name in files if name.endswith(SESSION_FILE_SUFFIXES)]
        if len(found) >= limit:
            break
    return sorted(found)


def credential_leads(root: Path, sources: dict[str, str]) -> list[Lead]:
    """Session strings, logged sessions, api_hash literals, and session files git would pick up."""
    leads: list[Lead] = []
    for rel, text in sources.items():
        if rel == ".gitignore":
            continue
        for match in SESSION_STRING_RE.finditer(text):
            leads.append(Lead("high", "session-string-literal", rel, text[: match.start()].count("\n") + 1,
                              "looks like a Telethon session string; it grants full account access. Remove it, then have the owner end that session"))
        if rel.endswith(".py"):
            for match in SESSION_LOG_RE.finditer(text):
                leads.append(Lead("high", "session-logged", rel, text[: match.start()].count("\n") + 1, "a session string is printed or logged"))
            if not TEST_PATH.search(rel):
                for match in API_HASH_RE.finditer(text):
                    if len(set(match.group(1))) > 4:
                        leads.append(Lead("high", "api-hash-in-source", rel, text[: match.start()].count("\n") + 1, "api_hash is hard-coded; load it from the environment or a secret manager"))
        if rel.rsplit("/", 1)[-1].startswith("Dockerfile"):
            for match in IMAGE_SECRET_RE.finditer(text):
                leads.append(Lead("high", "secret-in-image", rel, text[: match.start()].count("\n") + 1,
                                  f"{match.group(2)} in {match.group(1)} is baked into the image layers; pass it at runtime as a secret"))
    rules = ignore_rules(root)
    for rel in session_files(root):
        if not session_ignored(rel, rules):
            leads.append(Lead("high", "session-file-not-ignored", rel, 1, "session file is not covered by .gitignore and could be committed"))
    uses_mtproto = any(rel.endswith(".py") and MTPROTO_IMPORT_RE.search(text) for rel, text in sources.items())
    if uses_mtproto and not session_ignored("x.session", rules):
        leads.append(Lead("medium", "session-not-ignored", ".gitignore", 1, "MTProto project without a *.session rule; run scripts/secure_mtproto_project.py"))
    return leads


IMAGE_SECRET_RE = re.compile(r"(?im)^\s*(ENV|ARG)\s+([A-Z0-9_]*(?:SESSION|API_HASH|TOKEN|SECRET)[A-Z0-9_]*)\b")


@dataclass
class Lead:
    severity: str
    rule: str
    path: str
    line: int
    message: str


def dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def call_has(call: ast.Call, name: str) -> bool:
    return any(keyword.arg == name for keyword in call.keywords)


def own_nodes(function: ast.AST):
    """Walk a function body without entering nested defs."""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


def awaits_cancelled_task(function, handler_try):
    """try: await task / except CancelledError, right after task.cancel(): the standard stop() idiom."""
    body = handler_try.body
    if len(body) != 1 or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Await):
        return False
    target = ast.unparse(body[0].value.value)
    return any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "cancel" and ast.unparse(n.func.value) == target
               for n in ast.walk(function))


class PythonScan:
    def __init__(self, rel: str, source: str, tree: ast.Module, project_text: str) -> None:
        self.rel = rel
        self.source = source
        self.tree = tree
        self.project_text = project_text
        self.leads: list[Lead] = []

    def add(self, severity: str, rule: str, line: int, message: str) -> None:
        self.leads.append(Lead(severity, rule, self.rel, line, message))

    def run(self) -> list[Lead]:
        self.stop_idioms = {id(h) for f in ast.walk(self.tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                            for tr in ast.walk(f) if isinstance(tr, ast.Try) and awaits_cancelled_task(f, tr) for h in tr.handlers}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.AsyncFunctionDef):
                self.check_async(node)
                self.check_handler(node)
            elif isinstance(node, ast.Call):
                self.check_call(node)
            elif isinstance(node, ast.ExceptHandler):
                self.check_except(node)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.check_import(node)
            elif isinstance(node, ast.Compare):
                self.check_compare(node)
        self.check_module()
        return self.leads

    def check_async(self, function: ast.AsyncFunctionDef) -> None:
        for node in own_nodes(function):
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                if name in BLOCKING:
                    self.add("high", "blocking-call", node.lineno, f"{name}() inside async {function.name} stalls every chat; {BLOCKING[name]}")

    def is_callback_handler(self, function: ast.AsyncFunctionDef) -> bool:
        for arg in function.args.args:
            if arg.annotation is not None and dotted(arg.annotation).endswith("CallbackQuery"):
                return True
        return any("callback_query" in dotted(getattr(d, "func", d)) for d in function.decorator_list)

    def check_handler(self, function: ast.AsyncFunctionDef) -> None:
        names = [dotted(n.func) for n in own_nodes(function) if isinstance(n, ast.Call)]
        if self.is_callback_handler(function) and "CallbackAnswerMiddleware" not in self.project_text:
            answered = any(n.endswith(("callback.answer", "query.answer", "call.answer", "cb.answer", "callback_query.answer", "answer_callback_query")) or n.endswith(".answer") and "message" not in n for n in names)
            if not answered:
                params = {a.arg for a in function.args.args}
                delegated = any(
                    isinstance(n, ast.Call) and any(isinstance(x, ast.Name) and x.id in params for x in n.args)
                    for n in own_nodes(function)
                )
                if delegated:
                    self.add("low", "callback-delegated", function.lineno, f"{function.name} passes its callback to a helper; confirm every helper path answers it")
                else:
                    self.add("high", "callback-unanswered", function.lineno, f"{function.name} handles a callback but never answers it; the client spinner keeps running")
        body = "\n".join(ast.get_source_segment(self.source, n) or "" for n in function.body)
        if "successful_payment" in body or any("successful_payment" in (ast.get_source_segment(self.source, d) or "") for d in function.decorator_list):
            if "telegram_payment_charge_id" not in self.project_text:
                self.add("high", "payment-no-charge-id", function.lineno, f"{function.name} handles successful_payment without telegram_payment_charge_id: no dedupe key, no refund path")

    def is_setup_script(self) -> bool:
        return bool(SETUP_SCRIPT.search(self.rel))

    def check_mtproto_call(self, call: ast.Call, name: str, leaf: str) -> None:
        if "TelegramClient" not in self.source and "telethon" not in self.source:
            return
        if leaf == "StringSession" and call.args and self.may_be_empty(call.args[0]):
            self.add("high", "empty-string-session", call.lineno, "StringSession from a value that may be empty; an unset variable becomes a new login. Fail when it is missing")
        if self.is_setup_script():
            return
        if leaf == "start" and "client" in name.lower() and not call_has(call, "bot_token"):
            self.add("high", "user-client-start", call.lineno, f"{name}() prompts for a phone number when the session is not authorized; use connect() and is_user_authorized()")
        if leaf == "log_out":
            self.add("high", "log-out", call.lineno, "log_out() revokes the session; shutdown should only disconnect()")

    @staticmethod
    def may_be_empty(node: ast.AST) -> bool:
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return any(isinstance(v, ast.Constant) and not v.value for v in node.values)
        if isinstance(node, ast.Call) and dotted(node.func) in ("os.environ.get", "os.getenv", "environ.get", "getenv"):
            default = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "default"), None)
            return default is None or isinstance(default, ast.Constant) and not default.value
        return False

    def check_call(self, call: ast.Call) -> None:
        name = dotted(call.func)
        leaf = name.rsplit(".", 1)[-1]
        self.check_mtproto_call(call, name, leaf)
        if call_has(call, "shell") and any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords):
            self.add("high", "shell-true", call.lineno, f"{name}(shell=True) risks command injection from user file names or URLs")
        if leaf == "create_subprocess_shell" or name == "os.system":
            self.add("high", "shell-exec", call.lineno, f"{name} goes through a shell; pass an argv list instead")
        if leaf in ("execute", "executemany", "fetch", "fetchrow", "fetchval") and call.args and self.is_dynamic_string(call.args[0]):
            self.add("high", "sql-string", call.lineno, f"{name}() builds SQL from a string expression; bind parameters")
        if leaf == "set_webhook" and not call_has(call, "secret_token"):
            self.add("high", "webhook-no-secret", call.lineno, "set_webhook without secret_token; anyone who finds the URL can forge updates")
        if leaf == "SimpleRequestHandler" and not call_has(call, "secret_token"):
            self.add("high", "webhook-no-secret", call.lineno, "SimpleRequestHandler without secret_token does not verify the webhook header")
        if leaf == "run_webhook" and not call_has(call, "secret_token"):
            self.add("high", "webhook-no-secret", call.lineno, "run_webhook without secret_token")
        if leaf == "parse_webapp_init_data":
            self.add("high", "init-data-unverified", call.lineno, "parse_webapp_init_data performs no security check; validate the signature")
        if any(k.arg == "drop_pending_updates" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords):
            self.add("medium", "drops-updates", call.lineno, "drop_pending_updates discards queued updates, including paid ones, on each start")
        if leaf == "MemoryStorage":
            self.add("low", "memory-fsm", call.lineno, "MemoryStorage loses conversations on restart; fine for development")
        if leaf == "mkdtemp" or (leaf == "NamedTemporaryFile" and any(k.arg == "delete" and isinstance(k.value, ast.Constant) and k.value.value is False for k in call.keywords)):
            if "rmtree" not in self.source and ".unlink" not in self.source and "os.remove" not in self.source:
                self.add("medium", "temp-leak", call.lineno, "temporary path is created but this file never removes one")
        if leaf in SEND_METHODS and call.args:
            self.check_text_arg(call, call.args[0])
        for keyword in call.keywords:
            if leaf in SEND_METHODS and keyword.arg in ("text", "caption"):
                self.check_text_arg(call, keyword.value)
        if leaf in ("print", "info", "debug", "warning", "error", "exception", "critical") and leaf != "error" or leaf == "error" and name.startswith(("log", "logger")):
            for arg in call.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, (ast.Name, ast.Attribute)) and re.search(r"(?i)bot_?token|^token$|\.token$", dotted(sub)):
                        self.add("high", "secret-logged", call.lineno, f"{name}() may log the bot token")
                        break

    @staticmethod
    def is_dynamic_string(node: ast.AST) -> bool:
        if isinstance(node, ast.JoinedStr):
            def constant_like(value: ast.FormattedValue) -> bool:
                expr = value.value
                if isinstance(expr, ast.Name):
                    return expr.id.isupper() or "placeholder" in expr.id.lower()
                return isinstance(expr, ast.Call) and dotted(expr.func).endswith(".join") and any(
                    isinstance(sub, ast.Constant) and sub.value == "?" for sub in ast.walk(expr)
                )
            return any(isinstance(v, ast.FormattedValue) and not constant_like(v) for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
            return True
        return isinstance(node, ast.Call) and dotted(node.func).endswith(".format")

    def check_text_arg(self, call: ast.Call, node: ast.AST) -> None:
        if not isinstance(node, ast.JoinedStr):
            return
        literal = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
        html_mode = TAG_IN_TEXT.search(literal) or any(k.arg == "parse_mode" for k in call.keywords)
        if not html_mode:
            return
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                expr = ast.get_source_segment(self.source, value.value) or ""
                if not ESCAPERS.search(expr) and self.looks_untrusted(expr):
                    self.add("high", "unescaped-text", call.lineno, f"{expr} goes into markup unescaped; a < in it breaks the send or injects tags")

    @staticmethod
    def looks_untrusted(expr: str) -> bool:
        return bool(re.search(r"(?i)name|title|text|caption|query|username|file|user|data|comment|message|filename|desc", expr)) and not re.search(r"(?i)\bid\b|_id\b|count|len\(", expr)

    def check_except(self, handler: ast.ExceptHandler) -> None:
        type_name = dotted(handler.type) if handler.type is not None else ""
        if type_name.endswith(("TelegramRetryAfter", "RetryAfter")):
            body = "\n".join(ast.get_source_segment(self.source, n) or "" for n in handler.body)
            if "retry_after" not in body:
                self.add("medium", "retry-after-ignored", handler.lineno, "429 handler does not wait for the server-provided retry_after")
        if type_name in ("", "Exception", "BaseException") and len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
            self.add("medium", "swallowed-exception", handler.lineno, "exception swallowed silently; the user gets no reply and logs show nothing")
        caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        catches_cancel = handler.type is None or any(dotted(c) == "BaseException" or dotted(c).endswith("CancelledError") for c in caught)
        if catches_cancel and not any(isinstance(n, ast.Raise) for n in ast.walk(handler)) and id(handler) not in self.stop_idioms:
            self.add("high", "swallowed-cancellation", handler.lineno, "catches CancelledError without re-raising; shutdown hangs and tasks never stop")

    def check_import(self, node: ast.AST) -> None:
        module = getattr(node, "module", "") or ""
        names = [a.name for a in node.names]
        if module.startswith("aiogram.contrib") or (module == "aiogram" and "executor" in names):
            self.add("high", "aiogram2-api", node.lineno, "aiogram 2.x API; 3.x removed it")
        if module.startswith("telegram.ext") and "Filters" in names:
            self.add("high", "ptb13-api", node.lineno, "python-telegram-bot <20 API (Filters); v20+ is async and uses filters")
        if module.startswith("pyrogram") or "pyrogram" in names:
            self.add("low", "pyrogram-archived", node.lineno, "upstream Pyrogram is archived; check whether a maintained fork or Telethon fits")

    def check_compare(self, node: ast.Compare) -> None:
        text = ast.get_source_segment(self.source, node) or ""
        if re.search(r"\.username\b", text) and re.search(r"(?i)admin|owner|staff|moder", text):
            self.add("high", "username-auth", node.lineno, "authorization by username; usernames change and can be reassigned, so compare numeric IDs")

    def check_module(self) -> None:
        if re.search(r"safe_parse_webapp_init_data|check_webapp_signature", self.source) and "auth_date" not in self.source:
            match = re.search(r"safe_parse_webapp_init_data|check_webapp_signature", self.source)
            self.add("high", "init-data-no-expiry", self.source[: match.start()].count("\n") + 1, "signature is checked but auth_date is not; a leaked payload works forever")


JS_RULES: list[tuple[str, str, re.Pattern[str], str]] = [
    ("high", "frontend-secret", re.compile(r"\b(VITE|NEXT_PUBLIC|REACT_APP|NUXT_PUBLIC)_[A-Z0-9_]*(BOT_TOKEN|TOKEN|SECRET)\b"), "build-time public variable holds a secret and ships to every browser"),
    ("high", "innerhtml-template", re.compile(r"\.innerHTML\s*\+?=\s*(`[^`]*\$\{|[^;\n]*\+\s*\w)"), "dynamic innerHTML can inject script; use textContent or escape"),
    ("medium", "token-in-storage", re.compile(r"localStorage\.setItem\(\s*[\"'`][^\"'`]*(token|secret|session)", re.I), "long-lived credential in localStorage; prefer SecureStorage or short sessions"),
    ("medium", "shell-exec", re.compile(r"\bexec(?:Sync)?\(\s*`[^`]*\$\{"), "shell command built from a template; use execFile with an argv list"),
]
UNSAFE_SEND = re.compile(r"initDataUnsafe[^;\n]*(fetch|axios|body|headers|JSON\.stringify)|(fetch|axios|body|headers|JSON\.stringify)[^;\n]*initDataUnsafe")
SETUP_SCRIPT = re.compile(r"(?i)(^|/)(tools/|scripts/)|login|create_session|session_gen|make_session|provision")
UNSAFE_ID = re.compile(r"initDataUnsafe\??\.user\??\.id")
BOT_API_CALL = re.compile(r"api\.telegram\.org/bot")
CLIENT_PATH = re.compile(r"(^|/)(webapp|web-app|frontend|client|public|miniapp|mini-app|src/(components|pages|app))(/|$)", re.I)


def scan_script(rel: str, text: str) -> list[Lead]:
    leads = []
    for severity, rule, pattern, message in JS_RULES:
        for match in pattern.finditer(text):
            leads.append(Lead(severity, rule, rel, text[: match.start()].count("\n") + 1, message))
    for pattern, rule, message in (
        (UNSAFE_SEND, "init-data-unsafe-sent", "initDataUnsafe reaches the backend; send raw initData and validate it there"),
        (UNSAFE_ID, "init-data-unsafe-id", "user id taken from initDataUnsafe; never authorize with it"),
    ):
        for match in pattern.finditer(text):
            leads.append(Lead("high", rule, rel, text[: match.start()].count("\n") + 1, message))
    if BOT_API_CALL.search(text) and CLIENT_PATH.search(rel):
        leads.append(Lead("high", "client-bot-api", rel, text[: BOT_API_CALL.search(text).start()].count("\n") + 1, "Bot API called from client code exposes the token"))
    return leads


def scan_project_signals(root: Path, sources: dict[str, str], leads: list[Lead]) -> None:
    scripts = {rel: t for rel, t in sources.items() if Path(rel).suffix in SCRIPT_SUFFIXES or rel.endswith(".html")}
    mini_app_files = [rel for rel, t in scripts.items() if "telegram-web-app.js" in t or "Telegram.WebApp" in t or "@tma.js" in t or "@telegram-apps/" in t]
    if mini_app_files:
        joined = "\n".join(t for rel, t in sources.items() if Path(rel).suffix in SCRIPT_SUFFIXES | {".css", ".scss", ".html"})
        anchor = sorted(mini_app_files)[0]
        checks = (
            (r"--tg-theme-|themeParams|bindThemeParams", "no-theme", "no Telegram theme usage found; the app will not follow light and dark"),
            (r"--tg-(content-)?safe-area|safeAreaInset|contentSafeAreaInset|bindViewport", "no-safe-area", "no safe-area handling found; content can sit under Telegram controls in fullscreen"),
            (r"\bready\(\)|\.ready\b|init\(\)", "no-ready", "ready() not found; the loading placeholder may stay too long"),
            (r"BackButton|backButton", "no-back-button", "no BackButton use; nested screens need native back"),
        )
        for pattern, rule, message in checks:
            if not re.search(pattern, joined):
                leads.append(Lead("medium", rule, anchor, 1, message))
    handlers = [rel for rel, t in scripts.items() if re.search(r"\.callbackQuery\(|\.action\(|[\"']callback_query", t)]
    all_scripts = "\n".join(scripts.values())
    if handlers and not re.search(r"answerCallbackQuery|answerCbQuery", all_scripts):
        leads.append(Lead("high", "callback-unanswered", sorted(handlers)[0], 1, "callback handlers exist but nothing answers a callback query"))
    env_example = any(name in sources for name in (".env", ".env.local", ".env.production"))
    if env_example:
        gitignore = root / ".gitignore"
        if not gitignore.exists() or ".env" not in gitignore.read_text(encoding="utf-8", errors="replace"):
            leads.append(Lead("high", "env-not-ignored", ".gitignore", 1, ".env exists but is not git-ignored"))


def collect(root: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(directory) / name
            if path.suffix not in TEXT_SUFFIXES | {".css", ".scss"} and not name.startswith((".env", "Dockerfile")):
                continue
            try:
                if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                    continue
                sources[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return sources


def audit(root: Path) -> list[Lead]:
    sources = collect(root)
    project_python = "\n".join(t for rel, t in sources.items() if rel.endswith(".py"))
    leads: list[Lead] = []
    for rel, text in sources.items():
        for match in TOKEN_RE.finditer(text):
            if not PLACEHOLDER_RE.match(match.group(2)) and not rel.endswith(".example"):
                leads.append(Lead("high", "token-in-source", rel, text[: match.start()].count("\n") + 1, f"looks like a real bot token ({match.group(1)}:***); revoke it if it was committed"))
        if rel.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                leads.append(Lead("low", "syntax-error", rel, exc.lineno or 1, "file does not parse; not scanned"))
                continue
            if not TEST_PATH.search(rel):
                leads.extend(PythonScan(rel, text, tree, project_python).run())
        elif Path(rel).suffix in SCRIPT_SUFFIXES:
            leads.extend(scan_script(rel, text))
    scan_project_signals(root, sources, leads)
    leads.extend(credential_leads(root, sources))
    order = {"high": 0, "medium": 1, "low": 2}
    unique = {(lead.rule, lead.path, lead.line): lead for lead in leads}
    return sorted(unique.values(), key=lambda lead: (order[lead.severity], lead.path, lead.line))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.project)
    if not root.is_dir():
        print(f"bad input: {root} is not a directory", file=sys.stderr)
        return 2
    leads = audit(root)
    high = sum(lead.severity == "high" for lead in leads)
    if args.json:
        print(json.dumps({"high": high, "total": len(leads), "leads": [asdict(lead) for lead in leads]}, indent=2))
    else:
        for lead in leads:
            print(f"{lead.severity:6} {lead.path}:{lead.line} [{lead.rule}] {lead.message}")
        print(f"{len(leads)} lead(s), {high} high. Confirm each one by reading the code.")
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main())
