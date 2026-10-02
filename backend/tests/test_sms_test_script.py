from __future__ import annotations

import asyncio

import httpx

from scripts.sms_test import (
    PRODUCTION_ENV_PATH,
    failure_result,
    parse_args,
    print_result,
    run_test,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.authenticated = 0
        self.sent: list[tuple[object, ...]] = []

    async def authenticate(self) -> None:
        self.authenticated += 1

    async def send(self, *args: object) -> str:
        self.sent.append(args)
        return "message-123"


def test_dry_run_authenticates_without_sending(capsys) -> None:
    provider = RecordingProvider()
    result = asyncio.run(run_test(provider, dry_run=True, number=None))
    print_result(result)
    assert provider.authenticated == 1
    assert provider.sent == []
    assert capsys.readouterr().out == "SUCCESS\n"


def test_send_uses_positional_number_and_limits_output(capsys) -> None:
    args = parse_args(["+12045550123"])
    provider = RecordingProvider()
    result = asyncio.run(run_test(provider, dry_run=args.dry_run, number=args.number))
    print_result(result)
    assert provider.authenticated == 1
    assert provider.sent == [("+12045550123", "Office Hub RingCentral SMS test.", [])]
    assert capsys.readouterr().out == "SUCCESS\nMessage ID: message-123\n"


def test_http_error_is_structured_and_redacts_configuration(capsys) -> None:
    secret = "configured-secret"
    request = httpx.Request("POST", "https://ringcentral.invalid/restapi/oauth/token")
    response = httpx.Response(
        401,
        request=request,
        json={"errorCode": "OAU-213", "message": f"Invalid credential {secret}"},
    )
    error = httpx.HTTPStatusError("ignored", request=request, response=response)
    result = failure_result(error, (secret,))
    print_result(result)
    output = capsys.readouterr().out
    assert output == (
        "FAILURE\n"
        "HTTP status: 401\n"
        "Error code: OAU-213\n"
        "Message: Invalid credential [redacted]\n"
    )
    assert secret not in output


def test_configuration_path_is_production_checkout_without_copying() -> None:
    assert PRODUCTION_ENV_PATH == PRODUCTION_ENV_PATH.home() / "office-hub" / ".env"
