"""Run backend tests with dummy settings and TCP networking disabled.

Use the existing interpreter, but never source a deployed .env or reuse its HOME.
Install requirements-test.txt in a separate test environment first.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="officehub-isolated-tests-") as home:
        env = {k: v for k, v in os.environ.items() if k in {
            "PATH", "LANG", "LC_ALL", "TZ", "PYTHONPATH", "VIRTUAL_ENV",
        }}
        env.update({
            "HOME": home,
            "PYTHONPATH": str(BACKEND) + os.pathsep + env.get("PYTHONPATH", ""),
            "ENVIRONMENT": "test",
            "DATABASE_URL": "postgresql+asyncpg://unit:unit@127.0.0.1:1/officehub_unit_tests",
            "REDIS_URL": "redis://127.0.0.1:1/15",
            "MINIO_URL": "http://127.0.0.1:1", "MINIO_ROOT_USER": "unit-test-only",
            "MINIO_ROOT_PASSWORD": "unit-test-only", "MINIO_BUCKET": "unit-tests",
            "IMAP_HOST": "unit.invalid", "IMAP_USER": "unit", "IMAP_PASSWORD": "unit-test-only",
            "IMAP_FOLDER": "INBOX", "ANTHROPIC_API_KEY": "unit-test-only",
            "OPENAI_API_KEY": "unit-test-only", "ACTIVE_MODEL_PROVIDER": "claude",
            "SECRET_KEY": "unit-test-only", "OFFICE_HUB_API_KEY": "unit-test-only",
            "DEFAULT_ORG_ID": "00000000-0000-0000-0000-000000000001",
            "PUBLIC_BASE_URL": "https://unit.invalid", "PUBLIC_SITE_URL": "https://unit.invalid",
            "CELERY_TASK_ALWAYS_EAGER": "true", "AUTH_ENFORCED": "false",
            "AWS_EC2_METADATA_DISABLED": "true", "BOX_TOKEN_FILE": home + "/absent-box-token.json",
            "GOOGLE_OAUTH_TOKEN_PATH": home + "/absent-google-token.json",
            "GOOGLE_OAUTH_CLIENT_SECRET_PATH": home + "/absent-google-client.json",
        })
        guard = (
            "import pytest_socket; pytest_socket.disable_socket(allow_unix_socket=True); "
            "import pytest, sys; raise SystemExit(pytest.main(sys.argv[1:]))"
        )
        args = sys.argv[1:] or ["tests", "-q"]
        return subprocess.run(
            [sys.executable, "-c", guard, "--disable-socket", "--allow-unix-socket", *args],
            cwd=BACKEND, env=env, check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
