"""Phase 3: ベンチマーク / Trending snapshot を取得し、差分を Discord に配信する CLI.

実行フロー:
    1. 登録 fetcher を全部 (または ``--source`` で指定したものを) 並列実行.
    2. 取得 snapshot を DB に保存 (UNIQUE 違反 = 同 captured_at の重複はスキップ).
    3. 直前 snapshot との diff を計算.
    4. diff.has_changes な snapshot は Discord に embed 1 通配信.
    5. 配信完了で notified=1 をセット.

実装メモ:
- LMArena / MTEB は ``category=benchmark`` → ``AI_RADAR_DISCORD_WEBHOOK_BENCHMARK``
- GitHub Trending は ``category=trend`` → ``AI_RADAR_DISCORD_WEBHOOK_TREND``
- どちらも未設定なら ``DISCORD_WEBHOOK_URL`` を fallback.

使用例:
    AI_RADAR_DISCORD_WEBHOOK_BENCHMARK=... \\
    AI_RADAR_DISCORD_WEBHOOK_TREND=... \\
      uv run python scripts/track_benchmarks.py

    uv run python scripts/track_benchmarks.py --source lmarena_text --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx

from ai_radar.crawler.benchmarks import (
    BenchmarkSnapshot,
    get_fetcher,
    registered_slugs,
)
from ai_radar.crawler.benchmarks.diff import SnapshotDiff, compute_diff
from ai_radar.crawler.benchmarks.store import (
    fetch_unnotified_snapshots,
    latest_before,
    mark_snapshot_notified,
    save_snapshot,
)
from ai_radar.db import init_db
from ai_radar.publisher.benchmark_discord import send_benchmark_batch
from ai_radar.publisher.discord import resolve_webhook

REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ai-radar benchmark snapshot tracker (Phase 3)")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=REPO_ROOT / "data" / "articles.db",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=None,
        help="特定 slug のみ取得 (省略時は全登録 fetcher). 複数指定可.",
    )
    parser.add_argument(
        "--min-rank-delta",
        type=int,
        default=2,
        help="rank 変動の最小しきい値 (既定 2).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 保存も Discord 配信もせず diff だけ表示する.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


async def _run_fetchers(slugs: list[str], log: logging.Logger) -> list[BenchmarkSnapshot]:
    """指定 slug の fetcher を並列実行して snapshot を集める.

    1 つでも例外で落ちないように `gather(..., return_exceptions=True)` で吸収する.
    未登録 slug は skip し、登録済みのみ実行する.
    """
    runnable: list[tuple[str, object]] = []  # (slug, coro)
    for slug in slugs:
        fetcher = get_fetcher(slug)
        if fetcher is None:
            log.warning("未登録 slug: %s", slug)
            continue
        runnable.append((slug, fetcher))

    if not runnable:
        return []

    async with httpx.AsyncClient(timeout=60.0) as client:
        tasks = [fn(client) for _, fn in runnable]  # type: ignore[operator]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    snapshots: list[BenchmarkSnapshot] = []
    for (slug, _fn), r in zip(runnable, results, strict=True):
        if isinstance(r, Exception):
            log.warning("fetcher 例外 slug=%s err=%s", slug, r)
            continue
        if isinstance(r, BenchmarkSnapshot):
            snapshots.append(r)
    return snapshots


def _log_diff(log: logging.Logger, snap: BenchmarkSnapshot, dif: SnapshotDiff) -> None:
    log.info(
        "%s: 新規=%d 上昇=%d 下落=%d 圏外=%d",
        snap.source_slug,
        len(dif.new_entries),
        len(dif.rank_up),
        len(dif.rank_down),
        len(dif.dropped),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("ai_radar.track_benchmarks")

    target_slugs = sorted(args.source) if args.source else sorted(registered_slugs())
    if not target_slugs:
        log.error("登録 fetcher がありません")
        return 1

    log.info("対象 slug: %s", ",".join(target_slugs))

    snapshots = asyncio.run(_run_fetchers(target_slugs, log))
    if not snapshots:
        log.warning("snapshot がひとつも取れませんでした")
        return 0

    if not args.db_path.exists():
        log.info("DB 新規作成: %s", args.db_path)
    conn = init_db(args.db_path)
    try:
        # Step A: 保存. 同時に diff も計算しておく.
        diffs_to_send: list[tuple[BenchmarkSnapshot, SnapshotDiff, int | None]] = []
        for snap in snapshots:
            if not snap.entries:
                log.info("%s: 空 snapshot (fetch 失敗), skip", snap.source_slug)
                continue
            prev = latest_before(conn, source_slug=snap.source_slug, before=snap.captured_at)
            dif = compute_diff(prev, snap, min_rank_delta=args.min_rank_delta)
            _log_diff(log, snap, dif)

            if args.dry_run:
                diffs_to_send.append((snap, dif, None))
                continue

            row_id = save_snapshot(conn, snap)
            if row_id is None:
                # 同時刻の snapshot が既にある (cron が短時間で2回回ったケース)
                continue

            if not dif.has_changes:
                # 配信しない: 即 notified=1 でクローズ
                mark_snapshot_notified(conn, row_id)
                continue
            diffs_to_send.append((snap, dif, row_id))

        # Step B: 既に DB に積まれた notified=0 のものも拾う (前回 run で配信失敗した分)
        if not args.dry_run:
            for row_id, snap in fetch_unnotified_snapshots(conn, limit=20):
                if any(r == row_id for _, _, r in diffs_to_send):
                    continue
                prev = latest_before(conn, source_slug=snap.source_slug, before=snap.captured_at)
                dif = compute_diff(prev, snap, min_rank_delta=args.min_rank_delta)
                if not dif.has_changes:
                    mark_snapshot_notified(conn, row_id)
                    continue
                diffs_to_send.append((snap, dif, row_id))

        # Step C: Discord 配信
        if not diffs_to_send:
            log.info("配信対象なし")
            return 0

        # send_items に row_id も同梱して、フィルタや失敗で順序がずれても
        # 成功した item の row_id だけを mark できるようにする.
        send_items: list[tuple[BenchmarkSnapshot, SnapshotDiff, str, int | None]] = []
        for snap, dif, row_id in diffs_to_send:
            webhook = resolve_webhook(snap.category)
            if not webhook:
                log.info("%s: webhook 未設定 (category=%s)、skip", snap.source_slug, snap.category)
                continue
            if args.dry_run:
                log.info(
                    "[DRY %s] %s 件の変化 (config=%s)",
                    snap.source_slug,
                    sum(
                        [
                            len(dif.new_entries),
                            len(dif.rank_up),
                            len(dif.rank_down),
                            len(dif.dropped),
                        ]
                    ),
                    snap.category,
                )
                continue
            send_items.append((snap, dif, webhook, row_id))

        if args.dry_run or not send_items:
            log.info("配信送信件数: %d", len(send_items))
            return 0

        batch = [(s, d, w) for s, d, w, _ in send_items]
        results = asyncio.run(send_benchmark_batch(batch))
        success = sum(1 for ok in results if ok)
        failure = sum(1 for ok in results if not ok)
        log.info("Discord 配信 success=%d failure=%d", success, failure)

        # 成功した item の row_id だけを mark する (順序ずれ・中間失敗に耐性あり)
        for (_snap, _dif, _wh, row_id), ok in zip(send_items, results, strict=True):
            if ok and row_id is not None:
                mark_snapshot_notified(conn, row_id)

        return 0 if failure == 0 else 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
