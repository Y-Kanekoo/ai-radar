"""sources.yaml / blocked.yaml のロードとデータクラス定義.

YAML を frozen dataclass にロードする層. クローラーや MCP からはこの層を経由する.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# リポジトリルート (src/ai_radar/sources.py から3階層上)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_SOURCES_PATH = _REPO_ROOT / "config" / "sources.yaml"
DEFAULT_BLOCKED_PATH = _REPO_ROOT / "config" / "blocked.yaml"


@dataclass(frozen=True)
class FetchPolicy:
    """1ソースの取得方針."""

    min_interval_seconds: int
    max_items_per_fetch: int


@dataclass(frozen=True)
class SourceConfig:
    """1ソースの定義 (sources.yaml の1エントリ).

    fetch_kind="rss" (デフォルト) は feedparser 経路、"scraper" は
    `crawler.scrapers` に登録された per-source HTML parser を使う.

    tier (Phase 2): 信頼度ティア 1-5.
        1 = 公式 (anthropic.com / arxiv.org 等)
        2 = 査読系 (The Information / MIT TR 等)
        3 = キュレーション (TLDR / Ben's Bites 等)
        4 = 個人 (Substack / Medium / HN 等)
        5 = SNS拡散・まとめ・自動翻訳
        Discord 配信スコアの第1因子. yaml 未指定なら 3.
    """

    slug: str
    name: str
    feed_url: str
    site_url: str | None
    language: str
    category: str
    enabled: bool
    fetch_policy: FetchPolicy
    license_note: str
    # Phase 0.5: scraper サポート. 旧 yaml との後方互換のためデフォルト "rss"
    fetch_kind: str = "rss"
    # Phase 2: 信頼度ティア (1=公式, 5=SNS). yaml 未指定なら 3.
    tier: int = 3


@dataclass(frozen=True)
class BlockedConfig:
    """ブロックリストの定義 (blocked.yaml)."""

    blocked_domains: frozenset[str]


def load_sources(path: Path = DEFAULT_SOURCES_PATH) -> list[SourceConfig]:
    """sources.yaml を読みロードする.

    Args:
        path: YAMLパス. デフォルトは `config/sources.yaml`.

    Returns:
        SourceConfig のリスト. 入力順序を保つ.

    Raises:
        FileNotFoundError: ファイルが存在しない.
        KeyError: 必須キーが欠ける.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources: list[SourceConfig] = []
    for entry in data.get("sources", []):
        fp = entry.get("fetch_policy", {})
        fetch_kind = entry.get("fetch_kind", "rss")
        if fetch_kind not in {"rss", "scraper"}:
            raise ValueError(
                f"{entry.get('slug')!r}: 不正な fetch_kind {fetch_kind!r} "
                f"(rss | scraper のいずれか)"
            )
        tier = int(entry.get("tier", 3))
        if not 1 <= tier <= 5:
            raise ValueError(f"{entry.get('slug')!r}: 不正な tier {tier!r} (1〜5 のいずれか)")
        sources.append(
            SourceConfig(
                slug=entry["slug"],
                name=entry["name"],
                feed_url=entry["feed_url"],
                site_url=entry.get("site_url"),
                language=entry["language"],
                category=entry["category"],
                enabled=bool(entry.get("enabled", True)),
                fetch_policy=FetchPolicy(
                    min_interval_seconds=int(fp.get("min_interval_seconds", 3600)),
                    max_items_per_fetch=int(fp.get("max_items_per_fetch", 30)),
                ),
                license_note=entry.get("license_note", ""),
                fetch_kind=fetch_kind,
                tier=tier,
            )
        )
    return sources


def load_blocked(path: Path = DEFAULT_BLOCKED_PATH) -> BlockedConfig:
    """blocked.yaml を読みロードする. ファイル不在時は空のBlockedConfig.

    Args:
        path: YAMLパス. デフォルトは `config/blocked.yaml`.

    Returns:
        BlockedConfig.
    """
    if not path.exists():
        return BlockedConfig(blocked_domains=frozenset())
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    domains = frozenset(
        entry["domain"].lower()
        for entry in (data.get("blocked_domains") or [])
        if entry.get("domain")
    )
    return BlockedConfig(blocked_domains=domains)
