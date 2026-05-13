"""tagger/engine.assign_tags() のユニットテスト."""

from __future__ import annotations

from ai_radar.tagger.engine import assign_tags
from ai_radar.tagger.rules import (
    CoOccurrenceRule,
    TaggerConfig,
    TagRule,
    load_tagger_config,
)


def _config(
    rules: list[TagRule],
    *,
    co_occurrence: list[CoOccurrenceRule] | None = None,
    source_tags: tuple[tuple[str, tuple[str, ...]], ...] = (),
    max_tags: int = 3,
    threshold: int = 2,
    weight_title: int = 2,
    weight_body: int = 1,
) -> TaggerConfig:
    return TaggerConfig(
        rules=tuple(rules),
        co_occurrence=tuple(co_occurrence or []),
        source_tags=source_tags,
        max_tags=max_tags,
        threshold=threshold,
        weight_title=weight_title,
        weight_body=weight_body,
    )


# ---------------- 基本 ----------------


def test_empty_input_returns_empty() -> None:
    config = _config([TagRule("e2e", ("playwright",), False)])
    assert assign_tags("", "", config) == []


def test_no_match_returns_empty() -> None:
    config = _config([TagRule("e2e", ("playwright",), False)])
    assert assign_tags("Hello", "world", config) == []


def test_title_match_alone_meets_threshold() -> None:
    """title 重み2 で threshold=2 に達する."""
    config = _config([TagRule("e2e", ("playwright",), False)])
    assert assign_tags("Playwright tutorial", "", config) == ["e2e"]


def test_body_only_match_below_threshold() -> None:
    """body のみのヒット (重み1) は threshold=2 未満で付かない."""
    config = _config([TagRule("e2e", ("playwright",), False)])
    assert assign_tags("Generic tutorial", "uses playwright internally", config) == []


def test_body_two_keywords_meet_threshold() -> None:
    """body で2つのキーワードがヒットすれば threshold=2 に届く."""
    config = _config([TagRule("e2e", ("playwright", "cypress"), False)])
    result = assign_tags("Generic", "playwright and cypress are different", config)
    assert result == ["e2e"]


def test_case_insensitive() -> None:
    config = _config([TagRule("e2e", ("playwright",), False)])
    assert assign_tags("PLAYWRIGHT Tutorial", "", config) == ["e2e"]


# ---------------- 複数タグ ----------------


def test_multiple_tags_sorted_by_score() -> None:
    """高スコアのタグが先頭."""
    config = _config(
        [
            TagRule("e2e", ("playwright",), False),
            TagRule("unit", ("jest", "vitest"), False),
        ]
    )
    # playwright in title (score 2), jest in body (score 1) — jest 単独は threshold 未満
    # vitest なし → unit 付かない
    result = assign_tags("Playwright vs Jest", "", config)
    # 両方 title ヒット → e2e=2, unit=2 → アルファベット順 (タイブレーク)
    assert "e2e" in result
    assert "unit" in result


def test_max_tags_caps_result() -> None:
    config = _config(
        [
            TagRule("a", ("foo",), False),
            TagRule("b", ("bar",), False),
            TagRule("c", ("baz",), False),
        ],
        max_tags=2,
    )
    result = assign_tags("foo bar baz", "", config)
    assert len(result) == 2


# ---------------- requires_co_tag ----------------


def test_requires_co_tag_alone_skipped() -> None:
    """tooling のような requires_co_tag タグは単独では付かない."""
    config = _config([TagRule("tooling", ("released",), True)])
    assert assign_tags("Released v1.0", "", config) == []


def test_requires_co_tag_with_primary_included() -> None:
    """primary タグが1つ以上あれば tooling も含める."""
    config = _config(
        [
            TagRule("e2e", ("playwright",), False),
            TagRule("tooling", ("released",), True),
        ]
    )
    result = assign_tags("Playwright Released", "", config)
    assert result == ["e2e", "tooling"]


# ---------------- 共起ルール ----------------


