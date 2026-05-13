"""sources.yaml / blocked.yaml ロード."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_radar.sources import (
    BlockedConfig,
    SourceConfig,
    load_blocked,
    load_sources,
)


def test_loads_20_sources_from_real_yaml() -> None:
    """実際の config/sources.yaml が Phase 0.5 の 20 ソースで正常パース.

    内訳: Phase 0 (11 sources, RSS) + Phase 0.5 (9 sources, 1 RSS + 8 scraper).
    Phase 3 以降の追加で更新.
    """
    sources = load_sources()
    assert len(sources) == 20


def test_all_sources_have_required_fields() -> None:
    sources = load_sources()
    for s in sources:
        assert isinstance(s, SourceConfig)
        assert s.slug
        assert s.name
        assert s.feed_url.startswith(("http://", "https://"))
        assert s.language in {"ja", "en"}, f"{s.slug}: 不正言語 {s.language}"
        assert s.category in {"release", "paper", "newsletter", "tool", "jp"}, (
            f"{s.slug}: 不正カテゴリ {s.category}"
        )
        assert s.fetch_policy.min_interval_seconds >= 0
        assert s.fetch_policy.max_items_per_fetch > 0


def test_slugs_are_unique() -> None:
    sources = load_sources()
    slugs = [s.slug for s in sources]
    assert len(slugs) == len(set(slugs)), "slug が重複している"


def test_critical_sources_present() -> None:
    """Phase 0 + Phase 0.5 コアソースが含まれている."""
    slugs = {s.slug for s in load_sources()}
    must = {
        # Phase 0 (RSS)
        "huggingface-blog",
        "google-research-blog",
        "arxiv-cs-lg",
        "tldr-ai",
        "stockmark-blog",
        # Phase 0.5 (scraper + 1 RSS)
        "anthropic-news",
        "hf-papers",
        "cursor-blog",
        "sakana-ai",
    }
    missing = must - slugs
    assert not missing, f"必須ソースが欠落: {missing}"


def test_phase05_scraper_sources_have_correct_fetch_kind() -> None:
    """Phase 0.5 で追加した 8 scraper ソースが fetch_kind='scraper' になっている."""
    by_slug = {s.slug: s for s in load_sources()}
    scraper_slugs = {
        "anthropic-news",
        "hf-papers",
        "cursor-blog",
        "elyza-news",
        "ai2-blog",
        "kimi-blog",
        "luma-news",
        "bfl-news",
    }
    for slug in scraper_slugs:
        assert by_slug[slug].fetch_kind == "scraper", (
            f"{slug}: fetch_kind={by_slug[slug].fetch_kind!r} (期待: scraper)"
        )
    # Sakana AI は feed.xml なので RSS
    assert by_slug["sakana-ai"].fetch_kind == "rss"


def test_default_fetch_kind_is_rss() -> None:
    """既存 11 ソース (yaml に fetch_kind 未指定) は デフォルト 'rss'."""
    by_slug = {s.slug: s for s in load_sources()}
    rss_slugs = {
        "huggingface-blog",
        "google-research-blog",
        "microsoft-ai-news",
        "arxiv-cs-lg",
        "tldr-ai",
        "bens-bites",
        "latent-space",
        "windsurf-blog",
        "replit-blog",
        "midjourney-updates",
        "stockmark-blog",
    }
    for slug in rss_slugs:
        assert by_slug[slug].fetch_kind == "rss", (
            f"{slug}: fetch_kind={by_slug[slug].fetch_kind!r} (期待: rss)"
        )


# ---------------- Phase 2: tier フィールド ----------------


def test_all_sources_have_tier_in_range() -> None:
    """全ソースの tier が 1-5 の範囲内."""
    for s in load_sources():
        assert 1 <= s.tier <= 5, f"{s.slug}: tier={s.tier} は範囲外"


def test_official_sources_are_tier1() -> None:
    """公式リリース系は Tier 1."""
    by_slug = {s.slug: s for s in load_sources()}
    assert by_slug["huggingface-blog"].tier == 1
    assert by_slug["google-research-blog"].tier == 1
    assert by_slug["anthropic-news"].tier == 1


def test_arxiv_is_tier2() -> None:
    """arxiv は査読系で Tier 2."""
    by_slug = {s.slug: s for s in load_sources()}
    assert by_slug["arxiv-cs-lg"].tier == 2


def test_newsletter_is_tier3() -> None:
    """ニュースレターはキュレーションで Tier 3."""
    by_slug = {s.slug: s for s in load_sources()}
    assert by_slug["tldr-ai"].tier == 3
    assert by_slug["bens-bites"].tier == 3
    assert by_slug["latent-space"].tier == 3


def test_default_tier_when_missing(tmp_path: Path) -> None:
    """yaml に tier 無しなら 3 が default."""
    yaml_text = """
version: 1
sources:
  - slug: notier
    name: NoTier
    feed_url: https://e.com/feed
    site_url: https://e.com
    language: en
    category: release
    enabled: true
    fetch_policy:
      min_interval_seconds: 0
      max_items_per_fetch: 10
    license_note: ok
"""
    p = tmp_path / "notier.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    sources = load_sources(p)
    assert sources[0].tier == 3


def test_invalid_tier_raises(tmp_path: Path) -> None:
    """tier が 1-5 範囲外なら ValueError."""
    yaml_text = """
version: 1
sources:
  - slug: bad
    name: Bad
    feed_url: https://e.com/feed
    site_url: https://e.com
    language: en
    category: release
    tier: 99
    enabled: true
    fetch_policy:
      min_interval_seconds: 0
      max_items_per_fetch: 10
    license_note: ok
"""
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ValueError, match="tier"):
        load_sources(p)


def test_invalid_fetch_kind_raises(tmp_path: Path) -> None:
    """sources.yaml の fetch_kind が 'rss'/'scraper' 以外なら ValueError."""
    yaml_text = """
version: 1
sources:
  - slug: bad
    name: Bad
    feed_url: https://e.com/feed
    site_url: https://e.com
    language: en
    category: release
    fetch_kind: api
    enabled: true
    fetch_policy:
      min_interval_seconds: 0
      max_items_per_fetch: 10
    license_note: ok
"""
    p = tmp_path / "bad.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    with pytest.raises(ValueError, match="fetch_kind"):
        load_sources(p)


def test_load_blocked_real_yaml() -> None:
    blocked = load_blocked()
    assert isinstance(blocked, BlockedConfig)
    assert "jiji.com" in blocked.blocked_domains


def test_load_blocked_missing_returns_empty(tmp_path: Path) -> None:
    """存在しないファイルでは空の BlockedConfig を返す."""
    blocked = load_blocked(tmp_path / "doesnotexist.yaml")
    assert blocked.blocked_domains == frozenset()


def test_load_blocked_empty_file(tmp_path: Path) -> None:
    """空ファイルでも空の BlockedConfig を返す (例外を出さない)."""
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    blocked = load_blocked(p)
    assert blocked.blocked_domains == frozenset()


def test_load_sources_with_explicit_path(tmp_path: Path) -> None:
    yaml_text = """
version: 1
sources:
  - slug: t1
    name: Test 1
    feed_url: https://e.com/feed
    site_url: https://e.com
    language: en
    category: release
    enabled: true
    fetch_policy:
      min_interval_seconds: 1800
      max_items_per_fetch: 10
    license_note: ok
"""
    p = tmp_path / "src.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    sources = load_sources(p)
    assert len(sources) == 1
    assert sources[0].slug == "t1"
    assert sources[0].fetch_policy.min_interval_seconds == 1800


def test_load_sources_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_sources(tmp_path / "missing.yaml")
