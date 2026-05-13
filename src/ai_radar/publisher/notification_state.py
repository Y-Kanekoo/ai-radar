"""通知状態 (article_notifications テーブル) の管理層."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass

from ai_radar.publisher.rss import FeedItem

logger = logging.getLogger("ai_radar.notification_state")

DISCORD_CHANNEL = "discord"  # 旧API互換のデフォルト channel 名 (全カテゴリ統合)


def discord_channel_for_category(category: str | None) -> str:
    """category 別の Discord channel 名を返す (Phase 1).

    None / 空文字なら旧API互換の "discord" を返す.
    例: "release" → "discord_release"
    """
    if not category:
        return DISCORD_CHANNEL
    return f"{DISCORD_CHANNEL}_{category}"


@dataclass(frozen=True)
class UnnotifiedArticle:
    """通知対象記事. article_id を持つ FeedItem ペア + Phase 2 配信判定用メタ."""

    article_id: int
    item: FeedItem
    category: str = ""  # Phase 1 で追加. 既存呼び出し互換のため default 空文字.
    tier: int = 3  # Phase 2: ソースの信頼度 Tier. 配信スコア計算に使用.
    is_hype: bool = False  # Phase 2: ハイプフラグ. Discord embed の ⚠️ 表示に使用.


def fetch_unnotified(
    conn: sqlite3.Connection,
    *,
    channel: str = DISCORD_CHANNEL,
    limit: int = 100,
    since_unix: int | None = None,
    category: str | None = None,
) -> list[UnnotifiedArticle]:
    """指定 channel に未通知の記事を取得する.

    body 列は SELECT しない (47条の5境界).

    Args:
        conn: SQLite 接続.
        channel: 通知チャネル名 (既定 'discord').
        limit: 最大取得件数.
        since_unix: 指定するとこの時刻以降に fetch された記事のみ返す.
        category: 指定するとソース category がこの値に一致する記事のみ返す (Phase 1).

    Returns:
        UnnotifiedArticle のリスト. published_at DESC 順.
    """
    where_extra = ""
    params: list[object] = [channel]
    if since_unix is not None:
        where_extra += "AND a.fetched_at >= ? "
        params.append(since_unix)
    if category is not None:
        where_extra += "AND s.category = ? "
        params.append(category)

    sql = f"""
        SELECT a.id, a.url, a.title, a.snippet, a.author, a.published_at, a.tags_json,
               a.is_hype,
               s.name AS source_name, s.category AS source_category, s.tier AS source_tier
        FROM articles a
        JOIN sources s ON a.source_id = s.id
        WHERE NOT EXISTS (
            SELECT 1 FROM article_notifications n
            WHERE n.article_id = a.id AND n.channel = ?
        )
        {where_extra}
        ORDER BY a.published_at DESC
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    result: list[UnnotifiedArticle] = []
    for r in rows:
        tags = tuple(json.loads(r["tags_json"]) or [])
        item = FeedItem(
            id=r["url"],
            url=r["url"],
            title=r["title"],
            snippet=r["snippet"],
            source_name=r["source_name"],
            author=r["author"],
            published_at=int(r["published_at"]),
            tags=tags,
        )
        result.append(
            UnnotifiedArticle(
                article_id=int(r["id"]),
                item=item,
                category=r["source_category"] or "",
                tier=int(r["source_tier"] or 3),
                is_hype=bool(r["is_hype"]),
            )
        )
    return result


def mark_notified(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    channel: str = DISCORD_CHANNEL,
) -> None:
    """記事を通知済みとしてマークする. 既にマークされていれば何もしない (UNIQUE)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO article_notifications (article_id, channel, notified_at)
        VALUES (?, ?, ?)
        """,
        (article_id, channel, int(time.time())),
    )
    conn.commit()


def mark_notified_bulk(
    conn: sqlite3.Connection,
    article_ids: list[int],
    *,
    channel: str = DISCORD_CHANNEL,
) -> int:
    """複数記事を通知済みとして一括マークする. 実際に挿入された件数を返す."""
    if not article_ids:
        return 0
    now = int(time.time())
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO article_notifications (article_id, channel, notified_at)
        VALUES (?, ?, ?)
        """,
        [(aid, channel, now) for aid in article_ids],
    )
    conn.commit()
    return cur.rowcount or 0
