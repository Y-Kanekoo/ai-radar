"""未通知記事を Discord webhook に送信する CLI (Phase 1: category 別 7ch 対応).

環境変数:
    DISCORD_WEBHOOK_URL (旧API):
        全カテゴリの fallback webhook URL. 後方互換のため残す.

    AI_RADAR_DISCORD_WEBHOOK_<CATEGORY> (Phase 1 推奨):
        カテゴリ別 webhook URL. <CATEGORY> は大文字 (例: ``..._RELEASE``).
        個別設定があれば優先、無ければ fallback (旧API) を使う.

categories (Phase 1):
    release / paper / newsletter / tool / jp / benchmark / trend / podcast

カテゴリごとに channel 名 ``discord_<category>`` で article_notifications に
記録するため、Phase 0 までの ``discord`` channel とは独立した通知履歴になる.

使用例:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... \\
        uv run python scripts/notify_discord.py

    AI_RADAR_DISCORD_WEBHOOK_RELEASE=https://discord.com/api/webhooks/AAA \\
    AI_RADAR_DISCORD_WEBHOOK_PAPER=https://discord.com/api/webhooks/BBB \\
        uv run python scripts/notify_discord.py --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx

from ai_radar.crawler.scoring import should_deliver
from ai_radar.db import init_db
from ai_radar.publisher.discord import (
    CATEGORY_ENV_PREFIX,
    DEFAULT_RATE_LIMIT_DELAY,
    DEFAULT_TIMEOUT,
    FALLBACK_ENV,
    resolve_webhook,
    send_notification_with_message_id,
)
from ai_radar.publisher.notification_state import (
    discord_channel_for_category,
    fetch_unnotified,
    mark_notified,
    mark_notified_with_message_id,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Phase 1: 7 categories + 旧 互換の "" (category 未指定 = 全カテゴリ統合配信)
KNOWN_CATEGORIES: tuple[str, ...] = (
    "release",
    "paper",
    "newsletter",
    "tool",
    "jp",
    "benchmark",
    "trend",
    "podcast",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ai-radar Discord 通知 (Phase 1: 7ch)")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=REPO_ROOT / "data" / "articles.db",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="1カテゴリあたりの送信最大件数 (既定 20)",
    )
    parser.add_argument(
        "--rate-delay",
        type=float,
        default=DEFAULT_RATE_LIMIT_DELAY,
        help="連続送信間隔 (秒)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には送信せず、対象を表示するだけ",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def _dispatch_category(
    conn,
    category: str,
    webhook_url: str,
    limit: int,
    rate_delay: float,
    dry_run: bool,
    log: logging.Logger,
) -> tuple[int, int, int]:
    """1 カテゴリ分の未通知記事を送信する.

    Phase 2: score >= SCORE_THRESHOLD の記事のみ配信. 閾値以下は配信せず通知済みに
    マーク (再評価しない). Tier 4-5 + ハイプキーワードヒットの記事は title 先頭に
    ⚠️ を付けて送る.

    Returns:
        (送信成功件数, 送信失敗件数, score 閾値未満で skip した件数).
    """
    channel = discord_channel_for_category(category)
    targets = fetch_unnotified(conn, channel=channel, limit=limit, category=category)
    if not targets:
        log.debug("%s: 未通知記事なし", category)
        return (0, 0, 0)

    # Phase 2: score フィルタで配信対象とスキップを分ける
    eligible = []
    skipped = []
    for t in targets:
        if should_deliver(
            tier=t.tier,
            category=t.category,
            published_at=t.item.published_at,
            is_hype=t.is_hype,
        ):
            eligible.append(t)
        else:
            skipped.append(t)

    log.info(
        "%s: 未通知 %d 件 (配信対象 %d / score 閾値未満 %d, channel=%s)",
        category,
        len(targets),
        len(eligible),
        len(skipped),
        channel,
    )

    # 閾値未満も通知済みとしてマーク (次回 fetch から除外)
    for t in skipped:
        mark_notified(conn, t.article_id, channel=channel)

    if not eligible:
        return (0, 0, len(skipped))

    if dry_run:
        for t in eligible:
            mark = "⚠️ " if t.is_hype else ""
            log.info("[DRY %s] %s%s — %s", category, mark, t.item.title, t.item.url)
        return (0, 0, len(skipped))

    # Phase 4a: per-item で送信し ?wait=true の応答から message_id を取得して保存する.
    # 失敗で打ち切らず、成功した item だけを (article_id, message_id) で mark する.
    success, failure = asyncio.run(
        _send_per_item_and_mark(
            conn,
            eligible,
            webhook_url,
            channel=channel,
            rate_delay=rate_delay,
            log=log,
        )
    )
    log.info("%s: 送信完了 success=%d failure=%d", category, success, failure)
    return (success, failure, len(skipped))


async def _send_per_item_and_mark(
    conn,
    eligible,
    webhook_url,
    *,
    channel,
    rate_delay,
    log,
) -> tuple[int, int]:
    """1 件ずつ送って Discord 側 message_id を回収しつつ mark する."""
    success = 0
    failure = 0
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        for i, t in enumerate(eligible):
            if i > 0 and rate_delay > 0:
                await asyncio.sleep(rate_delay)
            ok, msg_id, ch_id = await send_notification_with_message_id(
                t.item,
                webhook_url,
                is_hype=t.is_hype,
                client=client,
            )
            if ok:
                success += 1
                if msg_id:
                    mark_notified_with_message_id(
                        conn,
                        t.article_id,
                        channel=channel,
                        discord_message_id=msg_id,
                        discord_channel_id=ch_id,
                    )
                else:
                    # webhook が ?wait=true を尊重しなかった場合のフォールバック
                    mark_notified(conn, t.article_id, channel=channel)
            else:
                failure += 1
                log.debug("送信失敗 article_id=%d", t.article_id)
    return (success, failure)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("ai_radar.notify_discord")

    if not args.db_path.exists():
        log.error("DB が存在しません: %s", args.db_path)
        return 1

    # webhook が 1 つも設定されていない場合は警告して終了
    has_fallback = bool(os.environ.get(FALLBACK_ENV, "").strip())
    has_any_category = any(
        os.environ.get(f"{CATEGORY_ENV_PREFIX}{c.upper()}", "").strip() for c in KNOWN_CATEGORIES
    )
    if not has_fallback and not has_any_category and not args.dry_run:
        log.warning(
            "Discord webhook が 1 つも設定されていません (%s も AI_RADAR_DISCORD_WEBHOOK_* も未設定). "
            "通知をスキップします.",
            FALLBACK_ENV,
        )
        return 0

    conn = init_db(args.db_path)
    total_success = 0
    total_failure = 0
    total_skipped = 0
    try:
        for category in KNOWN_CATEGORIES:
            webhook = resolve_webhook(category)
            if not webhook:
                log.debug("%s: webhook 未設定 (fallback も無し)", category)
                continue
            success, failure, skipped = _dispatch_category(
                conn,
                category=category,
                webhook_url=webhook,
                limit=args.limit,
                rate_delay=args.rate_delay,
                dry_run=args.dry_run,
                log=log,
            )
            total_success += success
            total_failure += failure
            total_skipped += skipped
    finally:
        conn.close()

    log.info(
        "全カテゴリ合計: success=%d failure=%d score閾値未満=%d",
        total_success,
        total_failure,
        total_skipped,
    )
    return 0 if total_failure == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
