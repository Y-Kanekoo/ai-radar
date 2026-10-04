"""SQLite + FTS5 のスキーマ管理と接続オープン.

スキーマは init_db() で冪等に作成される. 重要な設計判断:

- WAL モード: 並列読み取り（クローラー実行中に MCP も同DBを開く想定）
- 外部コンテンツ FTS5 (`content='articles'`): ストレージ二重持ちを避け、トリガで同期
- `tokenize='porter unicode61 remove_diacritics 2'`:
    英語は porter stemming, アクセント記号は除去. 日本語は分かち書きしないが
    タイトル・タグの完全一致検索は機能する.
- `schema_version` テーブル: 将来のマイグレーション用バージョン番号を保持
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 6
# 履歴:
#   v2 (Phase 4): article_notifications テーブルを追加
#   v3 (Phase 1, ai-radar 0.2): articles に normalized_url / thread_id / cluster_id を追加
#                              (dedup 5層化と引用元/時系列クラスタリング)
#   v4 (Phase 2, ai-radar 0.2): articles に is_hype, sources に tier を追加
#   v5 (Phase 3, ai-radar 0.3): benchmark_snapshots テーブルを追加
#                              (LMArena / MTEB / GitHub Trending の snapshot + diff)
#   v6 (Phase 4a, ai-radar 0.3): article_notifications に
#                                 discord_message_id / discord_channel_id を追加.
#                                 reactions テーブルを新規追加 (Discord Bot 経由のリアクション集計用).

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    feed_url TEXT NOT NULL,
    site_url TEXT,
    language TEXT NOT NULL,
    category TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fetched_at INTEGER,
    last_etag TEXT,
    last_modified TEXT,
    consecutive_errors INTEGER DEFAULT 0,
    -- v4 (Phase 2): 信頼度 Tier 1-5 (1=公式, 5=SNS). yaml の値を upsert 時に書く.
    tier INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    guid TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    snippet TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    body TEXT,
    author TEXT,
    published_at INTEGER NOT NULL,
    fetched_at INTEGER NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    -- v3 (Phase 1): dedup 5層 + クラスタリング用カラム
    normalized_url TEXT,
    thread_id INTEGER,
    cluster_id INTEGER,
    -- v4 (Phase 2): ハイプフィルタ警告フラグ. Tier 4-5 + hype_keywords ヒットで 1.
    is_hype INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_id, guid)
);

CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_body_hash ON articles(body_hash);
CREATE INDEX IF NOT EXISTS idx_articles_normalized_url ON articles(normalized_url);
CREATE INDEX IF NOT EXISTS idx_articles_thread_id ON articles(thread_id);
CREATE INDEX IF NOT EXISTS idx_articles_cluster_id ON articles(cluster_id);

-- 外部コンテンツ FTS5: 列名は articles テーブルの列名と完全一致させる必要がある.
-- (FTS5 が articles テーブルから直接列を読み取るため)
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title, body, tags_json,
    content='articles', content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
  INSERT INTO articles_fts(rowid, title, body, tags_json)
  VALUES (new.id, new.title, COALESCE(new.body, ''), new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, body, tags_json)
  VALUES('delete', old.id, old.title, COALESCE(old.body, ''), old.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
  INSERT INTO articles_fts(articles_fts, rowid, title, body, tags_json)
  VALUES('delete', old.id, old.title, COALESCE(old.body, ''), old.tags_json);
  INSERT INTO articles_fts(rowid, title, body, tags_json)
  VALUES (new.id, new.title, COALESCE(new.body, ''), new.tags_json);
END;

CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    sources_processed INTEGER DEFAULT 0,
    articles_added INTEGER DEFAULT 0,
    errors_json TEXT
);

-- v2 (Phase 4): 記事通知状態. channel ごとに既送信を追跡する.
-- v6 (Phase 4a): discord_message_id / discord_channel_id を追加.
--                webhook の ?wait=true 応答から取得した実 message_id を保存し、
--                Bot API でリアクションを引くキーとして使う.
CREATE TABLE IF NOT EXISTS article_notifications (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    channel TEXT NOT NULL,
    notified_at INTEGER NOT NULL,
    discord_message_id TEXT,
    discord_channel_id TEXT,
    UNIQUE(article_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_notifications_channel ON article_notifications(channel);
CREATE INDEX IF NOT EXISTS idx_notifications_article ON article_notifications(article_id);
CREATE INDEX IF NOT EXISTS idx_notifications_discord_msg
    ON article_notifications(discord_message_id);

-- v5 (Phase 3): ベンチマーク / Trending の snapshot.
-- entries_json は ``[{"rank": int, "identifier": str, "score": float|None,
-- "payload": {...}}, ...]`` の JSON. 直前 snapshot との diff は呼び出し側で計算する.
CREATE TABLE IF NOT EXISTS benchmark_snapshots (
    id INTEGER PRIMARY KEY,
    source_slug TEXT NOT NULL,
    category TEXT NOT NULL,
    captured_at INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    entries_json TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_slug, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_bench_source_time
    ON benchmark_snapshots(source_slug, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_bench_notified
    ON benchmark_snapshots(notified, captured_at DESC);

-- v6 (Phase 4a): Discord Bot 経由のリアクション集計.
-- collected_at は collector が走った時刻. user_count は Discord API から取得した
-- 「現時点でその絵文字をつけたユーザー数」(含む Bot). 時系列で増減を追える.
CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id),
    discord_message_id TEXT NOT NULL,
    discord_channel_id TEXT NOT NULL,
    emoji TEXT NOT NULL,
    user_count INTEGER NOT NULL,
    collected_at INTEGER NOT NULL,
    UNIQUE(article_id, emoji, collected_at)
);
CREATE INDEX IF NOT EXISTS idx_reactions_article ON reactions(article_id);
CREATE INDEX IF NOT EXISTS idx_reactions_message ON reactions(discord_message_id);
CREATE INDEX IF NOT EXISTS idx_reactions_emoji ON reactions(emoji);
"""


