#!/usr/bin/env python3
"""Guarded staging frontend build; never change an env file or restart a service."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
KEY = "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY"
FORBIDDEN = {Path("/home/officehub/office-hub/frontend"), Path("/home/officehub/office-hub-lease-agreements/frontend"), Path("/home/officehub/office-hub-maint/frontend")}

def build_environment(parent, settings):
    key = settings.get(KEY)
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Required browser map configuration absent; refusing blank-map build")
    result = {k: v for k, v in parent.items() if k in {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR"}}
    result.update({KEY: key, "NEXT_TELEMETRY_DISABLED": "1", "NEXT_PUBLIC_API_URL": "/backend-api", "BACKEND_INTERNAL_URL": "http://127.0.0.1:8001", "NODE_OPTIONS": "--require " + str(ROOT / "ops/staging-integration/build_no_network.cjs")})
    return result

def assert_isolated(frontend, live_frontend):
    if frontend.resolve() in {p.resolve() for p in FORBIDDEN} | {live_frontend.resolve()}:
        raise ValueError("Refusing build in a live or fallback staging/production frontend")

def verify_output(frontend, key):
    static = frontend / ".next/static"
    inlined = any(key.encode() in p.read_bytes() for p in static.rglob("*.js"))
    html = frontend / ".next/server/app/rentals.html"
    if not inlined or not html.exists() or b"NEXT_PUBLIC_GOOGLE_MAPS_API_KEY is not configured" in html.read_bytes():
        raise ValueError("Built rentals page lacks required browser map configuration")
    return {"browser_map_key_inlined": True, "missing_key_banner": False}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frontend", type=Path, required=True)
    p.add_argument("--env", type=Path, required=True)
    p.add_argument("--log", type=Path, required=True)
    a = p.parse_args()
    try:
        live = Path(subprocess.check_output(["systemctl", "--user", "show", "officehub-staging-frontend.service", "-p", "WorkingDirectory", "--value"], text=True, stderr=subprocess.PIPE).strip())
        assert_isolated(a.frontend, live)
        env = build_environment(os.environ, dict(dotenv_values(a.env)))
        output = []
        for cmd in [["node", "node_modules/next/dist/bin/next", "build", "--webpack"], ["node", "scripts/check-client-api-urls.mjs"]]:
            result = subprocess.run(cmd, cwd=a.frontend, env=env, capture_output=True, text=True)
            output.append(result.stdout + result.stderr)
            fd = os.open(a.log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as log:
                log.write("\n".join(output).replace(env[KEY], "[REDACTED_BROWSER_MAP_KEY]"))
            if result.returncode:
                raise RuntimeError("Guarded frontend build failed; inspect protected redacted log")
        print(json.dumps(verify_output(a.frontend, env[KEY]), sort_keys=True))
        return 0
    except Exception as exc:
        print("Frontend build aborted: " + type(exc).__name__ + "; configuration/error values hidden")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
