"""Explicit RingCentral authentication and SMS smoke test.

Configuration is loaded directly from ~/office-hub/.env. The file is never
copied and configuration values are never included in command output.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Sequence

import httpx
from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
PRODUCTION_ENV_PATH = Path.home() / "office-hub" / ".env"
TEST_MESSAGE = "Office Hub RingCentral SMS test."
E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


class SmsTestError(RuntimeError):
    """A controlled error whose message is safe for command output."""


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SmsTestError(message)


@dataclass(frozen=True)
class Result:
    success: bool
    message_id: str | None = None
    http_status: str | None = None
    error_code: str | None = None
    message: str | None = None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = ArgumentParser(description="Authenticate with RingCentral or send one test SMS")
    parser.add_argument("number", nargs="?", help="E.164 recipient for send mode")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="authenticate only; do not send a message",
    )
    args = parser.parse_args(argv)
    if args.dry_run and args.number:
        raise SmsTestError("--dry-run does not accept a recipient number")
    if not args.dry_run and not args.number:
        raise SmsTestError("send mode requires an E.164 recipient number")
    if args.number and not E164_PATTERN.fullmatch(args.number):
        raise SmsTestError("recipient must be an E.164 number such as +12045550123")
    return args


def load_provider() -> tuple[object, tuple[str, ...]]:
    if not PRODUCTION_ENV_PATH.is_file():
        raise SmsTestError("configuration file is unavailable")
    load_dotenv(PRODUCTION_ENV_PATH, override=True)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    try:
        from app.core.config import settings
        from app.services.maintenance.sms.providers import RingCentralProvider
    except Exception as exc:
        raise SmsTestError("configuration could not be loaded") from exc

    client_secret = settings.ringcentral_client_secret.get_secret_value()
    jwt = settings.ringcentral_jwt.get_secret_value()
    values = (
        settings.ringcentral_server_url,
        settings.ringcentral_client_id,
        client_secret,
        jwt,
        settings.ringcentral_from_number,
    )
    if not all(value.strip() for value in values):
        raise SmsTestError("RingCentral configuration is incomplete")
    provider = RingCentralProvider(
        settings.ringcentral_server_url,
        settings.ringcentral_client_id,
        client_secret,
        jwt,
        settings.ringcentral_from_number,
    )
    return provider, values


async def run_test(provider: object, *, dry_run: bool, number: str | None) -> Result:
    try:
        authenticate = getattr(provider, "authenticate")
        await authenticate()
        if dry_run:
            return Result(success=True)
        send = getattr(provider, "send")
        message_id = await send(number, TEST_MESSAGE, [])
        return Result(success=True, message_id=_single_line(str(message_id)))
    finally:
        close = getattr(provider, "aclose", None)
        if close is not None:
            await close()


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _redact(value: str, configured_values: Sequence[str]) -> str:
    redacted = value
    for configured in configured_values:
        if configured:
            redacted = redacted.replace(configured, "[redacted]")
    return _single_line(redacted)


def _http_error(exc: httpx.HTTPStatusError, configured_values: Sequence[str]) -> Result:
    response = exc.response
    code: object = f"HTTP_{response.status_code}"
    message: object = response.reason_phrase or "RingCentral request failed"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload
        errors = payload.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            detail = errors[0]
        code = (
            detail.get("errorCode")
            or detail.get("code")
            or payload.get("error")
            or code
        )
        message = (
            detail.get("message")
            or detail.get("error_description")
            or payload.get("message")
            or payload.get("error_description")
            or message
        )
    return Result(
        success=False,
        http_status=str(response.status_code),
        error_code=_redact(str(code), configured_values),
        message=_redact(str(message), configured_values),
    )


def failure_result(exc: Exception, configured_values: Sequence[str]) -> Result:
    if isinstance(exc, httpx.HTTPStatusError):
        return _http_error(exc, configured_values)
    if isinstance(exc, httpx.RequestError):
        return Result(
            success=False,
            http_status="unavailable",
            error_code=type(exc).__name__,
            message="RingCentral request failed",
        )
    if isinstance(exc, SmsTestError):
        return Result(
            success=False,
            http_status="unavailable",
            error_code=type(exc).__name__,
            message=_single_line(str(exc)),
        )
    return Result(
        success=False,
        http_status="unavailable",
        error_code=type(exc).__name__,
        message="Unexpected RingCentral test failure",
    )


def print_result(result: Result) -> None:
    if result.success:
        print("SUCCESS")
        if result.message_id is not None:
            print(f"Message ID: {result.message_id}")
        return
    print("FAILURE")
    print(f"HTTP status: {result.http_status or 'unavailable'}")
    print(f"Error code: {result.error_code or 'unknown'}")
    print(f"Message: {result.message or 'RingCentral test failed'}")


def main(argv: Sequence[str] | None = None) -> int:
    configured_values: tuple[str, ...] = ()
    try:
        args = parse_args(argv)
        provider, configured_values = load_provider()
        result = asyncio.run(run_test(provider, dry_run=args.dry_run, number=args.number))
    except Exception as exc:
        result = failure_result(exc, configured_values)
    print_result(result)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
