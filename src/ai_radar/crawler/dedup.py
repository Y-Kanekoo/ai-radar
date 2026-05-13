"""重複検出層 (Phase 1: 5層 + クラスタリング).

dedup 5層:
  - 層1: ``is_known_by_normalized_url`` — URL 正規化後の完全一致
  - 層2: ``find_similar_title``       — title Levenshtein 類似度 >= 0.85
  - 層3: ``find_cross_source_duplicate`` — body_hash の完全一致 (別ソース)
  - 層4: ``find_thread_id``           — 24h 窓 + title 類似 >= 0.9 で同 thread に統合
  - 層5: ``find_cluster_id``          — 24h 窓 + title 類似 >= 0.8 で同 cluster に統合

層1〜3 は重複判定 (orchestrator が skip 判断に使う). 層4〜5 はクラスタ ID 割り当てで
新規挿入を妨げない. thread/cluster の採番は ``next_thread_id`` / ``next_cluster_id``.

class:`difflib.SequenceMatcher` の ``ratio()`` を Levenshtein 近似として使う. 標準
ライブラリのみで完結し、追加依存は無い. 24h 窓内のクエリ + 200 件上限なので、ピーク
クロール時でも各記事あたり数 ms に収まる.
"""

from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher

# Phase 1 のデフォルト値. 実装プランの threshold をそのまま採用.
DEFAULT_WINDOW_SECONDS = 86400  # 24h
TITLE_SIMILARITY_DEDUP = 0.85  # 層2: 重複判定
TITLE_SIMILARITY_THREAD = 0.90  # 層4: 引用元クラスタ
TITLE_SIMILARITY_CLUSTER = 0.80  # 層5: 時系列クラスタ
_LOOKUP_LIMIT = 200


def is_known(conn: sqlite3.Connection, source_id: int, guid: str) -> bool:
    """同一 (source_id, guid) が既にDBに存在するか (旧API、Phase 0 から).

    UNIQUE 制約に依存するため insert_article() の IntegrityError も同等の保護を
    持つが、こちらは insert 前に判定して無駄なクエリを避けたい場合に使う.
    """
    cur = conn.execute(
        "SELECT 1 FROM articles WHERE source_id = ? AND guid = ? LIMIT 1",
        (source_id, guid),
    )
    return cur.fetchone() is not None


# ---------------- 層1: URL 正規化マッチ ----------------


def is_known_by_normalized_url(conn: sqlite3.Connection, normalized_url: str | None) -> int | None:
    """同一 normalized_url の既存記事の id を返す. 無ければ None.

    normalized_url が空・None なら判定をスキップして None.
    """
    if not normalized_url:
        return None
    row = conn.execute(
        "SELECT id FROM articles WHERE normalized_url = ? LIMIT 1",
        (normalized_url,),
    ).fetchone()
    return int(row["id"]) if row else None


# ---------------- 層2: タイトル類似度 ----------------


def find_similar_title(
    conn: sqlite3.Connection,
    title: str,
    published_at: int,
    *,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    similarity: float = TITLE_SIMILARITY_DEDUP,
) -> int | None:
    """24h 窓内で title 類似度 >= ``similarity`` の既存記事の id を返す.

    SequenceMatcher で部分一致による類似度を計算する. 完全一致を含むので
    実質的な強い重複検出. 大文字小文字は ratio 前に lower() で揃える.

    Args:
        title: 比較対象のタイトル.
        published_at: 比較対象の公開時刻 (UNIX 秒).
        window_seconds: 比較窓のサイズ (前後それぞれ).
        similarity: 類似度しきい値 (0.0〜1.0).

    Returns:
        マッチした既存記事の id. 無ければ None.
    """
    if not title:
        return None
    rows = conn.execute(
        """
        SELECT id, title FROM articles
        WHERE published_at BETWEEN ? AND ?
        ORDER BY published_at DESC
        LIMIT ?
        """,
        (published_at - window_seconds, published_at + window_seconds, _LOOKUP_LIMIT),
    ).fetchall()
    title_lc = title.lower()
    for row in rows:
        ratio = SequenceMatcher(None, title_lc, row["title"].lower()).ratio()
        if ratio >= similarity:
            return int(row["id"])
    return None


