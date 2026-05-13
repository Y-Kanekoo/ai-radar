"""scripts/track_benchmarks.py の Discord 配信 dispatch 整合性 (Phase 3).

特に Bug A (webhook 未設定 category の filtering で row_id が誤って mark される)
と Bug B (中間失敗で残り item が未通知のまま残る) を直接検証する.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import pytest

import scripts.track_benchmarks as tb
from ai_radar.crawler.benchmarks import (
    _REGISTRY,
    BenchmarkEntry,
    BenchmarkSnapshot,
    register,
)
from ai_radar.db import init_db


def _make_snap(slug: str, category: str, at: int, ident: str) -> BenchmarkSnapshot:
    return BenchmarkSnapshot(
        source_slug=slug,
        category=category,
        captured_at=at,
        entries=(BenchmarkEntry(rank=1, identifier=ident, score=1.0, payload={}),),
        display_name=slug,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """各テストで隔離した DB."""
    return tmp_path / "track.db"


@pytest.fixture
def fake_fetchers(monkeypatch: pytest.MonkeyPatch) -> dict[str, BenchmarkSnapshot]:
    """2 ソース (benchmark / trend) を登録した状態にする.

    既存登録を上書きしてテスト後に元に戻すため、_REGISTRY を直接いじる.
    """
    saved = dict(_REGISTRY)
    _REGISTRY.clear()

    snap_b = _make_snap("test_bench", "benchmark", 100, "ModelA")
    snap_t = _make_snap("test_trend", "trend", 200, "owner/repo")
    snaps = {"test_bench": snap_b, "test_trend": snap_t}

    async def _b(client: httpx.AsyncClient | None = None) -> BenchmarkSnapshot:
        return snap_b

    async def _t(client: httpx.AsyncClient | None = None) -> BenchmarkSnapshot:
        return snap_t

    register("test_bench")(_b)
    register("test_trend")(_t)
    # `_ensure_fetchers_loaded` が True なら本物 import がスキップされる:
    monkeypatch.setattr(tb, "registered_slugs", lambda: frozenset(_REGISTRY))
    monkeypatch.setattr(tb, "get_fetcher", lambda slug: _REGISTRY.get(slug))

    yield snaps

    _REGISTRY.clear()
    _REGISTRY.update(saved)


def _set_only_benchmark_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """`benchmark` 用 webhook のみセット (trend は未設定にして bug A をトリガ)."""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("AI_RADAR_DISCORD_WEBHOOK_TREND", raising=False)
    monkeypatch.setenv("AI_RADAR_DISCORD_WEBHOOK_BENCHMARK", "https://discord.com/api/webhooks/B/B")


def _stub_send_batch(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[list[tuple[BenchmarkSnapshot, object, str]]], Awaitable[list[bool]]],
) -> None:
    """Discord 配信を差し替える (テスト用)."""
    monkeypatch.setattr(tb, "send_benchmark_batch", handler)


def _row_notified(db_path: Path, slug: str) -> int:
    """slug の最新行の notified 値."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT notified FROM benchmark_snapshots WHERE source_slug=? "
            "ORDER BY captured_at DESC LIMIT 1",
            (slug,),
        ).fetchone()
    finally:
        conn.close()
    return row["notified"] if row else -1


def test_dispatch_does_not_mark_trend_when_only_benchmark_webhook_set(
    db_path: Path,
    fake_fetchers: dict[str, BenchmarkSnapshot],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug A 回帰防止.

    trend 用 webhook 未設定なら、test_trend 行は notified=0 のまま残らなければ
    ならない. test_bench は配信成功で notified=1.
    """
    _set_only_benchmark_webhook(monkeypatch)

    async def _send(items):  # type: ignore[no-untyped-def]
        # この時点で trend は filter で除外されているはず. benchmark 1 件のみ受け取る.
        assert len(items) == 1
        assert items[0][0].source_slug == "test_bench"
        return [True]

    _stub_send_batch(monkeypatch, _send)

    # DB を事前作成して捕捉
    init_db(db_path).close()
    rc = tb.main(["--db-path", str(db_path), "--min-rank-delta", "1"])
    assert rc == 0

    assert _row_notified(db_path, "test_bench") == 1, "benchmark は notified=1"
    assert _row_notified(db_path, "test_trend") == 0, "trend は notified=0 (webhook 未設定)"


def test_dispatch_marks_only_successful_items(
    db_path: Path,
    fake_fetchers: dict[str, BenchmarkSnapshot],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug B 回帰防止.

    benchmark 失敗 + trend 成功なら、benchmark は notified=0 のまま (再配信),
    trend は notified=1 になる.
    """
    monkeypatch.setenv("AI_RADAR_DISCORD_WEBHOOK_BENCHMARK", "https://discord.com/api/webhooks/B/B")
    monkeypatch.setenv("AI_RADAR_DISCORD_WEBHOOK_TREND", "https://discord.com/api/webhooks/T/T")

    async def _send(items):  # type: ignore[no-untyped-def]
        # send_items は sorted(slugs) 順なので test_bench → test_trend
        assert items[0][0].source_slug == "test_bench"
        assert items[1][0].source_slug == "test_trend"
        return [False, True]  # benchmark 失敗、trend 成功

    _stub_send_batch(monkeypatch, _send)

    init_db(db_path).close()
    rc = tb.main(["--db-path", str(db_path), "--min-rank-delta", "1"])
    # failure > 0 なので 2 を返す
    assert rc == 2

    assert _row_notified(db_path, "test_bench") == 0, "失敗した benchmark は notified=0"
    assert _row_notified(db_path, "test_trend") == 1, "成功した trend は notified=1"


def test_dispatch_no_changes_marks_notified_without_sending(
    db_path: Path,
    fake_fetchers: dict[str, BenchmarkSnapshot],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """前回と同一 entries なら配信せず notified=1.

    Bug B 修正版で「変化なし」snapshot の早期 notified が壊れていないか確認.
    """
    monkeypatch.setenv("AI_RADAR_DISCORD_WEBHOOK_BENCHMARK", "https://discord.com/api/webhooks/B/B")
    monkeypatch.setenv("AI_RADAR_DISCORD_WEBHOOK_TREND", "https://discord.com/api/webhooks/T/T")

    # まず 100 で 1 回保存しておく (前回 snapshot)
    conn = init_db(db_path)
    try:
        for _slug, snap in fake_fetchers.items():
            conn.execute(
                "INSERT INTO benchmark_snapshots "
                "(source_slug, category, captured_at, display_name, entries_json, notified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (
                    snap.source_slug,
                    snap.category,
                    snap.captured_at - 1,
                    snap.display_name,
                    json.dumps(
                        [
                            {
                                "rank": e.rank,
                                "identifier": e.identifier,
                                "score": e.score,
                                "payload": e.payload,
                            }
                            for e in snap.entries
                        ]
                    ),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    sent: list[object] = []

    async def _send(items):  # type: ignore[no-untyped-def]
        sent.append(items)
        return [True] * len(items)

    _stub_send_batch(monkeypatch, _send)

    rc = tb.main(["--db-path", str(db_path), "--min-rank-delta", "1"])
    assert rc == 0
    assert sent == [], "変化なしなら配信されない"
    # 新規行も notified=1 で挿入されている
    assert _row_notified(db_path, "test_bench") == 1
    assert _row_notified(db_path, "test_trend") == 1
