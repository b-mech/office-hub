#!/usr/bin/env python3
"""Prepare NEW protected staging envs, without editing any deployed file."""
import argparse
import os
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

PREFIXES = ("MAINT_", "MAINTENANCE_", "SMS_", "RINGCENTRAL_", "PRIVI_", "STAGING_SMS_", "TWILIO_", "TURNSTILE_", "SLACK_", "CELERY_")
EXACT = {"PUBLIC_BASE_URL", "PUBLIC_BRAND_NAME", "REDIS_URL"}


def combine(lease, worker):
    if lease.get("ENVIRONMENT") != "staging" or worker.get("ENVIRONMENT") != "staging":
        raise ValueError("Both inputs must be staging")
    if make_url(lease["DATABASE_URL"]).database != "officehub_lease_agreements_test":
        raise ValueError("Canonical DB guard failed")
    if not worker.get("STAGING_SMS_ALLOWLIST"):
        raise ValueError("Refuse missing staging SMS allowlist")
    backend = dict(lease)
    for key, value in worker.items():
        if key.startswith(PREFIXES) or key in EXACT:
            backend[key] = value
    worker = dict(worker, DATABASE_URL=lease["DATABASE_URL"])
    return backend, worker


def write_new(path, values):
    # Dotenv single-quoted escaping; fail rather than replace any existing file.
    body = "".join(k + "='" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'\n" for k, v in values.items() if v is not None)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(body)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lease-env", type=Path, required=True)
    p.add_argument("--worker-env", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    try:
        backend, worker = combine(dict(dotenv_values(a.lease_env)), dict(dotenv_values(a.worker_env)))
        a.out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        write_new(a.out_dir / "backend.env", backend)
        write_new(a.out_dir / "worker.env", worker)
        frontend = dict(dotenv_values(a.lease_env), BACKEND_INTERNAL_URL="http://127.0.0.1:8001")
        write_new(a.out_dir / "frontend.env", frontend)
        print("Prepared new mode-0600 staging env files; no deployed file changed; values hidden")
        return 0
    except Exception as exc:
        print("Preparation aborted: " + type(exc).__name__ + "; no values printed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
