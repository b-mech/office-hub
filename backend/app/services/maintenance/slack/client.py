from __future__ import annotations

from typing import Protocol

import httpx

from app.core.config import settings


class SlackClient(Protocol):
    async def post_message(self, channel: str, text: str) -> dict[str, object]: ...
    async def lookup_user_by_email(self, email: str) -> str | None: ...
    async def open_dm(self, slack_user_id: str) -> str: ...


class SlackApiError(RuntimeError):
    def __init__(self, message: str, response: httpx.Response) -> None:
        super().__init__(message)
        self.response = response


class HttpSlackClient:
    """Small outbound-only Slack Web API client."""

    def __init__(self, token: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.token = token if token is not None else settings.slack_bot_token
        self.transport = transport

    async def _call(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        async with httpx.AsyncClient(
            base_url="https://slack.com/api/",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=15,
            transport=self.transport,
        ) as client:
            response = await client.post(method, json=payload)
        if response.status_code == 429:
            raise SlackApiError("Slack rate limit", response)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise SlackApiError(f"Slack API error: {data.get('error', 'unknown_error')}", response)
        return data

    async def post_message(self, channel: str, text: str) -> dict[str, object]:
        return await self._call(
            "chat.postMessage",
            {"channel": channel, "text": text, "unfurl_links": False, "unfurl_media": False},
        )

    async def lookup_user_by_email(self, email: str) -> str | None:
        data = await self._call("users.lookupByEmail", {"email": email})
        user = data.get("user")
        return str(user.get("id")) if isinstance(user, dict) and user.get("id") else None

    async def open_dm(self, slack_user_id: str) -> str:
        data = await self._call("conversations.open", {"users": slack_user_id})
        channel = data.get("channel")
        if not isinstance(channel, dict) or not channel.get("id"):
            raise RuntimeError("Slack did not return a DM channel")
        return str(channel["id"])
