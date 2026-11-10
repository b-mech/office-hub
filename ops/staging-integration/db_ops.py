#!/usr/bin/env python3
"""Credential-safe staging DB operator; constructing the plan does not execute it."""
import argparse
import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]


def validate(url, expected, write=False, allow_live=False):
    parsed = make_url(url)
    if parsed.database != expected:
        raise ValueError("Database-name guard failed")
    if expected not in {"officehub_staging", "officehub_lease_agreements_test"} and not (expected.startswith("officehub_") and "_trial_" in expected):
        raise ValueError("Only known staging databases and named trials are allowed")
    if write and "_trial_" not in expected and not allow_live:
        raise ValueError("Live staging write requires --allow-live-target")
    return parsed


async def revision(url):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num"))).scalars().all()
    finally:
        await engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["dump", "restore", "revision", "migrate"])
    p.add_argument("--env", type=Path, required=True)
    p.add_argument("--expect-db", required=True)
    p.add_argument("--file", type=Path)
    p.add_argument("--direction", choices=["upgrade", "downgrade"], default="upgrade")
    p.add_argument("--revision", default="head")
    p.add_argument("--allow-live-target", action="store_true")
    args = p.parse_args()
    try:
        values = {k: v for k, v in dotenv_values(args.env).items() if v is not None}
        url = values["DATABASE_URL"]
        u = validate(url, args.expect_db, args.action in {"restore", "migrate"}, args.allow_live_target)
        if args.action == "revision":
            print(args.expect_db, asyncio.run(revision(url)))
            return 0
        if args.action == "migrate":
            result = subprocess.run([sys.executable, "-m", "alembic", args.direction, args.revision], cwd=ROOT / "backend", env=dict(os.environ, **values), capture_output=True, text=True)
        else:
            if args.file is None:
                raise ValueError("--file is required")
            # Staging databases are in this local PostgreSQL container. Secrets
            # are inherited environment only, never arguments or displayed URLs.
            env = dict(os.environ, PGPASSWORD=u.password or "")
            cmd = ["docker", "exec"] + (["-i"] if args.action == "restore" else []) + ["-e", "PGPASSWORD", "office-hub-postgres-1"]
            if args.action == "dump":
                cmd += ["pg_dump", "-h", "127.0.0.1", "-U", u.username, "-d", u.database, "--format=custom", "--no-owner", "--no-privileges"]
                fd = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    result = subprocess.run(cmd, env=env, stdout=output, stderr=subprocess.PIPE)
            else:
                cmd += ["pg_restore", "-h", "127.0.0.1", "-U", u.username, "-d", u.database, "--clean", "--if-exists", "--no-owner", "--no-privileges", "--exit-on-error"]
                with args.file.open("rb") as source:
                    result = subprocess.run(cmd, env=env, stdin=source, capture_output=True)
        if args.action == "migrate":
            # Only migration progress is safe to print. Never dump raw driver or
            # settings tracebacks, which may embed URLs, passwords or tenant PII.
            for line in (result.stdout + result.stderr).splitlines():
                if re.match(r"INFO  \[alembic\.", line):
                    print(line)
        print(args.action, args.expect_db, "exit", result.returncode)
        return result.returncode
    except Exception as exc:
        print("Operation aborted; error class: " + type(exc).__name__ + ". No credential/error values printed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
