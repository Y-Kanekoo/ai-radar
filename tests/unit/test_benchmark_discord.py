"""benchmark Discord embed の生成 (Phase 3)."""

from __future__ import annotations

import asyncio

import httpx

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot
from ai_radar.crawler.benchmarks.diff import RankedDiff, SnapshotDiff
from ai_radar.publisher.benchmark_discord import (
    BENCHMARK_COLOR,
    TREND_COLOR,
    build_benchmark_embed,
    send_benchmark_notification,
)


def _entry(rank: int, ident: str, score: float | None = None) -> BenchmarkEntry:
    return BenchmarkEntry(rank=rank, identifier=ident, score=score, payload={})


def _snap(category: str = "benchmark") -> BenchmarkSnapshot:
    return BenchmarkSnapshot(
        source_slug="test_src",
        category=category,
        captured_at=1700000000,
        entries=(),
        display_name="Test Display",
    )


def _diff_with_new() -> SnapshotDiff:
    return SnapshotDiff(
        new_entries=(_entry(1, "Model-X", 1300.0), _entry(3, "Model-Y", 1250.0)),
        rank_up=(),
        rank_down=(),
        dropped=(),
    )


def test_build_embed_uses_benchmark_color_for_benchmark_category() -> None:
    """category=benchmark は BENCHMARK_COLOR を使う."""
    embed = build_benchmark_embed(_snap("benchmark"), _diff_with_new())
    assert embed["color"] == BENCHMARK_COLOR


def test_build_embed_uses_trend_color_for_trend_category() -> None:
    """category=trend は TREND_COLOR を使う."""
    embed = build_benchmark_embed(_snap("trend"), _diff_with_new())
    assert embed["color"] == TREND_COLOR


def test_build_embed_title_is_display_name() -> None:
    """title は snapshot.display_name."""
    embed = build_benchmark_embed(_snap(), _diff_with_new())
    assert embed["title"] == "Test Display"


def test_build_embed_description_has_section_headers() -> None:
    """description に 4 セクションの一部が含まれる."""
    diff = SnapshotDiff(
        new_entries=(_entry(1, "A", 1.0),),
        rank_up=(RankedDiff(entry=_entry(2, "B", 0.9), previous_rank=5),),
        rank_down=(RankedDiff(entry=_entry(8, "C", 0.5), previous_rank=3),),
        dropped=(RankedDiff(entry=_entry(99, "D", None), previous_rank=4),),
    )
    embed = build_benchmark_embed(_snap(), diff)
    desc = embed["description"]
    assert isinstance(desc, str)
    assert "🆕 新規ランクイン" in desc
    assert "📈 順位上昇" in desc
    assert "📉 順位下落" in desc
    assert "❌ 圏外" in desc


def test_build_embed_truncates_long_description() -> None:
    """description は DISCORD_DESCRIPTION_LIMIT を超えない."""
    big = tuple(_entry(i, f"id-{'X' * 80}-{i}", 1.0) for i in range(1, 50))
    diff = SnapshotDiff(new_entries=big, rank_up=(), rank_down=(), dropped=())
    embed = build_benchmark_embed(_snap(), diff)
    desc = embed["description"]
    assert isinstance(desc, str)
    assert len(desc) <= 2048


def test_build_embed_empty_description_shows_placeholder() -> None:
    """diff が空でも description は空文字にならない."""
    diff = SnapshotDiff(new_entries=(), rank_up=(), rank_down=(), dropped=())
    embed = build_benchmark_embed(_snap(), diff)
    assert embed["description"] == "(変化なし)"


def test_send_benchmark_notification_returns_true_on_success() -> None:
    """webhook 204 で True."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        ok = asyncio.run(
            send_benchmark_notification(
                _snap(),
                _diff_with_new(),
                "https://discord.com/api/webhooks/X/Y",
                client=client,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert ok is True


def test_send_benchmark_notification_returns_false_on_error() -> None:
    """webhook 500 で False."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"oops")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        ok = asyncio.run(
            send_benchmark_notification(
                _snap(),
                _diff_with_new(),
                "https://discord.com/api/webhooks/X/Y",
                client=client,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert ok is False


def test_send_benchmark_batch_returns_per_item_results() -> None:
    """batch は item ごとの bool リストを返し、中間失敗で打ち切らない."""
    from ai_radar.publisher.benchmark_discord import send_benchmark_batch

    # 3 件の webhook URL ごとに status を変える: 0→204, 1→500, 2→204
    call_index = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = call_index["i"]
        call_index["i"] += 1
        return httpx.Response(204 if i != 1 else 500)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    items = [
        (_snap(), _diff_with_new(), f"https://discord.com/api/webhooks/X/{i}") for i in range(3)
    ]
    try:
        results = asyncio.run(send_benchmark_batch(items, rate_limit_delay=0.0, client=client))
    finally:
        asyncio.run(client.aclose())
    # 真ん中だけ失敗、前後は成功している (打ち切らずに最後まで進む)
    assert results == [True, False, True]
