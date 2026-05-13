"""scripts/notify_discord._send_per_item_and_mark の orchestration テスト (Phase 4a).

`send_notification_with_message_id` を単体で testしている既存テストとは別に、
本番経路全体 (fetch_unnotified → 配信 → mark_notified_with_message_id) が結合する
ことを確認する. advisor 指摘の「新コード経路に orchestration テストが無い」への対応.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

import scripts.notify_discord as nd
from ai_radar.crawler.store import ArticleRow, insert_article, upsert_source
from ai_radar.db import init_db
from ai_radar.publisher.notification_state import (
    UnnotifiedArticle,
    discord_channel_for_category,
)
from ai_radar.publisher.rss import FeedItem
from ai_radar.sources import FetchPolicy, SourceConfig


def _src(slug: str = "src_release", category: str = "release", tier: int = 1) -> SourceConfig:
    return SourceConfig(
        slug=slug,
        name=f"Source {slug}",
        feed_url=f"https://{slug}.example.com/f",
        site_url=None,
        language="en",
        category=category,
        enabled=True,
        fetch_policy=FetchPolicy(min_interval_seconds=0, max_items_per_fetch=10),
        license_note="",
        tier=tier,
    )


def _setup_article(conn, guid: str = "g1", published_at: int = 1700000000) -> int:
    sid = upsert_source(conn, _src())
    insert_article(
        conn,
        ArticleRow(
            source_id=sid,
            guid=guid,
            url=f"https://e.com/{guid}",
            title=f"title-{guid}",
            snippet="snip",
            body_hash=guid,
            body="b",
            author=None,
            published_at=published_at,
            tags=[],
        ),
    )
    return int(conn.execute("SELECT id FROM articles WHERE guid = ?", (guid,)).fetchone()["id"])


def _make_eligible(article_id: int, *, is_hype: bool = False) -> UnnotifiedArticle:
    return UnnotifiedArticle(
        article_id=article_id,
        item=FeedItem(
            id=f"https://e.com/{article_id}",
            url=f"https://e.com/{article_id}",
            title="t",
            snippet="s",
            source_name="src_release",
            author=None,
            published_at=1700000000,
            tags=(),
        ),
        category="release",
        tier=1,
        is_hype=is_hype,
    )


def test_send_per_item_and_mark_persists_message_id(tmp_path: Path) -> None:
    """Discord が ``{"id": "MSG1", "channel_id": "CHAN1"}`` を返したとき、
    article_notifications に discord_message_id / discord_channel_id が保存される.
    """
    conn = init_db(tmp_path / "t.db")
    try:
        aid = _setup_article(conn)
        eligible = [_make_eligible(aid)]

        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"id": "MSG1", "channel_id": "CHAN1"})

        # `_send_per_item_and_mark` は内部で AsyncClient を生成するため、httpx の
        # transport をパッチしてレスポンスを差し替える.
        transport = httpx.MockTransport(handler)
        orig_async_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return orig_async_client(*args, **kwargs)

        nd.httpx.AsyncClient = factory  # type: ignore[assignment]
        try:
            success, failure = asyncio.run(
                nd._send_per_item_and_mark(
                    conn,
                    eligible,
                    webhook_url="https://discord.com/api/webhooks/A/B",
                    channel=discord_channel_for_category("release"),
                    rate_delay=0,
                    log=logging.getLogger("test"),
                )
            )
        finally:
            nd.httpx.AsyncClient = orig_async_client  # type: ignore[assignment]

        assert success == 1
        assert failure == 0
        assert "wait=true" in captured["url"]

        row = conn.execute(
            "SELECT discord_message_id, discord_channel_id FROM article_notifications "
            "WHERE article_id = ? AND channel = ?",
            (aid, "discord_release"),
        ).fetchone()
        assert row is not None
        assert row["discord_message_id"] == "MSG1"
        assert row["discord_channel_id"] == "CHAN1"
    finally:
        conn.close()


def test_send_per_item_and_mark_falls_back_when_no_body(tmp_path: Path) -> None:
    """204 等で id が返らない場合は mark_notified にフォールバックし、
    discord_message_id は NULL のまま行は作成される (重複送信防止).
    """
    conn = init_db(tmp_path / "t.db")
    try:
        aid = _setup_article(conn, guid="g2")
        eligible = [_make_eligible(aid)]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        transport = httpx.MockTransport(handler)
        orig_async_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return orig_async_client(*args, **kwargs)

        nd.httpx.AsyncClient = factory  # type: ignore[assignment]
        try:
            success, failure = asyncio.run(
                nd._send_per_item_and_mark(
                    conn,
                    eligible,
                    webhook_url="https://discord.com/api/webhooks/A/B",
                    channel=discord_channel_for_category("release"),
                    rate_delay=0,
                    log=logging.getLogger("test"),
                )
            )
        finally:
            nd.httpx.AsyncClient = orig_async_client  # type: ignore[assignment]

        assert success == 1
        assert failure == 0
        row = conn.execute(
            "SELECT discord_message_id FROM article_notifications WHERE article_id = ?",
            (aid,),
        ).fetchone()
        assert row is not None
        assert row["discord_message_id"] is None
    finally:
        conn.close()


def test_send_per_item_and_mark_failure_leaves_unmarked(tmp_path: Path) -> None:
    """500 で送信失敗した場合、article_notifications に行が作成されない
    (次回 cron で再試行できる).
    """
    conn = init_db(tmp_path / "t.db")
    try:
        aid = _setup_article(conn, guid="g3")
        eligible = [_make_eligible(aid)]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        orig_async_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return orig_async_client(*args, **kwargs)

        nd.httpx.AsyncClient = factory  # type: ignore[assignment]
        try:
            success, failure = asyncio.run(
                nd._send_per_item_and_mark(
                    conn,
                    eligible,
                    webhook_url="https://discord.com/api/webhooks/A/B",
                    channel=discord_channel_for_category("release"),
                    rate_delay=0,
                    log=logging.getLogger("test"),
                )
            )
        finally:
            nd.httpx.AsyncClient = orig_async_client  # type: ignore[assignment]

        assert success == 0
        assert failure == 1
        row = conn.execute(
            "SELECT id FROM article_notifications WHERE article_id = ?",
            (aid,),
        ).fetchone()
        assert row is None  # 失敗時は再試行可能性のため mark しない
    finally:
        conn.close()
