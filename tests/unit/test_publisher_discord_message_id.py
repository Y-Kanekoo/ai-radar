"""publisher.discord.send_notification_with_message_id (Phase 4a)."""

from __future__ import annotations

import asyncio

import httpx

from ai_radar.publisher.discord import send_notification_with_message_id
from ai_radar.publisher.rss import FeedItem


def _item() -> FeedItem:
    return FeedItem(
        id="https://e.com/1",
        url="https://e.com/1",
        title="Title",
        snippet="Snip",
        source_name="src",
        author=None,
        published_at=1700000000,
        tags=(),
    )


def test_send_with_message_id_appends_wait_query() -> None:
    """?wait=true が URL に付与される (既存 ? の有無を吸収)."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(204)  # no body

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        asyncio.run(
            send_notification_with_message_id(
                _item(), "https://discord.com/api/webhooks/A/B", client=client
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert "wait=true" in captured["url"]


def test_send_with_message_id_existing_query_uses_amp() -> None:
    """既存 query 付きの URL でも & で繋がる."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        asyncio.run(
            send_notification_with_message_id(
                _item(),
                "https://discord.com/api/webhooks/A/B?foo=1",
                client=client,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert "foo=1" in captured["url"]
    assert "wait=true" in captured["url"]


def test_send_with_message_id_returns_ids_on_success() -> None:
    """200 で body に id / channel_id があれば返却."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "MSG123", "channel_id": "CHAN456"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        ok, msg_id, ch_id = asyncio.run(
            send_notification_with_message_id(
                _item(), "https://discord.com/api/webhooks/A/B", client=client
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert ok is True
    assert msg_id == "MSG123"
    assert ch_id == "CHAN456"


def test_send_with_message_id_returns_none_ids_when_body_missing() -> None:
    """204 (no body) でも True を返し、ID は None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        ok, msg_id, ch_id = asyncio.run(
            send_notification_with_message_id(
                _item(), "https://discord.com/api/webhooks/A/B", client=client
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert ok is True
    assert msg_id is None
    assert ch_id is None


def test_send_with_message_id_failure_returns_false() -> None:
    """500 で (False, None, None)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        result = asyncio.run(
            send_notification_with_message_id(
                _item(), "https://discord.com/api/webhooks/A/B", client=client
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert result == (False, None, None)
