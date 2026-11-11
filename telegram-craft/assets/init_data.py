"""Validate Telegram Mini App init data on the server (standard library only).

Copy into the backend. Pass the raw `Telegram.WebApp.initData` string, never
`initDataUnsafe`. Spec: https://core.telegram.org/bots/webapps
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    """Raised when init data is malformed, forged, or too old."""


@dataclass(frozen=True)
class InitData:
    auth_date: int
    user: dict[str, Any] | None
    fields: dict[str, str]

    @property
    def user_id(self) -> int | None:
        return None if self.user is None else int(self.user["id"])


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 3600,
    now: float | None = None,
    future_skew_seconds: int = 60,
) -> InitData:
    """Return parsed fields, or raise InitDataError.

    The HMAC data-check-string covers every received field except `hash`, so a
    `signature` field stays in it. Dropping `signature` rejects valid launches.

    Pick `max_age_seconds` per endpoint: short for money and account changes.
    Exchange valid init data for your own session rather than extending this.
    """
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("init data is not a valid query string") from exc

    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise InitDataError("init data contains duplicate keys")

    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("init data has no hash")

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("init data signature mismatch")

    # Freshness only means something once the signature is known to be good.
    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError) as exc:
        raise InitDataError("init data has no usable auth_date") from exc

    current = time.time() if now is None else now
    if auth_date > current + future_skew_seconds:
        raise InitDataError("init data is from the future")
    if current - auth_date > max_age_seconds:
        raise InitDataError("init data has expired")

    user = None
    if "user" in fields:
        try:
            user = json.loads(fields["user"])
        except json.JSONDecodeError as exc:
            raise InitDataError("init data user is not valid JSON") from exc
        if not isinstance(user, dict) or "id" not in user:
            raise InitDataError("init data user has no id")

    return InitData(auth_date=auth_date, user=user, fields=fields)
