"""配信スコアリング (Phase 2 + 4a).

スコアリング式:
    score = source_tier_score(tier)
          × time_decay(category, age_seconds)
          × user_interest                # Phase 4a で配線、現状 1.0 固定
          × (1 - HYPE_PENALTY if is_hype else 1.0)

閾値 ``SCORE_THRESHOLD`` (0.5) 以上で Discord 配信を許可する.

時間減衰の半減期 (λ→半減期 = ln(2)/λ):
    release=0.5 (1.4日) / benchmark=0.3 (2.3日) / paper=0.05 (14日) /
    tutorial=0.01 (70日) / その他=0.3 (デフォルト)

設計判断:
- DB に score 列を持たせない (時間で変動するため). 配信時にオンザフライ計算.
- Tier 1-5 と category は既に DB に保存済み (sources テーブル v4) なので、
  Phase 4 でリアクション学習を導入するまでは静的な情報のみで計算できる.

Phase 4a: ``user_interest_for(slug, conn)`` を配線するが、現時点は固定 1.0 を返す
(リアクションデータがまだ蓄積されていないため). データが溜まり次第 Phase 4.5 で
Bayesian posterior 等に差し替える前提.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time

logger = logging.getLogger("ai_radar.scoring")

# 配信閾値. プラン §5.4 の値.
SCORE_THRESHOLD = 0.5

# ハイプ警告フラグが立っているときのスコア減衰率 (0.5 = 半減).
HYPE_PENALTY = 0.5

# Tier 1-5 の既存配信重み。査読/品質/人気の証拠とは独立。数値は変更しない。
_TIER_SCORE: dict[int, float] = {
    1: 1.0,  # 公式
    2: 0.8,  # 既存 Tier 2 (arXiv等を含む。査読を意味しない)
    3: 0.7,  # キュレーション
    4: 0.5,  # 個人ブログ
    5: 0.3,  # SNS拡散
}
_TIER_FALLBACK_SCORE = 0.5

# category 別の時間減衰 λ. ai-radar の category 命名に合わせる
# (release / paper / newsletter / tool / jp / benchmark / trend / podcast).
_LAMBDA_BY_CATEGORY: dict[str, float] = {
    "release": 0.5,
    "benchmark": 0.3,
    "paper": 0.05,
    "newsletter": 0.4,
    "tool": 0.4,
    "jp": 0.3,
    "trend": 0.4,
    "podcast": 0.2,
}
_DEFAULT_LAMBDA = 0.3


# Phase 4a: リアクション集計から user_interest を引く窓 (14 日).
USER_INTEREST_WINDOW_SECONDS = 14 * 86400
# Phase 4a の no-op フォールバック. Phase 4.5 で Beta posterior に置き換える前提.
USER_INTEREST_DEFAULT = 1.0
USER_INTEREST_MIN = 0.5
USER_INTEREST_MAX = 2.0


def user_interest_for(
    source_slug: str,
    conn: sqlite3.Connection | None = None,
    *,
    now: int | None = None,
    window_seconds: int = USER_INTEREST_WINDOW_SECONDS,
) -> float:
    """source slug に対するユーザ興味係数を返す (Phase 4a no-op).

    現状は ``USER_INTEREST_DEFAULT`` (1.0) 固定. リアクション集計テーブル
    (Phase 4a で追加) のデータが揃ったら Phase 4.5 で Beta posterior に置き換える.

    ``conn`` が ``None`` でも安全に動く (テスト用) ようにしておく.

    Args:
        source_slug: ソース slug. ``user_interest`` をスケーリングするキー.
        conn: SQLite 接続. None なら default 値を返す.
        now: 現在時刻 (unix 秒). テスト用. None なら ``time.time()``.
        window_seconds: 集計窓 (秒). デフォルト 14 日.

    Returns:
        係数 (``USER_INTEREST_MIN`` 〜 ``USER_INTEREST_MAX`` の範囲). 現状常に 1.0.
    """
    if conn is None:
        return USER_INTEREST_DEFAULT
    current = int(time.time()) if now is None else now
    since = current - window_seconds
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM reactions r
            JOIN articles a ON r.article_id = a.id
            JOIN sources s ON a.source_id = s.id
            WHERE s.slug = ? AND r.collected_at >= ?
            """,
            (source_slug, since),
        ).fetchone()
    except sqlite3.OperationalError as e:
        # reactions テーブルがまだ無い (古い DB) の場合は default にフォールバック.
        logger.debug("reactions テーブル無し source=%s err=%s", source_slug, e)
        return USER_INTEREST_DEFAULT
    if row is None or not row["c"]:
        # 集計データなし -> default.
        return USER_INTEREST_DEFAULT
    # Phase 4a: count > 0 でも 1.0 を返す (no-op). Phase 4.5 で重み付けする.
    return USER_INTEREST_DEFAULT


def source_tier_score(tier: int) -> float:
    """Tier (1-5) を 0.3〜1.0 のスコアに変換. 範囲外は 0.5."""
    return _TIER_SCORE.get(tier, _TIER_FALLBACK_SCORE)


def time_decay(category: str, age_seconds: int) -> float:
    """category 別の時間減衰係数を返す.

    age_seconds が負 (未来日付) は 1.0 として扱う.
    減衰式は ``exp(-λ × age_days)``.
    """
    if age_seconds < 0:
        return 1.0
    lam = _LAMBDA_BY_CATEGORY.get(category, _DEFAULT_LAMBDA)
    age_days = age_seconds / 86400.0
    return math.exp(-lam * age_days)


def compute_score(
    *,
    tier: int,
    category: str,
    age_seconds: int,
    is_hype: bool = False,
    user_interest: float = 1.0,
) -> float:
    """配信スコアを計算する.

    Args:
        tier: ソースの配信優先度 (1-5).
        category: ソース category (release / paper / ...).
        age_seconds: 公開からの経過秒数. ``int(time.time() - published_at)``.
        is_hype: Tier 4-5 でハイプ警告フラグが立っているか.
        user_interest: ユーザ興味係数 (Phase 4 でリアクション学習から取得).

    Returns:
        ``score`` (0.0 以上). ``SCORE_THRESHOLD`` 以上で配信推奨.
    """
    score = source_tier_score(tier) * time_decay(category, age_seconds) * user_interest
    if is_hype:
        score *= 1.0 - HYPE_PENALTY
    return score


def should_deliver(
    *,
    tier: int,
    category: str,
    published_at: int,
    is_hype: bool = False,
    user_interest: float = 1.0,
    now: int | None = None,
    threshold: float = SCORE_THRESHOLD,
) -> bool:
    """Discord 配信すべきかを判定する.

    ``published_at`` から現在までの経過時間でスコアを計算し、``threshold`` と比較する.

    Args:
        tier: ソース配信優先度.
        category: ソース category.
        published_at: 記事公開時刻 (unix 秒).
        is_hype: ハイプフラグ.
        user_interest: ユーザ興味係数 (Phase 4 用).
        now: 評価時の時刻 (unix 秒). None なら ``time.time()``.
        threshold: 閾値 (デフォルト 0.5).

    Returns:
        score >= threshold なら True.
    """
    current = int(time.time()) if now is None else now
    age_seconds = current - published_at
    score = compute_score(
        tier=tier,
        category=category,
        age_seconds=age_seconds,
        is_hype=is_hype,
        user_interest=user_interest,
    )
    return score >= threshold
