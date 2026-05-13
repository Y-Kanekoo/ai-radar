"""benchmarks registry の登録と取得 (Phase 3)."""

from __future__ import annotations

from ai_radar.crawler.benchmarks import (
    get_fetcher,
    registered_slugs,
)


def test_registered_slugs_includes_all_phase3() -> None:
    """Phase 3 の 3 fetcher (LMArena / MTEB / GitHub Trending) が登録されている."""
    slugs = registered_slugs()
    assert "lmarena_text" in slugs
    assert "mteb_models" in slugs
    assert "github_trending_daily" in slugs


def test_get_fetcher_returns_callable_for_registered_slug() -> None:
    """登録 slug は callable を返す."""
    fn = get_fetcher("lmarena_text")
    assert fn is not None
    assert callable(fn)


def test_get_fetcher_returns_none_for_unknown_slug() -> None:
    """未登録 slug は None."""
    assert get_fetcher("does_not_exist") is None


def test_duplicate_register_raises() -> None:
    """同一 slug を 2 度 register すると ValueError."""
    from ai_radar.crawler.benchmarks import register

    @register("dup_test_slug")
    async def _f(client):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    try:
        register("dup_test_slug")(_f)
    except ValueError:
        pass
    else:
        raise AssertionError("ValueError が発生しなかった")
