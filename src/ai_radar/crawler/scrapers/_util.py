"""Scraper 共通ユーティリティ (Phase 0.5).

サイト固有の差を吸収する小さなヘルパ. URL 結合と日付の正規化を提供する.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urljoin

from dateutil import parser as dateparser


def absolute_url(base: str, href: str) -> str:
    """相対 URL を絶対 URL に. すでに絶対なら href をそのまま返す."""
    return urljoin(base, href)


def parse_date_to_struct(text: str | None) -> tuple[int, ...] | None:
    """日付テキストを 6 要素 (UTC) struct_time タプルに変換する.

    対応形式は dateutil.parser が解釈できるもの全部. ISO 8601 (`datetime` 属性),
    "May 6, 2026", "2026/04/20", "2026.05.11" など実例で確認した形式は全て通る.

    Args:
        text: 日付文字列. None / 空文字なら None を返す.

    Returns:
        (year, month, day, hour, minute, second) の UTC タプル. 失敗時は None.
    """
    if not text:
        return None
    try:
        dt = dateparser.parse(text)
    except (ValueError, TypeError, OverflowError):
        return None
    if dt is None:
        return None
    # naive datetime は UTC として扱う (Anthropic の "May 6, 2026" 等)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    utc = dt.astimezone(UTC)
    return (utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second)


def now_utc_struct() -> tuple[int, ...]:
    """現在の UTC を struct タプルで返す. 日付が DOM に無いソース (HF Papers) 用."""
    n = datetime.now(UTC)
    return (n.year, n.month, n.day, n.hour, n.minute, n.second)
