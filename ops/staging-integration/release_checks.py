#!/usr/bin/env python3
"""Read-only staging release gates. Never display config or credential values."""
from __future__ import annotations
import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from types import SimpleNamespace

NAMES = ("backend", "frontend", "worker", "beat")
OVERRIDE_NAME = "zz-lease-maint.conf"
PINNED = {"celery": "5.4.0", "kombu": "5.6.2", "redis": "5.2.0"}

def checked_transport(versions, client_factory):
    if versions != PINNED:
        raise ValueError("Installed transport versions do not match reviewed pins")
    client_factory(SimpleNamespace(global_keyprefix=""))
    return versions

def transport():
    from kombu.transport.redis import Channel
    return checked_transport({k: metadata.version(k) for k in PINNED}, Channel._get_client)

def expected(name, release, env_dir):
    release, env_dir = Path(release), Path(env_dir)
    folder = "frontend" if name == "frontend" else "backend"
    env = name if name in {"backend", "frontend"} else "worker"
    commands = {
        "backend": [str(release / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port", "8001"],
        "frontend": ["/usr/bin/npm", "start", "--", "--hostname", "127.0.0.1", "--port", "3001"],
        "worker": [str(release / ".venv/bin/celery"), "-A", "app.workers.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"],
        "beat": [str(release / ".venv/bin/celery"), "-A", "app.workers.celery_app:celery_app", "beat", "--loglevel=INFO", "--pidfile=" + os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}") + "/officehub-staging-beat/celerybeat.pid", "--schedule=" + os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")) + "/officehub-staging/celerybeat-schedule"],
    }
    return {"WorkingDirectory": str(release / folder), "EnvironmentFiles": [str(env_dir / (env + ".env"))], "argv": commands[name]}

def assert_effective(name, values, release, env_dir):
    want = expected(name, release, env_dir)
    if values["WorkingDirectory"] != want["WorkingDirectory"]:
        raise ValueError(name + " WorkingDirectory mismatch")
    files = re.findall(r"(/\S+)\s+\(ignore_errors=(?:yes|no)\)", values["EnvironmentFiles"])
    if files != want["EnvironmentFiles"]:
        raise ValueError(name + " EnvironmentFiles mismatch")
    matches = re.findall(r"argv\[\]=(.*?)\s+;", values["ExecStart"])
    if len(matches) != 1 or shlex.split(matches[0]) != want["argv"]:
        raise ValueError(name + " ExecStart mismatch")

def show(name, prop):
    return subprocess.check_output(["systemctl", "--user", "show", "officehub-staging-" + name + ".service", "-p", prop, "--value"], text=True).strip()

def effective(release, env_dir):
    units = ["officehub-staging-" + name + ".service" for name in NAMES]
    result = subprocess.run(["systemd-analyze", "--user", "verify", *units], capture_output=True)
    if result.returncode:
        raise ValueError("systemd unit verification failed; values hidden")
    for name in NAMES:
        assert_effective(name, {k: show(name, k) for k in ("WorkingDirectory", "EnvironmentFiles", "ExecStart")}, release, env_dir)
    return {name: "effective config verified" for name in NAMES}

def assert_running(values, baseline=None):
    if values["ActiveState"] != "active" or values["SubState"] != "running" or int(values["MainPID"]) <= 0:
        raise ValueError("Service is not running")
    if baseline and any(values[k] != baseline[k] for k in ("MainPID", "NRestarts", "InvocationID")):
        raise ValueError("Service restarted during stability window")

def stable(release, env_dir, seconds=10):
    if seconds < 10:
        raise ValueError("Stability window must be at least ten seconds")
    effective(release, env_dir)
    fields = ("ActiveState", "SubState", "MainPID", "NRestarts", "InvocationID")
    baseline = {name: {k: show(name, k) for k in fields} for name in NAMES}
    for name, values in baseline.items():
        assert_running(values)
        if str(Path("/proc").joinpath(values["MainPID"], "cwd").resolve()) != expected(name, release, env_dir)["WorkingDirectory"]:
            raise ValueError(name + " running process cwd mismatch")
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for name in ("worker", "beat"):
            assert_running({k: show(name, k) for k in fields}, baseline[name])
        time.sleep(min(1, max(0, end-time.monotonic())))
    for name, marker in (("worker", " ready."), ("beat", "beat: Starting")):
        result = subprocess.run(["journalctl", "--user", "-u", "officehub-staging-" + name + ".service", "_SYSTEMD_INVOCATION_ID=" + baseline[name]["InvocationID"], "-o", "json", "--no-pager"], capture_output=True, text=True)
        messages = [json.loads(line).get("MESSAGE", "") for line in result.stdout.splitlines()]
        if result.returncode or not any(marker in message for message in messages):
            raise ValueError(name + " did not report readiness in current invocation")
    return {"stable_seconds": seconds, "pids": {k: int(v["MainPID"]) for k,v in baseline.items()}}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["transport", "effective", "stable"])
    p.add_argument("--release", type=Path)
    p.add_argument("--env-dir", type=Path)
    p.add_argument("--seconds", type=int, default=10)
    a = p.parse_args()
    try:
        if a.action == "transport":
            result = transport()
        else:
            if not a.release or not a.env_dir:
                raise ValueError("Release and env dir required")
            result = effective(a.release, a.env_dir) if a.action == "effective" else stable(a.release, a.env_dir, a.seconds)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print("Release gate failed: " + type(exc).__name__ + "; config/error values hidden")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