def init_db(path: Path) -> sqlite3.Connection:
    """DBファイルを開きスキーマを冪等に適用する.

    親ディレクトリが無ければ作成する. WAL モードで開く.

    Args:
        path: DBファイルのパス. 通常 `data/articles.db`.

    Returns:
        オープンした sqlite3.Connection. 利用後は呼び出し側で `close()` する.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        initialize_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """開いた接続へ共通のスキーマ初期化・migration を適用する.

    ファイル DB と dry-run のメモリコピーで同じ互換性を保つ.
    接続の close は呼び出し側が担当する.
    """
    conn.row_factory = sqlite3.Row

    # 既存 articles に v3 カラムが無い場合は、_SCHEMA_SQL の CREATE INDEX が落ちる前に
    # ALTER TABLE で列追加しておく (新規 DB ではテーブル自体が無いので skip).
    _premigrate_columns_if_needed(conn)

    conn.executescript(_SCHEMA_SQL)

    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    elif row["version"] < SCHEMA_VERSION:
        _migrate(conn, from_version=row["version"])
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        conn.commit()
    elif row["version"] > SCHEMA_VERSION:
        raise RuntimeError(
            f"スキーマバージョン不一致: DB={row['version']} > コード={SCHEMA_VERSION}. "
            "より新しいコードでDBが作られている可能性があります."
        )


def _premigrate_columns_if_needed(conn: sqlite3.Connection) -> None:
    """既存 articles / sources に v3-v4 カラムが欠けていれば ALTER TABLE で追加する.

    ``_SCHEMA_SQL`` を実行する前に呼ぶ. 新規 DB の場合 articles テーブル自体が
    存在しないのでスキップする (テーブルは ``_SCHEMA_SQL`` の CREATE TABLE で
    最新スキーマを含む状態で作成される).
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='articles'"
    ).fetchone()
    if row is None:
        return  # 新規 DB
    altered = False
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(articles)")}
    if "normalized_url" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN normalized_url TEXT")
        altered = True
    if "thread_id" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN thread_id INTEGER")
        altered = True
    if "cluster_id" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN cluster_id INTEGER")
        altered = True
    # v4 (Phase 2): is_hype カラム
    if "is_hype" not in cols:
        conn.execute("ALTER TABLE articles ADD COLUMN is_hype INTEGER NOT NULL DEFAULT 0")
        altered = True
    # v4 (Phase 2): sources.tier カラム
    src_cols = {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
    if "tier" not in src_cols:
        conn.execute("ALTER TABLE sources ADD COLUMN tier INTEGER NOT NULL DEFAULT 3")
        altered = True
    # v6 (Phase 4a): article_notifications に discord_message_id / discord_channel_id
    n_row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='article_notifications'"
    ).fetchone()
    if n_row is not None:
        n_cols = {r["name"] for r in conn.execute("PRAGMA table_info(article_notifications)")}
        if "discord_message_id" not in n_cols:
            conn.execute("ALTER TABLE article_notifications ADD COLUMN discord_message_id TEXT")
            altered = True
        if "discord_channel_id" not in n_cols:
            conn.execute("ALTER TABLE article_notifications ADD COLUMN discord_channel_id TEXT")
            altered = True
    if altered:
        conn.commit()


def _migrate(conn: sqlite3.Connection, *, from_version: int) -> None:
    """既存DBを最新スキーマに前方マイグレーションする.

    新規テーブルは CREATE TABLE IF NOT EXISTS で既に作成済みなので、ここでは
    カラム追加など ALTER TABLE が必要な変更だけを扱う.
    """
    if from_version < 3:
        # v2 → v3 (Phase 1): articles に dedup 用 3 カラムを追加.
        # SQLite の ADD COLUMN には IF NOT EXISTS が無いので、既存列を PRAGMA で確認する.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
        if "normalized_url" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN normalized_url TEXT")
        if "thread_id" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN thread_id INTEGER")
        if "cluster_id" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN cluster_id INTEGER")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_normalized_url ON articles(normalized_url)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_thread_id ON articles(thread_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_cluster_id ON articles(cluster_id)")
    if from_version < 4:
        # v3 → v4 (Phase 2): articles.is_hype + sources.tier. _premigrate で既に ALTER 済み
        # かもしれないので PRAGMA で確認してから.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
        if "is_hype" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN is_hype INTEGER NOT NULL DEFAULT 0")
        src_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
        if "tier" not in src_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN tier INTEGER NOT NULL DEFAULT 3")
    if from_version < 5:
        # v4 → v5 (Phase 3): benchmark_snapshots テーブル.
        # `_SCHEMA_SQL` の CREATE TABLE IF NOT EXISTS で既に作成済み. 何もしない.
        pass
    if from_version < 6:
        # v5 → v6 (Phase 4a): article_notifications に列追加 + reactions テーブル.
        # 列追加は _premigrate でも実行されるが、念のため PRAGMA 確認.
        n_cols = {row["name"] for row in conn.execute("PRAGMA table_info(article_notifications)")}
        if "discord_message_id" not in n_cols:
            conn.execute("ALTER TABLE article_notifications ADD COLUMN discord_message_id TEXT")
        if "discord_channel_id" not in n_cols:
            conn.execute("ALTER TABLE article_notifications ADD COLUMN discord_channel_id TEXT")
        # reactions テーブルは _SCHEMA_SQL の CREATE TABLE IF NOT EXISTS で生成済み.
        # index も同じく.
