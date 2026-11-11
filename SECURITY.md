# Security policy

## Reporting a vulnerability

Report security issues privately through GitHub's [private vulnerability reporting](https://github.com/bisnuray/telegram-craft/security/advisories/new). Do not open a public issue for a vulnerability.

Include the affected file, what an attacker can do, and the smallest example that shows it. You should get a reply within 7 days.

## Scope

In scope:
- the scripts and assets in `telegram-craft/`, for example an escaping bypass in `rich_html.py` or a check in `tg_lint.py` that passes unsafe content;
- `initData` validation and session handling;
- guidance in the skill that would lead an agent to write insecure code.

Out of scope:
- bugs in Telegram, its client apps, or third-party libraries; report those to their maintainers;
- code an agent wrote in your project. Review it the way you review any code.

## Never share credentials

Never include a bot token, `api_hash`, session file, or session string in a report, an issue, or a pull request. If one was exposed, revoke it first (BotFather `/revoke`, or Settings → Devices for a user session) and then report.
