"""db.init_db() の冪等性とスキーマ生成."""

from __future__ import annotations

from pathlib import Path

from ai_radar.db import SCHEMA_VERSION, init_db


def test_init_db_creates_all_tables(tmp_path: Path) -> None:
    """sources / articles / crawl_runs / schema_version がすべて生成される."""
    conn = init_db(tmp_path / "test.db")
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {r["name"] for r in rows}
        assert "sources" in names
        assert "articles" in names
        assert "crawl_runs" in names
        assert "schema_version" in names
    finally:
        conn.close()


def test_init_db_creates_fts5_virtual_table(tmp_path: Path) -> None:
    """articles_fts (FTS5 virtual table) が生成される."""
    conn = init_db(tmp_path / "test.db")
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE name='articles_fts'").fetchone()
        assert row is not None
    finally:
        conn.close()


def test_schema_version_recorded(tmp_path: Path) -> None:
    """初回実行で schema_version が SCHEMA_VERSION に設定される."""
    conn = init_db(tmp_path / "test.db")
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == SCHEMA_VERSION
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    """既存DBで init_db を再実行しても問題なく動作する."""
    db_path = tmp_path / "test.db"
    conn1 = init_db(db_path)
    conn1.close()
    conn2 = init_db(db_path)
    try:
        row = conn2.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == SCHEMA_VERSION
    finally:
        conn2.close()


def test_init_db_creates_parent_dir(tmp_path: Path) -> None:
    """親ディレクトリが無くても自動作成される."""
    db_path = tmp_path / "subdir" / "nested" / "test.db"
    assert not db_path.parent.exists()
    conn = init_db(db_path)
    try:
        assert db_path.parent.exists()
    finally:
        conn.close()


def test_articles_fts_trigger_on_insert(tmp_path: Path) -> None:
    """記事を INSERT すると FTS5 にも自動で同期される."""
    conn = init_db(tmp_path / "test.db")
    try:
        conn.execute(
            "INSERT INTO sources (slug, name, feed_url, language, category) "
            "VALUES ('s', 'S', 'https://e.com/feed', 'en', 'blog')"
        )
        conn.execute(
            "INSERT INTO articles (source_id, guid, url, title, snippet, body_hash, "
            "body, published_at, fetched_at) "
            "VALUES (1, 'g1', 'https://e.com/1', 'Hello world', 'snip', 'h', "
            "'Hello world body', 1700000000, 1700000000)"
        )
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM articles_fts WHERE articles_fts MATCH 'hello'"
        ).fetchall()
        assert len(rows) == 1
    finally:
        conn.close()


# ---------------- Phase 1: v3 マイグレーション ----------------


def test_v3_columns_present_in_fresh_db(tmp_path: Path) -> None:
    """新規 DB は articles に Phase 1 の 3 カラムを持つ."""
    conn = init_db(tmp_path / "test.db")
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
        assert "normalized_url" in cols
        assert "thread_id" in cols
        assert "cluster_id" in cols
    finally:
        conn.close()


def test_v3_indices_present_in_fresh_db(tmp_path: Path) -> None:
    """新規 DB に Phase 1 の dedup インデックスがある."""
    conn = init_db(tmp_path / "test.db")
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='articles'"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert "idx_articles_normalized_url" in names
        assert "idx_articles_thread_id" in names
        assert "idx_articles_cluster_id" in names
    finally:
        conn.close()


