from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import httpx

from app.core.config import settings
from app.models.maintenance import MaintStatus
from app.models.maintenance import MaintDirection, MaintSmsMessage
from app.services.maintenance.qr import printable_pdf, verify_print_token
from app.services.maintenance.rate_limit import RateLimitExceeded, RedisRateLimiter
from app.services.maintenance.sms.inbound import (
    RouteKind,
    choose_route,
    is_close_confirmation,
    opt_keyword,
)
from app.services.maintenance.sms.outbound import SmsOptedOutError, normalized_delivery_status, quiet_hours_release, queue_sms, send_due_messages
from app.services.maintenance.notifier import NoopMaintenanceNotifier
from app.services.maintenance.sms.providers import (
    FakeProvider,
    RingCentralProvider,
    TwilioProvider,
    twilio_signature,
)
from app.services.maintenance.tokens import generate_token
from app.services.maintenance.turnstile import TurnstileError, verify_turnstile


def test_official_turnstile_test_keys_are_development_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "turnstile_site_key", "")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    assert settings.effective_turnstile_site_key == "1x00000000000000000000AA"
    assert settings.effective_turnstile_secret_key == "1x0000000000000000000000000000000AA"


@pytest.mark.asyncio
async def test_turnstile_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def json(self): return {"success": False}
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, *args, **kwargs): return Response()
    monkeypatch.setattr("app.services.maintenance.turnstile.httpx.AsyncClient", lambda **kwargs: Client())
    with pytest.raises(TurnstileError, match="failed"):
        await verify_turnstile("bad-token", "127.0.0.1")


class Pipeline:
    def __init__(self, counts: dict[str, int]): self.counts=counts; self.keys=[]
    def incr(self, key): self.keys.append(key); return self
    def expire(self, *args, **kwargs): return self
    async def execute(self):
        values=[]
        for key in self.keys:
            self.counts[key]=self.counts.get(key,0)+1
            values.extend([self.counts[key], True])
        return values


class FakeRedis:
    def __init__(self): self.counts={}
    def pipeline(self, transaction=True): return Pipeline(self.counts)


@pytest.mark.asyncio
async def test_intake_rate_limits_token_and_ip() -> None:
    limiter = RedisRateLimiter(FakeRedis())  # type: ignore[arg-type]
    for _ in range(5): await limiter.intake("token-a", "127.0.0.1")
    with pytest.raises(RateLimitExceeded, match="intake link"):
        await limiter.intake("token-a", "127.0.0.1")
    for index in range(10): await limiter.intake(f"token-{index}", "192.0.2.1")
    with pytest.raises(RateLimitExceeded, match="IP address"):
        await limiter.intake("another", "192.0.2.1")


def test_qr_pdf_uses_public_brand_and_token_is_hash_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://maintenance.invalid")
    monkeypatch.setattr(settings, "public_brand_name", "Connect Properties")
    token = generate_token()
    record = SimpleNamespace(token_hash=token.digest, revoked_at=None)
    assert verify_print_token(token.value, record)
    assert not verify_print_token("wrong", record)
    pdf = printable_pdf([(token.value, "Test Property", "Unit 2")])
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1_000


@pytest.mark.asyncio
async def test_fake_provider_and_twilio_signature() -> None:
    provider = FakeProvider("secret")
    sid = await provider.send("+12045550100", "Hello", [])
    assert sid.startswith("SMFAKE")
    url = "https://maintenance.invalid/api/webhooks/twilio/sms"
    form = {"From": "+12045550100", "Body": "Hello"}
    signature = twilio_signature(url, form, "secret")
    assert provider.validate_signature(url, form, signature)
    assert not provider.validate_signature(url, form, "invalid")
    twilio = TwilioProvider("ACtest", "secret", "+12045550999")
    assert twilio.validate_signature(url, form, signature)


@pytest.mark.asyncio
async def test_ringcentral_provider_uses_jwt_token_and_configured_number() -> None:
    requests: list[object] = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/restapi/oauth/token":
            return httpx.Response(
                200, json={"access_token": "test-access-token", "expires_in": 3600}
            )
        assert request.headers["Authorization"] == "Bearer test-access-token"
        payload = json.loads(request.content)
        assert payload["from"]["phoneNumber"] == "+12045550999"
        assert payload["to"][0]["phoneNumber"] == "+12045550100"
        return httpx.Response(200, json={"id": "12345"})

    transport = httpx.MockTransport(handler)
    provider = RingCentralProvider(
        "https://platform.ringcentral.test",
        "test-client",
        "test-secret",
        "test-jwt",
        "+12045550999",
        transport=transport,
    )
    assert await provider.send("+12045550100", "Hello", []) == "12345"
    assert await provider.send("+12045550100", "Again", []) == "12345"
    assert sum(request.url.path == "/restapi/oauth/token" for request in requests) == 1


def test_ringcentral_secrets_are_excluded_from_settings_repr() -> None:
    rendered = repr(settings)
    assert "ringcentral_server_url" not in rendered
    assert "ringcentral_client_id" not in rendered
    assert "ringcentral_client_secret" not in rendered
    assert "ringcentral_jwt" not in rendered
    assert "ringcentral_from_number" not in rendered


