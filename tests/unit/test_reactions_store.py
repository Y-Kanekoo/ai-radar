"""reactions テーブル I/O のテスト (Phase 4a)."""

from __future__ import annotations

from pathlib import Path

from ai_radar.crawler.store import ArticleRow, insert_article, upsert_source
from ai_radar.db import init_db
from ai_radar.publisher.reactions_store import (
    ReactionEntry,
    aggregate_reactions_by_source,
    insert_reactions,
    latest_collected_at,
)
from ai_radar.sources import FetchPolicy, SourceConfig


def _setup_article(conn, slug: str = "src1") -> int:
    src = SourceConfig(
        slug=slug,
        name=slug,
        feed_url=f"https://{slug}.example.com/f",
        site_url=None,
        language="en",
        category="release",
        enabled=True,
        fetch_policy=FetchPolicy(min_interval_seconds=0, max_items_per_fetch=10),
        license_note="",
    )
    sid = upsert_source(conn, src)
    insert_article(
        conn,
        ArticleRow(
            source_id=sid,
            guid=f"{slug}-g",
            url=f"https://e.com/{slug}",
            title="t",
            snippet="s",
            body_hash="h",
            body="b",
            author=None,
            published_at=1700000000,
            tags=[],
        ),
    )
    return int(
        conn.execute("SELECT id FROM articles WHERE guid = ?", (f"{slug}-g",)).fetchone()["id"]
    )


def test_insert_reactions_persists_rows(tmp_path: Path) -> None:
    """新規 INSERT で挿入件数が返り、SELECT で取れる."""
    conn = init_db(tmp_path / "t.db")
    try:
        aid = _setup_article(conn)
        entries = [
            ReactionEntry(
                article_id=aid,
                discord_message_id="M1",
                discord_channel_id="C1",
                emoji="👍",
                user_count=3,
                collected_at=1700001000,
            ),
            ReactionEntry(
                article_id=aid,
                discord_message_id="M1",
                discord_channel_id="C1",
                emoji="🚀",
                user_count=1,
                collected_at=1700001000,
            ),
        ]
        n = insert_reactions(conn, entries)
        assert n == 2
        rows = conn.execute("SELECT emoji, user_count FROM reactions").fetchall()
        assert len(rows) == 2
    finally:
        conn.close()


def test_insert_reactions_unique_blocks_duplicates(tmp_path: Path) -> None:
    """同 (article_id, emoji, collected_at) は INSERT OR IGNORE で弾かれる."""
    conn = init_db(tmp_path / "t.db")
    try:
        aid = _setup_article(conn)
        e = ReactionEntry(
            article_id=aid,
            discord_message_id="M",
            discord_channel_id="C",
            emoji="👍",
            user_count=3,
            collected_at=1700001000,
        )
        assert insert_reactions(conn, [e]) == 1
        assert insert_reactions(conn, [e]) == 0
    finally:
        conn.close()


def test_insert_reactions_empty_returns_zero(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "t.db")
    try:
        assert insert_reactions(conn, []) == 0
    finally:
        conn.close()


def test_aggregate_reactions_by_source(tmp_path: Path) -> None:
    """source slug で SUM(user_count) が集計される."""
    conn = init_db(tmp_path / "t.db")
    try:
        a1 = _setup_article(conn, slug="src_a")
        a2 = _setup_article(conn, slug="src_b")
        insert_reactions(
            conn,
            [
                ReactionEntry(
                    article_id=a1,
                    discord_message_id="M",
                    discord_channel_id="C",
                    emoji="👍",
                    user_count=2,
                    collected_at=1700001000,
                ),
                ReactionEntry(
                    article_id=a1,
                    discord_message_id="M",
                    discord_channel_id="C",
                    emoji="🚀",
                    user_count=5,
                    collected_at=1700001000,
                ),
                ReactionEntry(
                    article_id=a2,
                    discord_message_id="M2",
                    discord_channel_id="C",
                    emoji="👍",
                    user_count=1,
                    collected_at=1700001000,
                ),
            ],
        )
        agg = aggregate_reactions_by_source(conn, since_unix=0)
        assert agg == {"src_a": 7, "src_b": 1}
    finally:
        conn.close()


def test_aggregate_reactions_respects_since_unix(tmp_path: Path) -> None:
    """since_unix より古い行は集計から除外."""
    conn = init_db(tmp_path / "t.db")
    try:
        aid = _setup_article(conn)
        insert_reactions(
            conn,
            [
                ReactionEntry(
                    article_id=aid,
                    discord_message_id="M",
                    discord_channel_id="C",
                    emoji="👍",
                    user_count=4,
                    collected_at=1000,
                ),
                ReactionEntry(
                    article_id=aid,
                    discord_message_id="M",
                    discord_channel_id="C",
                    emoji="🔥",
                    user_count=2,
                    collected_at=2000,
                ),
            ],
        )
        agg = aggregate_reactions_by_source(conn, since_unix=1500)
        assert agg == {"src1": 2}
    finally:
        conn.close()


def test_latest_collected_at_returns_max(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "t.db")
    try:
        aid = _setup_article(conn)
        insert_reactions(
            conn,
            [
                ReactionEntry(
                    article_id=aid,
                    discord_message_id="M",
                    discord_channel_id="C",
                    emoji="👍",
                    user_count=1,
                    collected_at=1000,
                ),
                ReactionEntry(
                    article_id=aid,
                    discord_message_id="M",
                    discord_channel_id="C",
                    emoji="🚀",
                    user_count=1,
                    collected_at=2500,
                ),
            ],
        )
        assert latest_collected_at(conn, article_id=aid) == 2500
    finally:
        conn.close()


def test_latest_collected_at_none_for_unknown(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "t.db")
    try:
        assert latest_collected_at(conn, article_id=999) is None
    finally:
        conn.close()
