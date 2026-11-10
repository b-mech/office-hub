#!/usr/bin/env python3
"""Generate candidate files only; never install/reload/restart any unit."""
import argparse
from pathlib import Path

OVERRIDE_NAME = "zz-lease-maint.conf"


def contents(name, release, env_dir):
    if name == "frontend":
        return f"[Service]\nWorkingDirectory={release}/frontend\nEnvironmentFile=\nEnvironmentFile={env_dir}/frontend.env\nEnvironment=BACKEND_INTERNAL_URL=http://127.0.0.1:8001\nExecStart=\nExecStart=/usr/bin/npm start -- --hostname 127.0.0.1 --port 3001\n"
    env = "backend" if name == "backend" else "worker"
    commands = {
        "backend": f"{release}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001",
        "worker": f"{release}/.venv/bin/celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --concurrency=2",
        "beat": f"{release}/.venv/bin/celery -A app.workers.celery_app:celery_app beat --loglevel=INFO --pidfile=%t/officehub-staging-beat/celerybeat.pid --schedule=%S/officehub-staging/celerybeat-schedule",
    }
    return f"[Service]\nWorkingDirectory={release}/backend\nEnvironmentFile=\nEnvironmentFile={env_dir}/{env}.env\nExecStart=\nExecStart={commands[name]}\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--env-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    a.out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ("backend", "frontend", "worker", "beat"):
        with (a.out_dir / (name + ".conf")).open("x") as f:
            f.write(contents(name, a.release.resolve(), a.env_dir.resolve()))
    print("Generated four candidate staging overrides; none installed")


if __name__ == "__main__":
    main()