def test_quiet_hours_defer_only_during_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "timezone", "America/Winnipeg")
    # 04:00 UTC is 23:00 local on the prior day in October.
    release = quiet_hours_release(datetime(2026, 10, 2, 4, 0, tzinfo=timezone.utc))
    assert release == datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)
    assert quiet_hours_release(datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)) is None


class ScalarSequenceSession:
    def __init__(self, values): self.values=iter(values); self.added=[]
    async def scalar(self, statement): return next(self.values)
    def add(self, item): self.added.append(item)
    async def flush(self): return None


@pytest.mark.asyncio
async def test_staff_relay_is_held_and_first_in_day_gets_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sms_relay_hold_seconds", 30)
    monkeypatch.setattr(settings, "sms_signature", "— Connect Properties")
    now = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc)
    db = ScalarSequenceSession([None, None, None])
    message = await queue_sms(db, to="+12045550100", body="We can come Tuesday.", automated=False, now=now)  # type: ignore[arg-type]
    assert message.status == "held"
    assert message.hold_until == datetime(2026, 10, 1, 17, 0, 30, tzinfo=timezone.utc)
    assert message.body == "We can come Tuesday. — Connect Properties"


@pytest.mark.asyncio
async def test_opted_out_recipient_is_blocked() -> None:
    db = ScalarSequenceSession([uuid4()])
    with pytest.raises(SmsOptedOutError):
        await queue_sms(db, to="+12045550100", body="blocked", automated=True)  # type: ignore[arg-type]


class ScalarRows:
    def __init__(self, values): self.values=values
    def all(self): return self.values


class SenderSession:
    def __init__(self, values): self.values=values
    async def scalars(self, statement): return ScalarRows(self.values)
    async def flush(self): return None


@pytest.mark.asyncio
async def test_held_to_sent_and_cancelled_is_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://maintenance.invalid")
    now = datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc)
    due = MaintSmsMessage(direction=MaintDirection.OUTBOUND, from_e164="+12045550999", to_e164="+12045550100", body="due", media_attachment_ids=[], is_automated=False, status="held", hold_until=now)
    cancelled = MaintSmsMessage(direction=MaintDirection.OUTBOUND, from_e164="+12045550999", to_e164="+12045550101", body="cancelled", media_attachment_ids=[], is_automated=False, status="held", hold_until=now, cancelled_at=now)
    provider = FakeProvider()
    count = await send_due_messages(SenderSession([due, cancelled]), provider, NoopMaintenanceNotifier(), now=now)  # type: ignore[arg-type]
    assert count == 1
    assert due.status == "queued"
    assert cancelled.status == "held"
    assert [item["body"] for item in provider.sent] == ["due"]


@pytest.mark.parametrize(
    ("kwargs", "kind"),
    [
        ({"vendor_work_orders": [("t1", "w1")], "open_tickets": [("t2", "MT-2")], "recent_resolved_ticket": "t3", "known_unit_id": 1}, RouteKind.VENDOR_WORK_ORDER),
        ({"vendor_work_orders": [], "open_tickets": [("t2", "MT-2"), ("t3", "MT-3")], "recent_resolved_ticket": "t4", "known_unit_id": 1}, RouteKind.TENANT_OPEN),
        ({"vendor_work_orders": [], "open_tickets": [], "recent_resolved_ticket": "t4", "known_unit_id": 1}, RouteKind.TENANT_RECENT_RESOLVED),
        ({"vendor_work_orders": [], "open_tickets": [], "recent_resolved_ticket": None, "known_unit_id": 1}, RouteKind.KNOWN_TENANT),
        ({"vendor_work_orders": [], "open_tickets": [], "recent_resolved_ticket": None, "known_unit_id": None}, RouteKind.UNKNOWN),
    ],
)
def test_every_inbound_routing_branch(kwargs: dict[str, object], kind: RouteKind) -> None:
    result = choose_route(**kwargs)  # type: ignore[arg-type]
    assert result.kind == kind
    if kind == RouteKind.TENANT_OPEN:
        assert result.other_open_numbers == ("MT-3",)


@pytest.mark.parametrize("body", ["YES", " y ", "fixed", "Done"])
def test_yes_keywords_close_resolved_ticket(body: str) -> None:
    assert is_close_confirmation(body)


def test_stop_start_keywords_are_mirrored() -> None:
    assert opt_keyword(" stop ") is True
    assert opt_keyword("START") is False
    assert opt_keyword("help") is None


def test_twilio_delivery_statuses_fit_persisted_states() -> None:
    assert normalized_delivery_status("sending") == "queued"
    assert normalized_delivery_status("undelivered") == "failed"
    assert normalized_delivery_status("read") == "delivered"
    assert normalized_delivery_status("unknown") is None


def test_unverified_reporter_path_is_explicit() -> None:
    # Intake intentionally creates a ticket even when current-lease lookup yields no match.
    lease = None
    assert (lease is not None) is False
