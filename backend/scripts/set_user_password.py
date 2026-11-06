"""Set (or clear) an Office Hub sign-in password for an existing user.

Run on the server against the intended database; the password is read from an
interactive prompt (never argv, env, or files) and only its bcrypt hash is
stored. Setting or clearing a password bumps ``session_version`` so every
existing session of that user is signed out.

    cd backend && .venv/bin/python -m scripts.set_user_password --email someone@example.com
    cd backend && .venv/bin/python -m scripts.set_user_password --user-id <uuid> --clear
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import stat
import sys
from pathlib import Path
from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.passwords import PasswordPolicyError
from app.core.passwords import hash_password
from app.core.passwords import validate_new_password
from app.models.core import User


def _prompt() -> str:
    if not sys.stdin.isatty():
        raise SystemExit("Refusing to read a password from a non-interactive stdin")
    first = getpass.getpass("New Office Hub password: ")
    try:
        validate_new_password(first)
    except PasswordPolicyError as exc:
        raise SystemExit(str(exc)) from None
    if getpass.getpass("Repeat password: ") != first:
        raise SystemExit("Passwords did not match")
    return first


def _read_password_file(path: str) -> str:
    """Read a password from a private (0600/0400) file owned by the caller; for scripted trials."""
    target = Path(path)
    info = target.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise SystemExit("Password file must be owned by you and not readable by group/others (chmod 600)")
    value = target.read_text().rstrip("\n")
    try:
        validate_new_password(value)
    except PasswordPolicyError as exc:
        raise SystemExit(str(exc)) from None
    return value


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--email")
    who.add_argument("--user-id", type=UUID)
    parser.add_argument("--password-file", help="read the new password from a chmod-600 file instead of a prompt")
    parser.add_argument("--clear", action="store_true", help="remove the password (disables password sign-in)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        if args.user_id:
            user = await db.get(User, args.user_id)
        else:
            user = await db.scalar(select(User).where(func.lower(User.email) == args.email.strip().casefold()))
        if user is None:
            raise SystemExit("No such user")
        if not user.is_active and not args.clear:
            raise SystemExit("User is inactive; reactivate them first")
        user.password_hash = None if args.clear else hash_password(
            _read_password_file(args.password_file) if args.password_file else _prompt()
        )
        user.password_changed_at = datetime.now(timezone.utc)
        user.session_version = (user.session_version or 0) + 1
        await db.commit()
        print(f"{'Cleared' if args.clear else 'Set'} password for user {user.id}; existing sessions revoked.")


if __name__ == "__main__":
    asyncio.run(main())
