"""tagger/rules.py のユニットテスト."""

from __future__ import annotations

from pathlib import Path

from ai_radar.tagger.rules import (
    CoOccurrenceRule,
    TaggerConfig,
    TagRule,
    load_tagger_config,
)


def test_loads_real_tag_rules() -> None:
    """config/tag_rules.yaml が正常にパースできる."""
    config = load_tagger_config()
    assert isinstance(config, TaggerConfig)
    assert len(config.rules) >= 10


def test_keywords_are_lowercased() -> None:
    config = load_tagger_config()
    for rule in config.rules:
        for keyword in rule.keywords:
            assert keyword == keyword.lower(), f"{rule.tag}: {keyword!r} が小文字化されていない"


def test_critical_tags_present() -> None:
    """12個の AI 固定タグが全て定義されている."""
    config = load_tagger_config()
    expected = {
        "llm",
        "agent",
        "multimodal",
        "rag",
        "fine-tuning",
        "benchmark",
        "safety",
        "regulation",
        "paper",
        "release",
        "tool",
        "opinion",
    }
    actual = {r.tag for r in config.rules}
    missing = expected - actual
    assert not missing, f"必須タグが欠落: {missing}"


def test_tool_requires_co_tag() -> None:
    """tool タグは requires_co_tag=True (ai-radar)."""
    config = load_tagger_config()
    tool = next((r for r in config.rules if r.tag == "tool"), None)
    assert tool is not None
    assert tool.requires_co_tag is True


def test_opinion_requires_co_tag() -> None:
    """opinion タグも requires_co_tag=True (ai-radar)."""
    config = load_tagger_config()
    opinion = next((r for r in config.rules if r.tag == "opinion"), None)
    assert opinion is not None
    assert opinion.requires_co_tag is True


def test_defaults_loaded() -> None:
    config = load_tagger_config()
    assert config.max_tags == 4
    assert config.threshold == 2
    assert config.weight_title == 2
    assert config.weight_body == 1


def test_load_with_custom_yaml(tmp_path: Path) -> None:
    yaml_text = """
version: 1
defaults:
  max_tags: 5
  threshold: 3
  weight_title: 4
  weight_body: 2
rules:
  - tag: foo
    keywords: [Foo, BAR]
  - tag: bar
    keywords: [baz]
    requires_co_tag: true
co_occurrence:
  - if_any: [foo]
    add: [auto]
source_tags:
  src1: [foo, bar]
  src2: [auto]
"""
    p = tmp_path / "rules.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    config = load_tagger_config(p)
    assert config.max_tags == 5
    assert config.threshold == 3
    assert config.weight_title == 4
    assert config.weight_body == 2
    assert len(config.rules) == 2
    foo = config.rules[0]
    assert foo.tag == "foo"
    assert foo.keywords == ("foo", "bar")  # 小文字化済
    assert foo.requires_co_tag is False
    bar = config.rules[1]
    assert bar.requires_co_tag is True
    assert len(config.co_occurrence) == 1
    co = config.co_occurrence[0]
    assert isinstance(co, CoOccurrenceRule)
    assert co.if_any == ("foo",)
    assert co.add == ("auto",)
    assert config.get_source_tags("src1") == ("foo", "bar")
    assert config.get_source_tags("src2") == ("auto",)
    assert config.get_source_tags("unknown") == ()


def test_real_yaml_has_source_tags_for_ai_sources() -> None:
    """実際の tag_rules.yaml に Phase 0 主要ソースの source_tags が定義されている."""
    config = load_tagger_config()
    assert config.get_source_tags("huggingface-blog") == ("release",)
    assert config.get_source_tags("google-research-blog") == ("paper", "release")
    assert config.get_source_tags("arxiv-cs-lg") == ("paper",)
    assert config.get_source_tags("tldr-ai") == ("opinion",)
    assert config.get_source_tags("windsurf-blog") == ("release", "tool")
    assert config.get_source_tags("midjourney-updates") == ("release", "multimodal")


def test_empty_yaml_returns_empty_config(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("version: 1\n", encoding="utf-8")
    config = load_tagger_config(p)
    assert config.rules == ()
    assert config.co_occurrence == ()


def test_tag_rule_dataclass_is_frozen() -> None:
    import dataclasses

    import pytest

    rule = TagRule(tag="x", keywords=("a", "b"), requires_co_tag=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.tag = "y"  # type: ignore[misc]
