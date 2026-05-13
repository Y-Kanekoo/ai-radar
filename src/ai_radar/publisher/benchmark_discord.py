"""benchmark snapshot diff を Discord embed として配信する層 (Phase 3).

通常の記事 (FeedItem) は ``publisher/discord.py`` を経由するが、benchmark snapshot は
スキーマが異なる (rank 表 + diff summary) のでこちらに分離する.

設計:
- 1 snapshot = 1 embed. title は snapshot.display_name, description は
  "new / rank_up / rank_down / dropped" を圧縮表記.
- diff が空 (has_changes=False) の場合は配信せず ``notified=1`` だけ立てる.
- 47条の5境界: identifier (公開モデル名 / 公開リポ名) と公開数値のみ. body は無し.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot
from ai_radar.crawler.benchmarks.diff import SnapshotDiff
from ai_radar.publisher.discord import (
    DEFAULT_RATE_LIMIT_DELAY,
    DEFAULT_TIMEOUT,
    DISCORD_DESCRIPTION_LIMIT,
    DISCORD_TITLE_LIMIT,
)

logger = logging.getLogger("ai_radar.benchmark_discord")

# benchmark embed 用の色 (橙系: trend, 緑系: benchmark)
BENCHMARK_COLOR = 0x16A34A
TREND_COLOR = 0xF59E0B

MAX_ENTRY_PER_SECTION = 5  # 4 セクション × 5 件 = 20 行で description 制限内に収まる


def _fmt_entry(entry: BenchmarkEntry) -> str:
    """1 行を ``"#N name (score)"`` 形式で短く."""
    score_part = ""
    if entry.score is not None:
        score_part = f" ({entry.score:g})"
    return f"#{entry.rank} {entry.identifier}{score_part}"


def _build_description(diff: SnapshotDiff) -> str:
    """diff を Discord description にする. 空文字 = 配信不要."""
    lines: list[str] = []
    if diff.new_entries:
        lines.append("**🆕 新規ランクイン**")
        for e in diff.new_entries[:MAX_ENTRY_PER_SECTION]:
            lines.append(_fmt_entry(e))
        if len(diff.new_entries) > MAX_ENTRY_PER_SECTION:
            lines.append(f"… 他 {len(diff.new_entries) - MAX_ENTRY_PER_SECTION} 件")
        lines.append("")
    if diff.rank_up:
        lines.append("**📈 順位上昇**")
        for d in diff.rank_up[:MAX_ENTRY_PER_SECTION]:
            lines.append(f"{_fmt_entry(d.entry)} (前回 #{d.previous_rank})")
        if len(diff.rank_up) > MAX_ENTRY_PER_SECTION:
            lines.append(f"… 他 {len(diff.rank_up) - MAX_ENTRY_PER_SECTION} 件")
        lines.append("")
    if diff.rank_down:
        lines.append("**📉 順位下落**")
        for d in diff.rank_down[:MAX_ENTRY_PER_SECTION]:
            lines.append(f"{_fmt_entry(d.entry)} (前回 #{d.previous_rank})")
        if len(diff.rank_down) > MAX_ENTRY_PER_SECTION:
            lines.append(f"… 他 {len(diff.rank_down) - MAX_ENTRY_PER_SECTION} 件")
        lines.append("")
    if diff.dropped:
        lines.append("**❌ 圏外**")
        for d in diff.dropped[:MAX_ENTRY_PER_SECTION]:
            lines.append(f"{d.entry.identifier} (前回 #{d.previous_rank})")
        if len(diff.dropped) > MAX_ENTRY_PER_SECTION:
            lines.append(f"… 他 {len(diff.dropped) - MAX_ENTRY_PER_SECTION} 件")

    text = "\n".join(lines).rstrip()
    if len(text) > DISCORD_DESCRIPTION_LIMIT:
        text = text[: DISCORD_DESCRIPTION_LIMIT - 1] + "…"
    return text


def build_benchmark_embed(snapshot: BenchmarkSnapshot, diff: SnapshotDiff) -> dict[str, object]:
    """snapshot + diff から Discord embed dict を生成する.

    呼び出し側は ``diff.has_changes`` を事前に確認すること.
    """
    title = snapshot.display_name[:DISCORD_TITLE_LIMIT]
    desc = _build_description(diff)
    color = TREND_COLOR if snapshot.category == "trend" else BENCHMARK_COLOR
    return {
        "title": title,
        "description": desc or "(変化なし)",
        "color": color,
        "footer": {"text": f"ai-radar / {snapshot.source_slug}"},
        "timestamp": datetime.fromtimestamp(snapshot.captured_at, tz=UTC).isoformat(),
    }


async def send_benchmark_notification(
    snapshot: BenchmarkSnapshot,
    diff: SnapshotDiff,
    webhook_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """benchmark embed を 1 通だけ送信する.

    Args:
        snapshot: 最新 snapshot.
        diff: 直前との差分.
        webhook_url: Discord webhook URL.
        client: 共有 httpx.AsyncClient.
        timeout: HTTP タイムアウト.

    Returns:
        成功で True, 失敗で False.
    """
    payload = {"embeds": [build_benchmark_embed(snapshot, diff)]}
    own = client is None
    used = client if client is not None else httpx.AsyncClient(timeout=timeout)
    try:
        try:
            resp = await used.post(webhook_url, json=payload)
        except httpx.HTTPError as e:
            logger.warning("benchmark Discord 送信失敗 (network): %s", e)
            return False

        if 200 <= resp.status_code < 300:
            return True
        # 429 の retry は記事と違って 1 通限りなのでスキップ
        logger.warning(
            "benchmark Discord 送信失敗 status=%d body=%r",
            resp.status_code,
            resp.text[:200],
        )
        return False
    finally:
        if own:
            await used.aclose()


async def send_benchmark_batch(
    items: list[tuple[BenchmarkSnapshot, SnapshotDiff, str]],
    *,
    rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY,
    client: httpx.AsyncClient | None = None,
) -> list[bool]:
    """``(snapshot, diff, webhook_url)`` のリストを順次送信する.

    成否は各 item ごとに独立して返す. 失敗で後続を打ち切らないので、呼び出し側は
    成功した item だけ ``notified=1`` 等の状態遷移を行うこと.

    Returns:
        各 item の成否 (``True``=送信成功). 長さは ``items`` と同じ.
    """
    results: list[bool] = []
    own = client is None
    used = client if client is not None else httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    try:
        for i, (snap, dif, webhook) in enumerate(items):
            if i > 0 and rate_limit_delay > 0:
                await asyncio.sleep(rate_limit_delay)
            ok = await send_benchmark_notification(snap, dif, webhook, client=used)
            results.append(ok)
    finally:
        if own:
            await used.aclose()
    return results
