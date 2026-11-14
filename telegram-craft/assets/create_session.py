"""Create a Telethon session string once, by hand, for an account you are authorized to use.

    TELEGRAM_API_ID=... TELEGRAM_API_HASH=... python create_session.py --out session.txt

Signs in interactively (phone, login code, and the 2FA password if set) and writes the
session string to a new file readable only by you. Move the value into the deployment's
secret store as TELEGRAM_SESSION_STRING, then delete the file. `--print` writes it to the
terminal instead; avoid that where the screen or scrollback is recorded.

The service itself never runs this: at startup it loads the string and fails if it is
missing or revoked. Run this again only when you choose to replace the session.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession


async def create_session() -> str:
    client = TelegramClient(StringSession(), int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"])
    await client.start()
    try:
        me = await client.get_me()
        print(f"Signed in as {me.first_name} (id {me.id}).", file=sys.stderr)
        return client.session.save()
    finally:
        # disconnect, not log_out: logging out would revoke the session just created.
        await client.disconnect()


def write_private(path: str, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(value + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", help="new file for the session string (created with mode 0600)")
    target.add_argument("--print", action="store_true", help="print the session string to stdout")
    args = parser.parse_args()
    session = asyncio.run(create_session())
    if args.print:
        print(session)
    else:
        write_private(args.out, session)
        print(f"Session written to {args.out}. Store it as TELEGRAM_SESSION_STRING, then delete the file.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
