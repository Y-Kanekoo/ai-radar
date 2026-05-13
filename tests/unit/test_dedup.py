"""dedup.py のユニットテスト (Phase 0 + Phase 1 5層)."""

from __future__ import annotations

from pathlib import Path

from ai_radar.crawler.dedup import (
    find_cluster_id,
    find_cross_source_duplicate,
    find_similar_title,
    find_thread_id,
    is_cross_source_duplicate,
    is_known,
    is_known_by_normalized_url,
    next_cluster_id,
    next_thread_id,
)
from ai_radar.crawler.store import ArticleRow, insert_article, upsert_source
from ai_radar.db import init_db
from ai_radar.sources import FetchPolicy, SourceConfig


def _make_source(slug: str = "test") -> SourceConfig:
    return SourceConfig(
        slug=slug,
        name="Test",
        feed_url="https://example.com/feed",
        site_url=None,
        language="en",
        category="blog",
        enabled=True,
        fetch_policy=FetchPolicy(min_interval_seconds=3600, max_items_per_fetch=30),
        license_note="",
    )


def _make_article(
    source_id: int,
    guid: str = "g1",
    body_hash: str = "h1",
    *,
    title: str = "t",
    url: str = "https://example.com/a",
    published_at: int = 1700000000,
    normalized_url: str | None = None,
    thread_id: int | None = None,
    cluster_id: int | None = None,
) -> ArticleRow:
    return ArticleRow(
        source_id=source_id,
        guid=guid,
        url=url,
        title=title,
        snippet="s",
        body_hash=body_hash,
        body="b",
        author=None,
        published_at=published_at,
        normalized_url=normalized_url,
        thread_id=thread_id,
        cluster_id=cluster_id,
    )