def test_v2_to_v3_migration_adds_columns(tmp_path: Path) -> None:
    """既存の v2 DB を v3 のコードで開くと ALTER TABLE で 3 カラムが追加される.

    v2 を再現するため、まず v2 のスキーマで articles テーブルを作って
    schema_version=2 を入れ、その後 init_db で v3 に upgrade させる.
    """
    import sqlite3

    db_path = tmp_path / "test.db"

    # v2 相当の articles テーブルを手動で作成 (Phase 0.5 までの状態を再現)
    raw = sqlite3.connect(db_path)
    raw.executescript("""
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            feed_url TEXT NOT NULL, site_url TEXT, language TEXT NOT NULL,
            category TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            last_fetched_at INTEGER, last_etag TEXT, last_modified TEXT,
            consecutive_errors INTEGER DEFAULT 0
        );
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY, guid TEXT NOT NULL,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            url TEXT NOT NULL, title TEXT NOT NULL, snippet TEXT NOT NULL,
            body_hash TEXT NOT NULL, body TEXT, author TEXT,
            published_at INTEGER NOT NULL, fetched_at INTEGER NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            UNIQUE(source_id, guid)
        );
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO schema_version(version) VALUES (2);
    """)
    raw.commit()
    # v2 では 3 カラムが存在しないことを確認
    cols_before = {row[1] for row in raw.execute("PRAGMA table_info(articles)")}
    assert "normalized_url" not in cols_before
    raw.close()

    # init_db で v3 に upgrade される
    conn = init_db(db_path)
    try:
        cols_after = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
        assert "normalized_url" in cols_after
        assert "thread_id" in cols_after
        assert "cluster_id" in cols_after
        # schema_version が最新 (Phase 2 で v4) になっている
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == 4
    finally:
        conn.close()


# ---------------- Phase 2: v4 マイグレーション ----------------


def test_v4_columns_present_in_fresh_db(tmp_path: Path) -> None:
    """新規 DB は v4 カラム (articles.is_hype + sources.tier) を持つ."""
    conn = init_db(tmp_path / "test.db")
    try:
        a_cols = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
        s_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
        assert "is_hype" in a_cols
        assert "tier" in s_cols
    finally:
        conn.close()


def test_v3_to_v4_migration(tmp_path: Path) -> None:
    """v3 既存 DB を v4 のコードで開くと is_hype + tier カラムが追加される."""
    import sqlite3

    db_path = tmp_path / "test.db"

    # v3 相当のスキーマを手動で作成 (Phase 1 までの状態)
    raw = sqlite3.connect(db_path)
    raw.executescript("""
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            feed_url TEXT NOT NULL, site_url TEXT, language TEXT NOT NULL,
            category TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            last_fetched_at INTEGER, last_etag TEXT, last_modified TEXT,
            consecutive_errors INTEGER DEFAULT 0
        );
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY, guid TEXT NOT NULL,
            source_id INTEGER NOT NULL REFERENCES sources(id),
            url TEXT NOT NULL, title TEXT NOT NULL, snippet TEXT NOT NULL,
            body_hash TEXT NOT NULL, body TEXT, author TEXT,
            published_at INTEGER NOT NULL, fetched_at INTEGER NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            normalized_url TEXT, thread_id INTEGER, cluster_id INTEGER,
            UNIQUE(source_id, guid)
        );
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO schema_version(version) VALUES (3);
    """)
    raw.commit()
    raw.close()

    # init_db で v4 に upgrade
    conn = init_db(db_path)
    try:
        a_cols = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
        s_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
        assert "is_hype" in a_cols
        assert "tier" in s_cols
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == 4
    finally:
        conn.close()


def test_v2_to_v3_migration_is_idempotent(tmp_path: Path) -> None:
    """v2→v3 migration を 2 回呼んでも (ALTER TABLE 重複で) エラーにならない."""
    db_path = tmp_path / "test.db"

    # 1 回目 (v2 → v3)
    conn1 = init_db(db_path)
    conn1.execute("UPDATE schema_version SET version = 2")
    conn1.commit()
    conn1.close()

    # 2 回目: 既に v3 カラムが存在するが、PRAGMA でチェックして skip するはず
    conn2 = init_db(db_path)
    try:
        row = conn2.execute("SELECT version FROM schema_version").fetchone()
        # 最新スキーマへ更新される (Phase 2 で v4)
        assert row["version"] == 4
    finally:
        conn2.close()
