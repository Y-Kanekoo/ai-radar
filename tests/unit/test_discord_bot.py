"""Discord Bot API クライアントの parse + retry ロジック (Phase 4a)."""

from __future__ import annotations

import asyncio

import httpx

from ai_radar.publisher.discord_bot import (
    ReactionRow,
    _emoji_label,
    _parse_reactions,
    fetch_message_reactions,
)

# ---------------- _emoji_label ----------------


def test_emoji_label_unicode() -> None:
    """通常絵文字は name そのもの."""
    assert _emoji_label({"name": "👍", "id": None}) == "👍"


def test_emoji_label_custom() -> None:
    """カスタム絵文字は ``name:id``."""
    assert _emoji_label({"name": "claude", "id": "123456"}) == "claude:123456"


def test_emoji_label_invalid_returns_none() -> None:
    """name が文字列でない / 空 / 非 dict は None."""
    assert _emoji_label(None) is None
    assert _emoji_label({"name": ""}) is None
    assert _emoji_label({"name": 42}) is None
    assert _emoji_label("not a dict") is None


# ---------------- _parse_reactions ----------------


def test_parse_reactions_empty_when_field_missing() -> None:
    """``reactions`` フィールド無しなら空."""
    assert _parse_reactions({}) == []


def test_parse_reactions_extracts_emoji_and_count() -> None:
    """通常絵文字 + count を抽出."""
    body = {
        "reactions": [
            {"emoji": {"name": "👍", "id": None}, "count": 3},
            {"emoji": {"name": "🚀", "id": None}, "count": 1},
        ]
    }
    out = _parse_reactions(body)
    assert out == [
        ReactionRow(emoji="👍", user_count=3),
        ReactionRow(emoji="🚀", user_count=1),
    ]


def test_parse_reactions_skips_invalid_entries() -> None:
    """name 不正 / count 非整数 / count 負数の行は skip."""
    body = {
        "reactions": [
            {"emoji": {"name": "👍"}, "count": 2},
            {"emoji": {"name": ""}, "count": 5},  # name 空
            {"emoji": {"name": "x"}, "count": -1},  # negative
            {"emoji": {"name": "y"}, "count": "many"},  # not int
            "not a dict",
        ]
    }
    out = _parse_reactions(body)
    assert out == [ReactionRow(emoji="👍", user_count=2)]


# ---------------- fetch_message_reactions ----------------


def test_fetch_message_reactions_success() -> None:
    """200 + reactions を含む body → ReactionRow リスト."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"].startswith("Bot ")
        return httpx.Response(
            200,
            json={
                "id": "msg1",
                "reactions": [
                    {"emoji": {"name": "👍", "id": None}, "count": 5},
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        rows = asyncio.run(fetch_message_reactions("CHAN", "MSG", "TOK", client=client))
    finally:
        asyncio.run(client.aclose())
    assert rows == [ReactionRow(emoji="👍", user_count=5)]


def test_fetch_message_reactions_404_returns_none() -> None:
    """404 (削除済) は None で retry なし."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={"message": "Unknown Message"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        rows = asyncio.run(fetch_message_reactions("C", "M", "T", client=client))
    finally:
        asyncio.run(client.aclose())
    assert rows is None
    assert calls["n"] == 1


def test_fetch_message_reactions_403_returns_none() -> None:
    """403 (権限不足) も None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Missing Permissions"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        rows = asyncio.run(fetch_message_reactions("C", "M", "T", client=client))
    finally:
        asyncio.run(client.aclose())
    assert rows is None


def test_fetch_message_reactions_429_retries_then_succeeds() -> None:
    """429 を 1 回返してから 200 → retry で成功."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "0.01"},
                json={"retry_after": 0.01, "message": "rate limited"},
            )
        return httpx.Response(200, json={"reactions": []})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        rows = asyncio.run(fetch_message_reactions("C", "M", "T", client=client))
    finally:
        asyncio.run(client.aclose())
    assert rows == []
    assert calls["n"] == 2
