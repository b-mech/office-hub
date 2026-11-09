from __future__ import annotations

from pathlib import Path
import subprocess

import httpx
import pytest

from app.services.maintenance import subscription_renewal as renewal

CALLBACK = "https://staging.invalid/api/webhooks/ringcentral/sms"


def install_transport(monkeypatch: pytest.MonkeyPatch, handler: object) -> None:
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(renewal.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))


@pytest.mark.asyncio
async def test_empty_post_challenge_echo_and_private_token_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    challenges: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.content == b""
        assert "Verification-Token" not in request.headers
        challenge = request.headers["Validation-Token"]
        assert challenge and challenge != "configured-private-token"
        challenges.append(challenge)
        return httpx.Response(200, headers={"Validation-Token": challenge})

    install_transport(monkeypatch, handler)
    await renewal.verify_public_webhook_token(CALLBACK, "configured-private-token")
    await renewal.verify_public_webhook_token(CALLBACK, "configured-private-token")
    assert len(set(challenges)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,echo", [(404, None), (302, None), (200, None), (200, "wrong")])
async def test_http_failure_access_redirect_or_missing_mismatched_echo_fails_closed(
    monkeypatch: pytest.MonkeyPatch, status: int, echo: str | None,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        headers = {"Location": "https://access.invalid/login"}
        if echo is not None:
            headers["Validation-Token"] = echo
        return httpx.Response(status, headers=headers, text="private-response-must-not-appear")

    install_transport(monkeypatch, handler)
    with pytest.raises(renewal.RingCentralSubscriptionError) as raised:
        await renewal.verify_public_webhook_token(CALLBACK, "configured-private-token")
    assert len(calls) == 1  # No Access redirects followed.
    assert "private-response-must-not-appear" not in str(raised.value)
    assert "configured-private-token" not in str(raised.value)


def test_lease_frontend_config_patch_applies_and_preserves_backend_proxy(tmp_path: Path) -> None:
    fixture = tmp_path / "frontend" / "next.config.ts"
    fixture.parent.mkdir()
    fixture.write_text('''import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["*.trycloudflare.com"],
  async rewrites() {
    return [
      {
        source: "/backend-api/:path*",
        destination: `${process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
''')
    root = Path(__file__).resolve().parents[2]
    patch = root / "ops/staging-ringcentral/lease-frontend-webhook-rewrite.patch"
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=tmp_path, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=tmp_path, check=True)
    configured = fixture.read_text()
    assert 'source: "/backend-api/:path*"' in configured
    assert 'source: "/api/webhooks/:path*"' in configured
    assert '}/api/webhooks/:path*`' in configured
    assert '"http://127.0.0.1:8000"' in configured  # Runtime/build env must select staging 8001.
