"""scoring.user_interest_for の Phase 4a no-op 動作と DB 統合."""

from __future__ import annotations

from pathlib import Path

from ai_radar.crawler.scoring import (
    USER_INTEREST_DEFAULT,
    compute_score,
    should_deliver,
    user_interest_for,
)
from ai_radar.crawler.store import ArticleRow, insert_article, upsert_source
from ai_radar.db import init_db
from ai_radar.publisher.reactions_store import ReactionEntry, insert_reactions
from ai_radar.sources import FetchPolicy, SourceConfig


def test_user_interest_for_none_conn_returns_default() -> None:
    """conn=None なら DB アクセスせず default."""
    assert user_interest_for("any_slug", None) == USER_INTEREST_DEFAULT


def test_user_interest_for_empty_db_returns_default(tmp_path: Path) -> None:
    """DB に reactions が無いなら default."""
    conn = init_db(tmp_path / "t.db")
    try:
        assert user_interest_for("nonexistent", conn) == USER_INTEREST_DEFAULT
    finally:
        conn.close()


def test_user_interest_for_with_reactions_still_default(tmp_path: Path) -> None:
    """Phase 4a 時点: reactions が貯まっても返り値は default 1.0 (no-op).

    Phase 4.5 で Bayesian posterior に切替予定. 現状は単純な「データ取得経路」の確認.
    """
    conn = init_db(tmp_path / "t.db")
    try:
        src = SourceConfig(
            slug="popular",
            name="Popular",
            feed_url="https://p.example.com/f",
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
                guid="g",
                url="https://e.com/g",
                title="t",
                snippet="s",
                body_hash="h",
                body="b",
                author=None,
                published_at=1700000000,
                tags=[],
            ),
        )
        aid = int(conn.execute("SELECT id FROM articles WHERE guid='g'").fetchone()["id"])
        insert_reactions(
            conn,
            [
                ReactionEntry(
                    article_id=aid,
                    discord_message_id="M",
                    discord_channel_id="C",
                    emoji="👍",
                    user_count=10,
                    collected_at=1700001000,
                ),
            ],
        )
        v = user_interest_for("popular", conn, now=1700001100)
        assert v == USER_INTEREST_DEFAULT
    finally:
        conn.close()


def test_compute_score_accepts_user_interest_factor() -> None:
    """user_interest がスコアを乗算する (既存の Phase 2 動作確認)."""
    base = compute_score(tier=1, category="release", age_seconds=0, user_interest=1.0)
    boosted = compute_score(tier=1, category="release", age_seconds=0, user_interest=2.0)
    assert boosted == base * 2.0


def test_should_deliver_uses_user_interest_factor() -> None:
    """user_interest を上げると配信閾値を超えるケース."""
    # tier=5 (0.3) × release decay × user_interest. age=0 で decay=1.0.
    # user_interest=1.0 → score=0.3 < 0.5 → False
    assert (
        should_deliver(tier=5, category="release", published_at=0, now=0, user_interest=1.0)
        is False
    )
    # user_interest=2.0 → score=0.6 > 0.5 → True
    assert (
        should_deliver(tier=5, category="release", published_at=0, now=0, user_interest=2.0) is True
    )
