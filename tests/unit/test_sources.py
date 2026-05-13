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


def test_loads_11_sources_from_real_yaml() -> None:
    """実際の config/sources.yaml が Phase 0 の 11 ソースで正常パース.

    Phase 0.5 (scraper layer 追加) 以降は 20+ ソースに増加予定. その時点で
    本テストの期待値を更新する.
    """
    sources = load_sources()
    assert len(sources) == 11


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
    """Phase 0 コアソースが含まれている."""
    slugs = {s.slug for s in load_sources()}
    must = {
        "huggingface-blog",
        "google-research-blog",
        "arxiv-cs-lg",
        "tldr-ai",
        "stockmark-blog",
    }
    missing = must - slugs
    assert not missing, f"必須ソースが欠落: {missing}"


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
