"""article_notifications の Phase 4a 拡張 (discord_message_id / discord_channel_id)."""

from __future__ import annotations

from pathlib import Path

from ai_radar.crawler.store import ArticleRow, insert_article, upsert_source
from ai_radar.db import init_db
from ai_radar.publisher.notification_state import (
    fetch_notifications_with_message_id,
    mark_notified,
    mark_notified_with_message_id,
)
from ai_radar.sources import FetchPolicy, SourceConfig


def _setup_articles(conn, n: int = 3) -> list[int]:
    src = SourceConfig(
        slug="s",
        name="S",
        feed_url="https://s.example.com/f",
        site_url=None,
        language="en",
        category="release",
        enabled=True,
        fetch_policy=FetchPolicy(min_interval_seconds=0, max_items_per_fetch=10),
        license_note="",
    )
    sid = upsert_source(conn, src)
    aids: list[int] = []
    for i in range(n):
        guid = f"g{i}"
        insert_article(
            conn,
            ArticleRow(
                source_id=sid,
                guid=guid,
                url=f"https://e.com/{guid}",
                title="t",
                snippet="s",
                body_hash=guid,
                body="b",
                author=None,
                published_at=1700000000 + i,
                tags=[],
            ),
        )
        aids.append(
            int(conn.execute("SELECT id FROM articles WHERE guid = ?", (guid,)).fetchone()["id"])
        )
    return aids


def test_mark_notified_with_message_id_inserts_new(tmp_path: Path) -> None:
    """初回挿入で discord_message_id / channel_id が保存される."""
    conn = init_db(tmp_path / "t.db")
    try:
        aids = _setup_articles(conn, n=1)
        mark_notified_with_message_id(
            conn,
            aids[0],
            channel="discord_release",
            discord_message_id="MSG1",
            discord_channel_id="CHAN1",
        )
        row = conn.execute(
            "SELECT discord_message_id, discord_channel_id FROM article_notifications "
            "WHERE article_id = ? AND channel = ?",
            (aids[0], "discord_release"),
        ).fetchone()
        assert row["discord_message_id"] == "MSG1"
        assert row["discord_channel_id"] == "CHAN1"
    finally:
        conn.close()


def test_mark_notified_with_message_id_upsert_overrides_only_when_set(
    tmp_path: Path,
) -> None:
    """同 (article_id, channel) で 2 回呼ぶと message_id は新しい値で上書き、
    None 渡しの場合は既存値を保持 (COALESCE).
    """
    conn = init_db(tmp_path / "t.db")
    try:
        aids = _setup_articles(conn, n=1)
        mark_notified_with_message_id(
            conn,
            aids[0],
            channel="discord_release",
            discord_message_id="MSG1",
            discord_channel_id="CHAN1",
        )
        # 2 回目: None 渡し → 既存値を保持
        mark_notified_with_message_id(
            conn,
            aids[0],
            channel="discord_release",
            discord_message_id=None,
            discord_channel_id=None,
        )
        row = conn.execute(
            "SELECT discord_message_id FROM article_notifications WHERE article_id = ?",
            (aids[0],),
        ).fetchone()
        assert row["discord_message_id"] == "MSG1"

        # 3 回目: 新値 → 上書き
        mark_notified_with_message_id(
            conn,
            aids[0],
            channel="discord_release",
            discord_message_id="MSG2",
            discord_channel_id="CHAN1",
        )
        row = conn.execute(
            "SELECT discord_message_id FROM article_notifications WHERE article_id = ?",
            (aids[0],),
        ).fetchone()
        assert row["discord_message_id"] == "MSG2"
    finally:
        conn.close()


def test_fetch_notifications_with_message_id_filters_null(tmp_path: Path) -> None:
    """discord_message_id が NULL の行は返らない."""
    conn = init_db(tmp_path / "t.db")
    try:
        aids = _setup_articles(conn, n=2)
        # 1 件は message_id 無し (旧来の mark_notified)
        mark_notified(conn, aids[0], channel="discord_release")
        # 1 件は message_id あり
        mark_notified_with_message_id(
            conn,
            aids[1],
            channel="discord_release",
            discord_message_id="MSG2",
            discord_channel_id="CHAN2",
        )
        out = fetch_notifications_with_message_id(conn, since_unix=0)
        ids = [m.article_id for m in out]
        assert aids[1] in ids
        assert aids[0] not in ids
    finally:
        conn.close()


def test_fetch_notifications_with_message_id_respects_since(tmp_path: Path) -> None:
    """since_unix より古い notified_at は返らない."""
    conn = init_db(tmp_path / "t.db")
    try:
        aids = _setup_articles(conn, n=1)
        mark_notified_with_message_id(
            conn,
            aids[0],
            channel="discord_release",
            discord_message_id="MSG1",
            discord_channel_id="CHAN1",
        )
        # notified_at を強引に古い時刻に書き換え
        conn.execute(
            "UPDATE article_notifications SET notified_at = 100 WHERE article_id = ?",
            (aids[0],),
        )
        conn.commit()
        out = fetch_notifications_with_message_id(conn, since_unix=200)
        assert out == []
    finally:
        conn.close()
