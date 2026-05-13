"""Phase 4a: Discord メッセージのリアクションを収集する CLI.

実行フロー:
    1. `article_notifications` から ``discord_message_id`` が記録済みの行を
       過去 ``--days`` 日分取得.
    2. (channel_id, message_id) ごとに Bot API でリアクション一覧を fetch.
    3. ``reactions`` テーブルに INSERT OR IGNORE (UNIQUE 重複は無視).
    4. 集計結果を log で要約.

実装メモ:
- ``AI_RADAR_DISCORD_BOT_TOKEN`` 必須. 未設定なら何もせず exit 0 (CI 安全).
- Bot は対象 channel に対して View Channel + Read Message History 権限が必要.
- Discord rate limit を踏まないように 1 メッセージごとに ``--delay`` 秒スリープ.

使用例:
    AI_RADAR_DISCORD_BOT_TOKEN=... \\
        uv run python scripts/collect_reactions.py --days 14
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import httpx

from ai_radar.db import init_db
from ai_radar.publisher.discord_bot import fetch_message_reactions
from ai_radar.publisher.notification_state import fetch_notifications_with_message_id
from ai_radar.publisher.reactions_store import ReactionEntry, insert_reactions

REPO_ROOT = Path(__file__).resolve().parent.parent
BOT_TOKEN_ENV = "AI_RADAR_DISCORD_BOT_TOKEN"
DEFAULT_DAYS = 14
DEFAULT_DELAY = 0.3  # 連続 Bot API 呼び出し間の待機


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ai-radar reaction collector (Phase 4a)")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=REPO_ROOT / "data" / "articles.db",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="過去何日分の通知を対象にするか (既定 14)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="1 回の実行で処理する最大メッセージ数",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="連続 Bot API 呼び出し間の待機秒数 (既定 0.3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Bot API は呼ぶが DB に書かない",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


async def _collect(
    log: logging.Logger,
    conn,
    bot_token: str,
    *,
    days: int,
    limit: int,
    delay: float,
    dry_run: bool,
) -> tuple[int, int]:
    """過去 ``days`` 日分のメッセージから reactions を集める.

    Returns: (処理メッセージ数, 挿入された reactions 件数)
    """
    since = int(time.time()) - days * 86400
    notes = fetch_notifications_with_message_id(conn, since_unix=since, limit=limit)
    if not notes:
        log.info("対象通知なし (since_unix=%d, limit=%d)", since, limit)
        return (0, 0)
    log.info("対象通知 %d 件 (過去 %d 日)", len(notes), days)

    processed = 0
    inserted = 0
    now = int(time.time())
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, note in enumerate(notes):
            if i > 0 and delay > 0:
                await asyncio.sleep(delay)
            rows = await fetch_message_reactions(
                channel_id=note.discord_channel_id,
                message_id=note.discord_message_id,
                bot_token=bot_token,
                client=client,
            )
            if rows is None:
                continue
            processed += 1
            if not rows:
                # リアクション 0 件: スキップ (テーブルに 0 行は持たない)
                continue
            entries = [
                ReactionEntry(
                    article_id=note.article_id,
                    discord_message_id=note.discord_message_id,
                    discord_channel_id=note.discord_channel_id,
                    emoji=r.emoji,
                    user_count=r.user_count,
                    collected_at=now,
                )
                for r in rows
            ]
            if dry_run:
                log.info(
                    "[DRY] article_id=%d msg=%s reactions=%s",
                    note.article_id,
                    note.discord_message_id,
                    ",".join(f"{r.emoji}:{r.user_count}" for r in rows),
                )
                continue
            inserted += insert_reactions(conn, entries)

    return (processed, inserted)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("ai_radar.collect_reactions")

    bot_token = os.environ.get(BOT_TOKEN_ENV, "").strip()
    if not bot_token:
        log.warning(
            "%s が未設定のため reactions 収集を skip (CI 安全のため exit 0)",
            BOT_TOKEN_ENV,
        )
        return 0

    if not args.db_path.exists():
        log.error("DB が存在しません: %s", args.db_path)
        return 1

    conn = init_db(args.db_path)
    try:
        processed, inserted = asyncio.run(
            _collect(
                log,
                conn,
                bot_token,
                days=args.days,
                limit=args.limit,
                delay=args.delay,
                dry_run=args.dry_run,
            )
        )
        log.info(
            "完了: 処理 %d メッセージ / 新規 reactions %d 行 / dry_run=%s",
            processed,
            inserted,
            args.dry_run,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
