from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.maintenance.slack.users import resolve_slack_user


class Rows:
    def __init__(self, values): self.values = values
    def all(self): return self.values


class Session:
    def __init__(self, candidates): self.candidates = candidates; self.flushed = False
    async def scalar(self, statement): return None
    async def scalars(self, statement): return Rows(self.candidates)
    async def flush(self): self.flushed = True


class Client:
    async def users_lookupByEmail(self, *, email):
        return {"user": {"id": "U-MATCH" if email == "match@example.com" else "U-OTHER"}}


@pytest.mark.asyncio
async def test_missing_slack_user_is_auto_linked_by_office_email() -> None:
    match = SimpleNamespace(email="match@example.com", slack_user_id=None)
    other = SimpleNamespace(email="other@example.com", slack_user_id=None)
    db = Session([match, other])
    result = await resolve_slack_user(db, Client(), "U-MATCH")  # type: ignore[arg-type]
    assert result is match
    assert match.slack_user_id == "U-MATCH"
    assert other.slack_user_id == "U-OTHER"
    assert db.flushed is True
