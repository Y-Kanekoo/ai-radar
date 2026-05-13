"""Discord Bot API クライアント (Phase 4a, リアクション読み取り用).

webhook は書き込み専用なので、リアクション (絵文字) を読むには Bot user が必要.
このモジュールは ``Bot <token>`` 認証で ``/channels/{cid}/messages/{mid}`` を叩いて
``reactions`` フィールドを取得する.

設計:
- Bot token は ``AI_RADAR_DISCORD_BOT_TOKEN`` env. webhook URL とは独立.
- 1 メッセージにつき 1 API call. ただし Discord API は 429 (rate limit) を厳格に
  返すので Retry-After + 指数バックオフ.
- 取得した reactions は ``ReactionRow`` のリストとして返す.

外部仕様:
    GET https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}
    Headers: Authorization: Bot {token}
    Response.reactions = [{"emoji": {"name": "👍", "id": null}, "count": 3}, ...]
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from ai_radar import __version__

logger = logging.getLogger("ai_radar.discord_bot")

API_BASE = "https://discord.com/api/v10"
USER_AGENT = f"DiscordBot (https://github.com/Y-Kanekoo/ai-radar, {__version__})"
DEFAULT_TIMEOUT = 15.0
MAX_RETRIES_429 = 3


@dataclass(frozen=True)
class ReactionRow:
    """1 メッセージ × 1 絵文字あたりの集計 1 行."""

    emoji: str
    user_count: int


def _emoji_label(emoji_obj: object) -> str | None:
    """Discord response の ``emoji`` object を ``"👍"`` 形式の文字列にする.

    通常絵文字: ``{"name": "👍", "id": null}`` → ``"👍"``
    カスタム絵文字: ``{"name": "foo", "id": "12345"}`` → ``"foo:12345"``
    None / 不正形式は None.
    """
    if not isinstance(emoji_obj, dict):
        return None
    name = emoji_obj.get("name")
    if not isinstance(name, str) or not name:
        return None
    cid = emoji_obj.get("id")
    if cid:
        return f"{name}:{cid}"
    return name


def _parse_reactions(message_body: dict) -> list[ReactionRow]:
    """メッセージ JSON から ``reactions`` を抽出する.

    ``reactions`` フィールドが欠落していたり空配列なら空リスト. 集計対象に
    含まれない (= まだ誰もリアクションしていない) ことを意味する.
    """
    raw = message_body.get("reactions") if isinstance(message_body, dict) else None
    if not isinstance(raw, list):
        return []
    rows: list[ReactionRow] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        emoji = _emoji_label(r.get("emoji"))
        if emoji is None:
            continue
        count = r.get("count")
        if not isinstance(count, int) or count < 0:
            continue
        rows.append(ReactionRow(emoji=emoji, user_count=count))
    return rows


async def fetch_message_reactions(
    channel_id: str,
    message_id: str,
    bot_token: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[ReactionRow] | None:
    """1 メッセージのリアクション一覧を取得する.

    Args:
        channel_id: Discord channel ID (snowflake).
        message_id: Discord message ID (snowflake).
        bot_token: Bot トークン (``AI_RADAR_DISCORD_BOT_TOKEN``).
        client: 共有 httpx.AsyncClient. None なら関数内で生成.
        timeout: HTTP タイムアウト.

    Returns:
        ``ReactionRow`` のリスト. メッセージ削除済み (404) や権限不足 (403) なら
        ``None``. 一時エラー (5xx) は max_retries で吸収.
    """
    url = f"{API_BASE}/channels/{channel_id}/messages/{message_id}"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    own = client is None
    used = client if client is not None else httpx.AsyncClient(timeout=timeout)
    try:
        for attempt in range(MAX_RETRIES_429 + 1):
            try:
                resp = await used.get(url, headers=headers)
            except httpx.HTTPError as e:
                logger.warning(
                    "Bot API 取得失敗 (network) channel=%s msg=%s err=%s", channel_id, message_id, e
                )
                return None

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    logger.warning("Bot API レスポンスが JSON でない msg=%s", message_id)
                    return None
                return _parse_reactions(body)

            if resp.status_code == 404:
                logger.info("Bot API 404 (削除済?) msg=%s", message_id)
                return None
            if resp.status_code == 403:
                logger.warning("Bot API 403 (権限不足?) msg=%s", message_id)
                return None

            if resp.status_code == 429 and attempt < MAX_RETRIES_429:
                retry_after = _parse_retry_after(resp)
                logger.info(
                    "Bot API rate limited, %.2fs 待機して再試行 msg=%s",
                    retry_after,
                    message_id,
                )
                await asyncio.sleep(retry_after)
                continue

            if 500 <= resp.status_code < 600 and attempt < MAX_RETRIES_429:
                # 一時的なサーバエラーは backoff で retry
                wait = 2.0 * (attempt + 1)
                logger.info(
                    "Bot API status=%d, %.1fs 待機して再試行 msg=%s",
                    resp.status_code,
                    wait,
                    message_id,
                )
                await asyncio.sleep(wait)
                continue

            logger.warning(
                "Bot API 失敗 status=%d msg=%s body=%r",
                resp.status_code,
                message_id,
                resp.text[:200],
            )
            return None
        return None
    finally:
        if own:
            await used.aclose()


def _parse_retry_after(resp: httpx.Response) -> float:
    """Retry-After ヘッダ or JSON body の retry_after を秒で返す."""
    header = resp.headers.get("retry-after")
    if header is not None:
        try:
            return max(0.5, float(header))
        except ValueError:
            pass
    try:
        body = resp.json()
        return max(0.5, float(body.get("retry_after", 1.0)))
    except (ValueError, TypeError, KeyError):
        return 1.0