# ---------------- 層3: body_hash クロスソース重複 ----------------


def find_cross_source_duplicate(
    conn: sqlite3.Connection, body_hash: str, source_id: int
) -> int | None:
    """別ソースに同一 body_hash の記事があれば id を返す (層3).

    body_hash が空・None なら None.
    """
    if not body_hash:
        return None
    row = conn.execute(
        "SELECT id FROM articles WHERE body_hash = ? AND source_id != ? LIMIT 1",
        (body_hash, source_id),
    ).fetchone()
    return int(row["id"]) if row else None


def is_cross_source_duplicate(conn: sqlite3.Connection, body_hash: str, source_id: int) -> bool:
    """``find_cross_source_duplicate`` の bool ラッパ (Phase 0 API 互換)."""
    return find_cross_source_duplicate(conn, body_hash, source_id) is not None


# ---------------- 層4: 引用元クラスタリング (thread_id) ----------------


def find_thread_id(
    conn: sqlite3.Connection,
    title: str,
    published_at: int,
    *,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    similarity: float = TITLE_SIMILARITY_THREAD,
) -> int | None:
    """24h 窓内で title 類似 >= 0.9 の既存記事の thread_id を返す.

    引用元クラスタリング: 同じイベントを別ソースが取り上げると同じ thread にまとまる.
    thread_id を持たない既存記事はスキップする (まだクラスタリング前の Phase 0 記事
    を巻き込まないため).

    Returns:
        既存 thread_id. 無ければ None (orchestrator 側で新規採番).
    """
    if not title:
        return None
    rows = conn.execute(
        """
        SELECT thread_id, title FROM articles
        WHERE published_at BETWEEN ? AND ?
          AND thread_id IS NOT NULL
        ORDER BY published_at DESC
        LIMIT ?
        """,
        (published_at - window_seconds, published_at + window_seconds, _LOOKUP_LIMIT),
    ).fetchall()
    title_lc = title.lower()
    for row in rows:
        ratio = SequenceMatcher(None, title_lc, row["title"].lower()).ratio()
        if ratio >= similarity:
            return int(row["thread_id"])
    return None


# ---------------- 層5: 時系列クラスタリング (cluster_id) ----------------


def find_cluster_id(
    conn: sqlite3.Connection,
    title: str,
    published_at: int,
    *,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    similarity: float = TITLE_SIMILARITY_CLUSTER,
) -> int | None:
    """24h 窓内で title 類似 >= 0.8 の既存記事の cluster_id を返す.

    時系列クラスタリング: 似たトピックが連発したときに 1 クラスタにまとめる.
    層4 より緩い閾値 (0.8) なので、引用元クラスタの上位概念として機能する.

    Returns:
        既存 cluster_id. 無ければ None (orchestrator 側で新規採番).
    """
    if not title:
        return None
    rows = conn.execute(
        """
        SELECT cluster_id, title FROM articles
        WHERE published_at BETWEEN ? AND ?
          AND cluster_id IS NOT NULL
        ORDER BY published_at DESC
        LIMIT ?
        """,
        (published_at - window_seconds, published_at + window_seconds, _LOOKUP_LIMIT),
    ).fetchall()
    title_lc = title.lower()
    for row in rows:
        ratio = SequenceMatcher(None, title_lc, row["title"].lower()).ratio()
        if ratio >= similarity:
            return int(row["cluster_id"])
    return None


# ---------------- thread_id / cluster_id 採番 ----------------


def next_thread_id(conn: sqlite3.Connection) -> int:
    """新しい thread_id を採番する (MAX+1).

    並行クロール時の衝突は SQLite の単一 connection 前提で問題になりにくいが、
    multi-process でクロールする場合は別のロック戦略が必要 (将来課題).
    """
    row = conn.execute("SELECT COALESCE(MAX(thread_id), 0) AS m FROM articles").fetchone()
    return int(row["m"]) + 1


def next_cluster_id(conn: sqlite3.Connection) -> int:
    """新しい cluster_id を採番する (MAX+1)."""
    row = conn.execute("SELECT COALESCE(MAX(cluster_id), 0) AS m FROM articles").fetchone()
    return int(row["m"]) + 1
