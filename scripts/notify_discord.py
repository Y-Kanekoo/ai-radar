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

from ai_radar.db import init_db
from ai_radar.publisher.discord import (
    CATEGORY_ENV_PREFIX,
    DEFAULT_RATE_LIMIT_DELAY,
    FALLBACK_ENV,
    resolve_webhook,
    send_batch,
)
from ai_radar.publisher.notification_state import (
    discord_channel_for_category,
    fetch_unnotified,
    mark_notified,
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
) -> tuple[int, int]:
    """1 カテゴリ分の未通知記事を送信して、成功/失敗の件数を返す."""
    channel = discord_channel_for_category(category)
    targets = fetch_unnotified(conn, channel=channel, limit=limit, category=category)
    if not targets:
        log.debug("%s: 未通知記事なし", category)
        return (0, 0)

    log.info("%s: 未通知 %d 件 (channel=%s)", category, len(targets), channel)

    if dry_run:
        for t in targets:
            log.info("[DRY %s] %s — %s", category, t.item.title, t.item.url)
        return (0, 0)

    items = [t.item for t in targets]
    success, failure = asyncio.run(send_batch(items, webhook_url, rate_limit_delay=rate_delay))
    log.info("%s: 送信完了 success=%d failure=%d", category, success, failure)

    # 成功した先頭から `success` 件を mark する
    for t in targets[:success]:
        mark_notified(conn, t.article_id, channel=channel)

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
    try:
        for category in KNOWN_CATEGORIES:
            webhook = resolve_webhook(category)
            if not webhook:
                log.debug("%s: webhook 未設定 (fallback も無し)", category)
                continue
            success, failure = _dispatch_category(
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
    finally:
        conn.close()

    log.info("全カテゴリ合計: success=%d failure=%d", total_success, total_failure)
    return 0 if total_failure == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
