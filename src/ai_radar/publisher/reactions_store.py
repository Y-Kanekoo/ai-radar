"""reactions テーブルの I/O (Phase 4a).

``collect_reactions.py`` から呼ばれる薄い DAL. UNIQUE(article_id, emoji, collected_at)
で重複を防ぐ. ``collected_at`` を日単位で丸めると同日の重複が UNIQUE で弾かれて
気持ち良いが、API rate limit の関係で日内に複数回 cron を回すこともあり得るので
ここでは raw unix を保存し、集計側で必要なら DISTINCT する.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

logger = logging.getLogger("ai_radar.reactions_store")


@dataclass(frozen=True)
class ReactionEntry:
    """DB 保存用の 1 行."""

    article_id: int
    discord_message_id: str
    discord_channel_id: str
    emoji: str
    user_count: int
    collected_at: int


def insert_reactions(
    conn: sqlite3.Connection,
    entries: list[ReactionEntry],
) -> int:
    """まとめて INSERT OR IGNORE する. 重複は無視. 挿入件数を返す."""
    if not entries:
        return 0
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO reactions
            (article_id, discord_message_id, discord_channel_id,
             emoji, user_count, collected_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                e.article_id,
                e.discord_message_id,
                e.discord_channel_id,
                e.emoji,
                e.user_count,
                e.collected_at,
            )
            for e in entries
        ],
    )
    conn.commit()
    return cur.rowcount or 0


def aggregate_reactions_by_source(
    conn: sqlite3.Connection,
    *,
    since_unix: int,
) -> dict[str, int]:
    """``since_unix`` 以降のリアクションを source slug ごとに合計する.

    user_interest 計算の元データになる. emoji 別の重み付けはここではせず、
    単純合計を返す (呼び出し側で正/負分別する余地を残す).
    """
    rows = conn.execute(
        """
        SELECT s.slug AS slug, SUM(r.user_count) AS total
        FROM reactions r
        JOIN articles a ON r.article_id = a.id
        JOIN sources s ON a.source_id = s.id
        WHERE r.collected_at >= ?
        GROUP BY s.slug
        """,
        (since_unix,),
    ).fetchall()
    return {str(r["slug"]): int(r["total"] or 0) for r in rows}


def latest_collected_at(
    conn: sqlite3.Connection,
    *,
    article_id: int,
) -> int | None:
    """記事の最新 collected_at. 直前収集との diff を見るのに使う (Phase 4.5 用)."""
    row = conn.execute(
        "SELECT MAX(collected_at) AS m FROM reactions WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    if row is None:
        return None
    m = row["m"]
    return int(m) if m is not None else None
