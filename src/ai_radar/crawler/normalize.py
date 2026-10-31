"""正規化層. URL / 日付 / 本文 / ハッシュをDB保存可能な形に整える.

47条の5 軽微利用の境界として `make_snippet` は **必ず** 100字以下に切り詰める.
これより長いテキストを公開してはいけない.
"""

from __future__ import annotations

import re

from radar_core import normalize as _core
from radar_core.normalize import TRACKING_PARAMS as TRACKING_PARAMS


def normalize_url(url: str) -> str:
    """URL を正規化する。既存の引数を維持して共有処理へ委譲する。"""
    return _core.normalize_url(url)


def normalize_published(struct_time: tuple[int, ...] | None) -> int:
    """published_parsed (UTC tuple) をUNIX秒に変換。None は現在時刻。"""
    return _core.normalize_published(struct_time)


def strip_html(text: str) -> str:
    """HTMLタグを除去しエンティティをデコードする。"""
    return _core.strip_html(text)


_WS = re.compile(r"\s+")


def make_snippet(body: str, max_chars: int = 100) -> str:
    """本文から **100字以内** の抜粋を生成する (47条の5軽微利用境界).

    HTML を除去 → 連続空白を1つに → max_chars で切り詰め. 切る位置は60%以降に
    スペースが見つかればそこを単語境界として採用する (英語向け補正).

    Args:
        body: 元本文 (HTML 可).
        max_chars: 最大文字数. 既定100.

    Returns:
        抜粋. max_chars を超える場合は末尾に `…` を付ける.
    """
    if max_chars > 0:
        return _core.make_snippet(body, max_chars)
    # radar-core が拒否する0以下の上限は、従来のスライス処理を維持する。
    plain = strip_html(body)
    plain = _WS.sub(" ", plain).strip()
    if len(plain) <= max_chars:
        return plain
    truncated = plain[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"


def compute_body_hash(body: str) -> str:
    """正規化後本文の SHA256 hex digest。クロスソース重複検出用。"""
    return _core.compute_body_hash(body)
