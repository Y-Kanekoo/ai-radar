"""タグ付けエンジン. ルールを記事に適用してタグリストを返す.

設計:
- title/body を小文字化し、キーワードの部分一致でスコアを加算
- title 重み2、body 重み1 (TaggerConfig で変更可能)
- スコア >= threshold (既定2) のタグを候補とする
- requires_co_tag=True のタグは他タグが1つ以上ある場合のみ追加 (例: tooling)
- 共起ルール (if_any/if_all) で別タグを補完
- 最終的に max_tags (既定3) で打ち切り

Phase 2 追加:
- ``is_blocked_by_anti_tag``: 採用/イベント告知/sponsored 等を配信から除外
- ``detect_hype``: ハイプ語ヒット + ソース Tier 4-5 で警告フラグ
"""

from __future__ import annotations

from ai_radar.tagger.rules import TaggerConfig

# Phase 2: Tier 4-5 のソースのみハイプフィルタを適用する.
# 公式 (Tier 1-3) の "breakthrough" は普通に出るが、SNS/個人ブログの "breakthrough" は警戒.
HYPE_MIN_TIER = 4


def _score_tag(
    title_lc: str,
    body_lc: str,
    keywords: tuple[str, ...],
    weight_title: int,
    weight_body: int,
) -> tuple[int, set[str]]:
    """1タグについてのスコアとマッチしたキーワード集合を返す."""
    score = 0
    matched: set[str] = set()
    for keyword in keywords:
        if keyword in title_lc:
            score += weight_title
            matched.add(keyword)
        elif keyword in body_lc:
            score += weight_body
            matched.add(keyword)
    return (score, matched)


def assign_tags(
    title: str,
    body: str,
    config: TaggerConfig,
    source_slug: str | None = None,
) -> list[str]:
    """記事に対しタグリストを推論する.

    Args:
        title: 記事タイトル.
        body: 記事本文 (HTML 除去後を推奨).
        config: TaggerConfig.
        source_slug: ソースの slug. 与えると `source_tags` の固定タグが
            最優先で付与される (requires_co_tag バイパス).

    Returns:
        タグ名のリスト. ソース固定タグ→スコア降順 で並び、最大 `config.max_tags` 件.
        ルールにもソースにもマッチしない場合は空リスト.
    """
    title_lc = (title or "").lower()
    body_lc = (body or "").lower()
    combined = title_lc + " " + body_lc

    tag_scores: dict[str, int] = {}

    for rule in config.rules:
        score, _matched = _score_tag(
            title_lc,
            body_lc,
            rule.keywords,
            config.weight_title,
            config.weight_body,
        )
        if score >= config.threshold:
            tag_scores[rule.tag] = score

    # 共起ルール: title+body の生テキストに対して評価する.
    # ルールのキーワードと一致しない汎用語 (例: "test", "claude") も検出可能にするため.
    for co in config.co_occurrence:
        triggered = False
        if co.if_any and any(k in combined for k in co.if_any):
            triggered = True
        if co.if_all and all(k in combined for k in co.if_all):
            triggered = True
        if triggered:
            for added_tag in co.add:
                tag_scores.setdefault(added_tag, config.threshold)

    # ソース固定タグ (requires_co_tag バイパス、最優先で配置)
    forced: list[str] = list(config.get_source_tags(source_slug)) if source_slug else []

    if not tag_scores and not forced:
        return []

    rule_by_tag = {r.tag: r for r in config.rules}

    # final は forced で初期化. 同じタグはスキップする
    final: list[str] = list(forced)

    sorted_pairs = sorted(tag_scores.items(), key=lambda x: (-x[1], x[0]))
    primary: list[str] = []
    secondary: list[str] = []
    for tag, _score in sorted_pairs:
        if tag in final:
            continue
        rule = rule_by_tag.get(tag)
        if rule is not None and rule.requires_co_tag:
            secondary.append(tag)
        else:
            primary.append(tag)

    # primary を最大件数まで追加
    for tag in primary:
        if len(final) >= config.max_tags:
            break
        final.append(tag)

    # 共起前提タグは primary または forced が1つ以上あれば追加
    if final:
        for tag in secondary:
            if len(final) >= config.max_tags:
                break
            if tag not in final:
                final.append(tag)

    return final


# ---------------- Phase 2: anti_tags / hype 検出 ----------------


def is_blocked_by_anti_tag(title: str, body: str, config: TaggerConfig) -> bool:
    """記事タイトル/本文が anti_tags のいずれかにヒットすれば True.

    Anti-tag は配信除外対象 (採用、イベント告知、sponsored、求人 等).
    title または body の小文字化テキストへの部分一致で判定.

    Args:
        title: 記事タイトル.
        body: 記事本文 (HTML 除去後).
        config: TaggerConfig (`anti_tags` を参照).

    Returns:
        いずれかの anti_tag にヒットしたら True.
    """
    if not config.anti_tags:
        return False
    combined = (title or "").lower() + " " + (body or "").lower()
    return any(kw in combined for kw in config.anti_tags)


def detect_hype(
    title: str,
    body: str,
    source_tier: int,
    config: TaggerConfig,
) -> bool:
    """記事がハイプ表現を含むかを判定する (Phase 2).

    Tier 4-5 のソースで `hype_keywords` のいずれかが title/body にヒットすれば True.
    公式や査読系 (Tier 1-3) は普通に "breakthrough" 等を使うため、適用しない.

    Args:
        title: 記事タイトル.
        body: 記事本文 (HTML 除去後).
        source_tier: ソースの信頼度 Tier (1-5).
        config: TaggerConfig (`hype_keywords` を参照).

    Returns:
        Tier 4-5 + ハイプ語ヒットなら True.
    """
    if source_tier < HYPE_MIN_TIER:
        return False
    if not config.hype_keywords:
        return False
    combined = (title or "").lower() + " " + (body or "").lower()
    return any(kw in combined for kw in config.hype_keywords)
