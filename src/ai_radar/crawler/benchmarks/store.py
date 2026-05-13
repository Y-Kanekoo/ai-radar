"""benchmark snapshot の DB I/O (Phase 3).

保存と取得を分離して `track_benchmarks.py` から呼ぶ. JSON のシリアライズも
ここで完結させ、呼び出し側は ``BenchmarkSnapshot`` だけを扱う.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot

logger = logging.getLogger("ai_radar.benchmarks.store")


def serialize_entries(entries: tuple[BenchmarkEntry, ...]) -> str:
    """``BenchmarkEntry`` タプルを JSON 文字列にする (DB 保存用)."""
    return json.dumps(
        [
            {
                "rank": e.rank,
                "identifier": e.identifier,
                "score": e.score,
                "payload": e.payload,
            }
            for e in entries
        ],
        ensure_ascii=False,
        sort_keys=True,
    )


def deserialize_entries(text: str) -> tuple[BenchmarkEntry, ...]:
    """JSON 文字列を ``BenchmarkEntry`` タプルに復元する."""
    data = json.loads(text)
    if not isinstance(data, list):
        return ()
    out: list[BenchmarkEntry] = []
    for d in data:
        if not isinstance(d, dict):
            continue
        try:
            out.append(
                BenchmarkEntry(
                    rank=int(d["rank"]),
                    identifier=str(d["identifier"]),
                    score=None if d.get("score") is None else float(d["score"]),
                    payload=dict(d.get("payload") or {}),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("entry 復元失敗: %s, 値=%r", e, d)
            continue
    return tuple(out)


def save_snapshot(conn: sqlite3.Connection, snapshot: BenchmarkSnapshot) -> int | None:
    """snapshot を保存し、新規 ID を返す.

    同 (source_slug, captured_at) が既に存在する場合は ``None`` を返す
    (UNIQUE 違反は OperationalError でなく IntegrityError なので別途キャッチ).
    """
    try:
        cur = conn.execute(
            """
            INSERT INTO benchmark_snapshots
                (source_slug, category, captured_at, display_name, entries_json, notified)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                snapshot.source_slug,
                snapshot.category,
                snapshot.captured_at,
                snapshot.display_name,
                serialize_entries(snapshot.entries),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as e:
        logger.info(
            "snapshot 既存 source=%s captured_at=%d (%s)",
            snapshot.source_slug,
            snapshot.captured_at,
            e,
        )
        return None


def latest_before(
    conn: sqlite3.Connection,
    *,
    source_slug: str,
    before: int,
) -> BenchmarkSnapshot | None:
    """``captured_at < before`` の最新 snapshot を取得する.

    diff 計算で「直前」の snapshot を引くために使う. None なら初回.
    """
    row = conn.execute(
        """
        SELECT source_slug, category, captured_at, display_name, entries_json
        FROM benchmark_snapshots
        WHERE source_slug = ? AND captured_at < ?
        ORDER BY captured_at DESC
        LIMIT 1
        """,
        (source_slug, before),
    ).fetchone()
    if row is None:
        return None
    return BenchmarkSnapshot(
        source_slug=row["source_slug"],
        category=row["category"],
        captured_at=row["captured_at"],
        entries=deserialize_entries(row["entries_json"]),
        display_name=row["display_name"],
    )


def fetch_unnotified_snapshots(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
) -> list[tuple[int, BenchmarkSnapshot]]:
    """notified=0 の snapshot を ``(row_id, snapshot)`` のリストで返す.

    captured_at 昇順 (古いものから配信する).
    """
    rows = conn.execute(
        """
        SELECT id, source_slug, category, captured_at, display_name, entries_json
        FROM benchmark_snapshots
        WHERE notified = 0
        ORDER BY captured_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out: list[tuple[int, BenchmarkSnapshot]] = []
    for r in rows:
        snap = BenchmarkSnapshot(
            source_slug=r["source_slug"],
            category=r["category"],
            captured_at=r["captured_at"],
            entries=deserialize_entries(r["entries_json"]),
            display_name=r["display_name"],
        )
        out.append((r["id"], snap))
    return out


def mark_snapshot_notified(conn: sqlite3.Connection, snapshot_id: int) -> None:
    """``notified=1`` をセット. 重複配信を防ぐ."""
    conn.execute(
        "UPDATE benchmark_snapshots SET notified = 1 WHERE id = ?",
        (snapshot_id,),
    )
    conn.commit()
