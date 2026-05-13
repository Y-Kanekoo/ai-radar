"""crawler/scoring.py のユニットテスト (Phase 2)."""

from __future__ import annotations

import math

from ai_radar.crawler.scoring import (
    HYPE_PENALTY,
    SCORE_THRESHOLD,
    compute_score,
    should_deliver,
    source_tier_score,
    time_decay,
)


class TestSourceTierScore:
    def test_tier_1_is_top(self) -> None:
        assert source_tier_score(1) == 1.0

    def test_tier_5_is_lowest(self) -> None:
        assert source_tier_score(5) == 0.3

    def test_tier_monotonic_decreasing(self) -> None:
        scores = [source_tier_score(t) for t in (1, 2, 3, 4, 5)]
        assert scores == sorted(scores, reverse=True)

    def test_unknown_tier_falls_back(self) -> None:
        # 0 や 99 は未定義 → 0.5 fallback
        assert source_tier_score(0) == 0.5
        assert source_tier_score(99) == 0.5


class TestTimeDecay:
    def test_zero_age_is_one(self) -> None:
        # age=0 → exp(0) = 1.0
        assert time_decay("release", 0) == 1.0

    def test_negative_age_is_one(self) -> None:
        # 未来日付は 1.0
        assert time_decay("release", -100) == 1.0

    def test_release_decays_quickly(self) -> None:
        """release は λ=0.5 → 1 日後の係数は exp(-0.5) ≈ 0.607."""
        result = time_decay("release", 86400)
        assert math.isclose(result, math.exp(-0.5), rel_tol=1e-6)

    def test_paper_decays_slowly(self) -> None:
        """paper は λ=0.05 → 1 日後でも 0.95 程度."""
        result = time_decay("paper", 86400)
        assert math.isclose(result, math.exp(-0.05), rel_tol=1e-6)
        assert result > 0.9

    def test_unknown_category_uses_default_lambda(self) -> None:
        """未定義 category はデフォルト λ=0.3 を使う."""
        result = time_decay("unknown", 86400)
        assert math.isclose(result, math.exp(-0.3), rel_tol=1e-6)


class TestComputeScore:
    def test_tier1_release_fresh(self) -> None:
        """Tier 1 + release + 即時 → ≈ 1.0."""
        s = compute_score(tier=1, category="release", age_seconds=0)
        assert math.isclose(s, 1.0)

    def test_tier5_old_paper_low(self) -> None:
        """Tier 5 + paper + 14日 → 低スコア."""
        s = compute_score(tier=5, category="paper", age_seconds=86400 * 14)
        # tier_5=0.3 × exp(-0.05*14) ≈ 0.3 × 0.497 ≈ 0.149
        assert s < 0.2

    def test_hype_penalty_halves_score(self) -> None:
        without = compute_score(tier=1, category="release", age_seconds=0, is_hype=False)
        with_hype = compute_score(tier=1, category="release", age_seconds=0, is_hype=True)
        assert math.isclose(with_hype, without * (1 - HYPE_PENALTY))

    def test_user_interest_scales(self) -> None:
        base = compute_score(tier=2, category="paper", age_seconds=0)
        doubled = compute_score(tier=2, category="paper", age_seconds=0, user_interest=2.0)
        assert math.isclose(doubled, base * 2.0)


class TestShouldDeliver:
    def test_fresh_tier1_release_passes(self) -> None:
        """Tier 1 公式の即時 release は配信対象."""
        assert should_deliver(
            tier=1, category="release", published_at=1_700_000_000, now=1_700_000_000
        )

    def test_old_tier4_release_filtered(self) -> None:
        """Tier 4 個人の 1 週間前 release は閾値未満."""
        # tier_4=0.5 × exp(-0.5 * 7) ≈ 0.5 × 0.030 ≈ 0.015
        assert not should_deliver(
            tier=4,
            category="release",
            published_at=1_700_000_000,
            now=1_700_000_000 + 86400 * 7,
        )

    def test_threshold_boundary(self) -> None:
        """閾値ちょうどは配信対象 (>= で判定)."""
        # tier_3=0.7, 0 age → 0.7 > 0.5
        assert should_deliver(
            tier=3, category="release", published_at=1_700_000_000, now=1_700_000_000
        )

    def test_hype_drops_below_threshold(self) -> None:
        """Tier 3 の即時記事も、hype フラグで閾値下回ることがある."""
        # tier_3=0.7 × 1.0 × (1 - 0.5) = 0.35 < 0.5
        assert not should_deliver(
            tier=3,
            category="release",
            published_at=1_700_000_000,
            now=1_700_000_000,
            is_hype=True,
        )


def test_score_threshold_is_half() -> None:
    """プラン §5.4 の閾値 0.5."""
    assert SCORE_THRESHOLD == 0.5