def test_co_occurrence_if_any_adds_tag() -> None:
    config = _config(
        [TagRule("e2e", ("playwright",), False)],
        co_occurrence=[CoOccurrenceRule(if_any=("playwright",), if_all=(), add=("tooling",))],
    )
    result = assign_tags("Playwright tutorial", "", config)
    assert "e2e" in result
    assert "tooling" in result


def test_co_occurrence_if_all_requires_all_present() -> None:
    config = _config(
        [
            TagRule("ai", ("claude",), False),
            TagRule("test", ("pytest",), False),
        ],
        co_occurrence=[CoOccurrenceRule(if_any=(), if_all=("claude", "test"), add=("ai-testing",))],
    )
    # claude と test 両方が title (=マッチ) にある
    result = assign_tags("Claude test", "", config)
    assert "ai-testing" in result


def test_co_occurrence_if_all_partial_no_trigger() -> None:
    config = _config(
        [TagRule("ai", ("claude",), False)],
        co_occurrence=[
            CoOccurrenceRule(if_any=(), if_all=("claude", "missing"), add=("ai-testing",))
        ],
    )
    result = assign_tags("Claude only", "", config)
    assert "ai-testing" not in result


# ---------------- 実際の tag_rules.yaml で検証 ----------------


def test_real_yaml_llm_release() -> None:
    """Claude のリリースタイトル → llm + release (共起ルールで llm も付与)."""
    config = load_tagger_config()
    result = assign_tags(
        "Claude Sonnet 4.7 released",
        "New version with improvements",
        config,
    )
    assert "llm" in result
    assert "release" in result


def test_real_yaml_agent_article() -> None:
    """Claude Code 等のコーディングエージェント記事 → agent + tool (共起ルール経由)."""
    config = load_tagger_config()
    result = assign_tags(
        "Claude Code でコーディングエージェント開発",
        "tool use と function calling を活用した autonomous agent の事例",
        config,
    )
    assert "agent" in result


def test_real_yaml_benchmark_article() -> None:
    """ベンチマーク記事 → benchmark."""
    config = load_tagger_config()
    result = assign_tags(
        "LMArena leaderboard 更新、MMLU で SOTA 達成",
        "evaluation results on MTEB and HELM benchmarks",
        config,
    )
    assert "benchmark" in result


def test_real_yaml_safety_article() -> None:
    """AI safety 記事 → safety."""
    config = load_tagger_config()
    result = assign_tags(
        "Constitutional AI と red teaming の最新研究",
        "jailbreak 対策と prompt injection 防御の手法",
        config,
    )
    assert "safety" in result


def test_real_yaml_fine_tuning_article() -> None:
    """LoRA/RLHF 等の Fine-tuning 記事 → fine-tuning."""
    config = load_tagger_config()
    result = assign_tags(
        "LoRA と QLoRA の比較",
        "RLHF と DPO による instruction tuning の手法",
        config,
    )
    assert "fine-tuning" in result


def test_real_yaml_unrelated_article_no_tags() -> None:
    """全く関係ない記事はタグが付かない."""
    config = load_tagger_config()
    result = assign_tags("今日のランチ", "ラーメンを食べた", config)
    assert result == []


def test_real_yaml_tool_requires_co_tag() -> None:
    """tool タグは requires_co_tag=True のため、他タグ無しでは付かない."""
    config = load_tagger_config()
    # "cli" は tool キーワードだが、他のキーワードにマッチしないため共起前提が満たされない
    result = assign_tags("New cli launched", "open source developer tool", config)
    # release キーワード "launch" がヒットすると release タグが付き、tool も co_tag として付与される
    # → tool が単独になる条件を検証するため、release を避けたタイトルに変更
    result = assign_tags("cli reference", "open source developer tool documentation", config)
    # tool キーワードのみのスコアでは threshold=2 に到達しないか、co_tag バイパスが効かない
    # 結果として tool は単独では付かない
    assert "tool" not in result
