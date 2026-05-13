"""benchmark store の DB I/O (Phase 3)."""

from __future__ import annotations

from pathlib import Path

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot
from ai_radar.crawler.benchmarks.store import (
    deserialize_entries,
    fetch_unnotified_snapshots,
    latest_before,
    mark_snapshot_notified,
    save_snapshot,
    serialize_entries,
)
from ai_radar.db import init_db


def _make_snap(slug: str = "lmarena_text", at: int = 1700000000) -> BenchmarkSnapshot:
    return BenchmarkSnapshot(
        source_slug=slug,
        category="benchmark",
        captured_at=at,
        entries=(
            BenchmarkEntry(rank=1, identifier="A", score=1300.0, payload={"organization": "X"}),
            BenchmarkEntry(rank=2, identifier="B", score=1280.5, payload={}),
        ),
        display_name="Test",
    )


def test_serialize_and_deserialize_roundtrip() -> None:
    """entries は JSON 経由でロスレスにラウンドトリップする."""
    entries = (
        BenchmarkEntry(rank=1, identifier="A", score=1.0, payload={"x": "y"}),
        BenchmarkEntry(rank=2, identifier="日本語", score=None, payload={}),
    )
    text = serialize_entries(entries)
    out = deserialize_entries(text)
    assert out == entries


def test_serialize_preserves_unicode() -> None:
    """ensure_ascii=False で日本語 identifier が壊れない."""
    text = serialize_entries((BenchmarkEntry(rank=1, identifier="日本語", score=None, payload={}),))
    assert "日本語" in text


def test_save_snapshot_inserts_row(tmp_path: Path) -> None:
    """save_snapshot で 1 行 INSERT され ID が返る."""
    conn = init_db(tmp_path / "t.db")
    try:
        row_id = save_snapshot(conn, _make_snap())
        assert isinstance(row_id, int) and row_id > 0
        row = conn.execute(
            "SELECT source_slug, category, captured_at, display_name, entries_json, notified "
            "FROM benchmark_snapshots WHERE id = ?",
            (row_id,),
        ).fetchone()
        assert row["source_slug"] == "lmarena_text"
        assert row["category"] == "benchmark"
        assert row["captured_at"] == 1700000000
        assert row["notified"] == 0
        # entries_json が復元可能
        out = deserialize_entries(row["entries_json"])
        assert out[0].identifier == "A"
    finally:
        conn.close()


def test_save_snapshot_duplicate_returns_none(tmp_path: Path) -> None:
    """同 (slug, captured_at) を 2 回 save すると 2 回目は None."""
    conn = init_db(tmp_path / "t.db")
    try:
        a = save_snapshot(conn, _make_snap())
        b = save_snapshot(conn, _make_snap())
        assert a is not None
        assert b is None
    finally:
        conn.close()


def test_latest_before_returns_most_recent_earlier(tmp_path: Path) -> None:
    """latest_before は captured_at < before の最新を返す."""
    conn = init_db(tmp_path / "t.db")
    try:
        save_snapshot(conn, _make_snap(at=100))
        save_snapshot(conn, _make_snap(at=200))
        save_snapshot(conn, _make_snap(at=300))
        prev = latest_before(conn, source_slug="lmarena_text", before=250)
        assert prev is not None
        assert prev.captured_at == 200
    finally:
        conn.close()


def test_latest_before_returns_none_when_empty(tmp_path: Path) -> None:
    """同 slug の snapshot が無いとき None."""
    conn = init_db(tmp_path / "t.db")
    try:
        save_snapshot(conn, _make_snap(slug="other", at=100))
        prev = latest_before(conn, source_slug="lmarena_text", before=200)
        assert prev is None
    finally:
        conn.close()


def test_fetch_unnotified_returns_notified_zero_only(tmp_path: Path) -> None:
    """notified=0 のみ返す."""
    conn = init_db(tmp_path / "t.db")
    try:
        a = save_snapshot(conn, _make_snap(at=100))
        b = save_snapshot(conn, _make_snap(at=200))
        assert a is not None and b is not None
        mark_snapshot_notified(conn, a)
        rows = fetch_unnotified_snapshots(conn)
        ids = [rid for rid, _ in rows]
        assert a not in ids
        assert b in ids
    finally:
        conn.close()


def test_mark_snapshot_notified_sets_flag(tmp_path: Path) -> None:
    """mark_snapshot_notified で notified=1 になる."""
    conn = init_db(tmp_path / "t.db")
    try:
        row_id = save_snapshot(conn, _make_snap())
        assert row_id is not None
        mark_snapshot_notified(conn, row_id)
        row = conn.execute(
            "SELECT notified FROM benchmark_snapshots WHERE id = ?", (row_id,)
        ).fetchone()
        assert row["notified"] == 1
    finally:
        conn.close()