def test_is_known_false_for_new(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        assert is_known(conn, sid, "g1") is False
    finally:
        conn.close()


def test_is_known_true_after_insert(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(conn, _make_article(sid, "g1"))
        assert is_known(conn, sid, "g1") is True
    finally:
        conn.close()


def test_double_insert_returns_false(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        assert insert_article(conn, _make_article(sid, "g1")) is True
        assert insert_article(conn, _make_article(sid, "g1")) is False
    finally:
        conn.close()


def test_cross_source_duplicate_detection(tmp_path: Path) -> None:
    """同じ body_hash の記事が異なるソースに存在することを検出."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid1 = upsert_source(conn, _make_source("s1"))
        sid2 = upsert_source(conn, _make_source("s2"))
        insert_article(conn, _make_article(sid1, "g1", body_hash="same_hash"))
        # s2 から見て、別ソース s1 に同じ body_hash があれば True
        assert is_cross_source_duplicate(conn, "same_hash", sid2) is True
        # s1 から見て、自分以外には存在しない → False
        assert is_cross_source_duplicate(conn, "same_hash", sid1) is False
    finally:
        conn.close()


# ---------------- Phase 1: 層1 URL 正規化マッチ ----------------


def test_is_known_by_normalized_url_returns_none_for_empty(tmp_path: Path) -> None:
    """空 URL は判定スキップで None."""
    conn = init_db(tmp_path / "test.db")
    try:
        assert is_known_by_normalized_url(conn, "") is None
        assert is_known_by_normalized_url(conn, None) is None
    finally:
        conn.close()


def test_is_known_by_normalized_url_returns_id(tmp_path: Path) -> None:
    """同 normalized_url の記事があれば id を返す."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(
            conn,
            _make_article(sid, "g1", normalized_url="https://example.com/x"),
        )
        row = conn.execute("SELECT id FROM articles").fetchone()
        article_id = int(row["id"])
        assert is_known_by_normalized_url(conn, "https://example.com/x") == article_id
        # 違う URL なら None
        assert is_known_by_normalized_url(conn, "https://example.com/y") is None
    finally:
        conn.close()


# ---------------- Phase 1: 層2 タイトル類似度 ----------------


def test_find_similar_title_exact_match(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(
            conn,
            _make_article(sid, "g1", title="Claude Opus 4.7 released", published_at=1700000000),
        )
        article_id = int(conn.execute("SELECT id FROM articles").fetchone()["id"])
        assert find_similar_title(conn, "Claude Opus 4.7 released", 1700000000) == article_id
    finally:
        conn.close()


def test_find_similar_title_high_similarity(tmp_path: Path) -> None:
    """類似度 >= 0.85 ならマッチする."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(
            conn,
            _make_article(
                sid,
                "g1",
                title="Introducing Claude Opus 4.7 - Anthropic announces",
                published_at=1700000000,
            ),
        )
        # 1 単語違いだが全体類似度 >= 0.85 のはず
        result = find_similar_title(
            conn,
            "Introducing Claude Opus 4.7 - Anthropic announced",
            1700000000,
        )
        assert result is not None
    finally:
        conn.close()


def test_find_similar_title_low_similarity_no_match(tmp_path: Path) -> None:
    """類似度 < 0.85 ならマッチしない."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(
            conn,
            _make_article(sid, "g1", title="Claude Opus 4.7 released", published_at=1700000000),
        )
        # 全く別の話題
        assert find_similar_title(conn, "OpenAI releases GPT-5.5", 1700000000) is None
    finally:
        conn.close()


def test_find_similar_title_outside_window(tmp_path: Path) -> None:
    """24h 窓外の記事は類似していてもマッチしない."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        # 既存記事は now - 48h
        insert_article(
            conn,
            _make_article(sid, "g1", title="Same title", published_at=1700000000 - 86400 * 2),
        )
        # 探索は now の時点 → 48h 前で window 外
        assert find_similar_title(conn, "Same title", 1700000000) is None
    finally:
        conn.close()


def test_find_similar_title_empty_returns_none(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "test.db")
    try:
        assert find_similar_title(conn, "", 1700000000) is None
    finally:
        conn.close()


# ---------------- Phase 1: 層3 body_hash クロスソース ----------------


def test_find_cross_source_duplicate_returns_id(tmp_path: Path) -> None:
    """find_cross_source_duplicate は match した article_id を返す."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid1 = upsert_source(conn, _make_source("s1"))
        sid2 = upsert_source(conn, _make_source("s2"))
        insert_article(conn, _make_article(sid1, "g1", body_hash="same"))
        article_id = int(conn.execute("SELECT id FROM articles").fetchone()["id"])
        assert find_cross_source_duplicate(conn, "same", sid2) == article_id
        assert find_cross_source_duplicate(conn, "same", sid1) is None  # 自ソースは除外
        assert find_cross_source_duplicate(conn, "", sid2) is None  # 空は skip
    finally:
        conn.close()


# ---------------- Phase 1: 層4 thread_id ----------------


def test_find_thread_id_matches_existing_thread(tmp_path: Path) -> None:
    """24h 窓内で title 類似 >= 0.9 の thread_id を返す."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(
            conn,
            _make_article(
                sid,
                "g1",
                title="GPT-5 launches today",
                published_at=1700000000,
                thread_id=42,
            ),
        )
        # 完全一致なら thread_id 42 を返す
        assert find_thread_id(conn, "GPT-5 launches today", 1700000000) == 42
    finally:
        conn.close()


def test_find_thread_id_skips_articles_without_thread(tmp_path: Path) -> None:
    """thread_id が NULL の記事は thread マッチ対象外."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(
            conn,
            _make_article(
                sid,
                "g1",
                title="Same title",
                published_at=1700000000,
                thread_id=None,
            ),
        )
        assert find_thread_id(conn, "Same title", 1700000000) is None
    finally:
        conn.close()


# ---------------- Phase 1: 層5 cluster_id ----------------


def test_find_cluster_id_lower_threshold_than_thread(tmp_path: Path) -> None:
    """cluster_id (>=0.8) は thread (>=0.9) より緩い類似度でも match する."""
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(
            conn,
            _make_article(
                sid,
                "g1",
                title="Claude Opus 4.7 brings improved coding performance",
                published_at=1700000000,
                cluster_id=99,
            ),
        )
        # 類似度 0.8-0.9 のテキスト (一部単語入れ替え)
        result = find_cluster_id(
            conn,
            "Claude Opus 4.7 delivers improved coding performance",
            1700000000,
        )
        assert result == 99
    finally:
        conn.close()


# ---------------- Phase 1: 採番 ----------------


def test_next_thread_id_starts_at_1(tmp_path: Path) -> None:
    """空 DB なら 1 から."""
    conn = init_db(tmp_path / "test.db")
    try:
        assert next_thread_id(conn) == 1
    finally:
        conn.close()


def test_next_thread_id_increments_max(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(conn, _make_article(sid, "g1", thread_id=5))
        insert_article(conn, _make_article(sid, "g2", thread_id=12))
        assert next_thread_id(conn) == 13
    finally:
        conn.close()


def test_next_cluster_id_increments_max(tmp_path: Path) -> None:
    conn = init_db(tmp_path / "test.db")
    try:
        sid = upsert_source(conn, _make_source())
        insert_article(conn, _make_article(sid, "g1", cluster_id=7))
        assert next_cluster_id(conn) == 8
    finally:
        conn.close()
