"""sources.yaml / blocked.yaml のロードとデータクラス定義.

YAML を frozen dataclass にロードする層. クローラーや MCP からはこの層を経由する.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

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
class SourceProvenance:
    """発見元の出所情報。記事単位の査読判定・品質保証ではない。

    publication_venue は掲載先が確認できた場合だけ記録する。発見サイト名と
    論文の掲載先は別物。peer_reviewed は掲載先と明示的な根拠URLを必要とするが、
    URLの存在だけでは証拠の内容を検証できないため、設定者が根拠を確認する。
    これらの値を個々の記事へ継承したり、配信スコアに利用したりしない。
    """

    source_type: str = "unknown"
    publication_venue: str | None = None
    review_status: str = "unknown"
    review_evidence_url: str | None = None
    popularity_signal: str = "none"

    def __post_init__(self) -> None:
        enums = {
            "source_type": {
                "unknown",
                "blog",
                "preprint_repository",
                "research_aggregator",
                "journal",
                "proceedings",
                "newsletter",
            },
            "review_status": {"unknown", "not_peer_reviewed", "peer_reviewed"},
            "popularity_signal": {"none", "community_upvotes"},
        }
        for name, allowed in enums.items():
            value = getattr(self, name)
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f"provenance.{name}: 不正な値 {value!r}")
        for name in ("publication_venue", "review_evidence_url"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"provenance.{name}: 空でない文字列または null が必要")
        if self.review_evidence_url is not None:
            url = urlsplit(self.review_evidence_url)
            if url.scheme not in {"http", "https"} or not url.hostname:
                raise ValueError("provenance.review_evidence_url: HTTP(S) URL が必要")
        if self.review_status == "peer_reviewed" and (
            self.publication_venue is None or self.review_evidence_url is None
        ):
            raise ValueError("provenance: peer_reviewed には掲載先と査読根拠URLが必要")


@dataclass(frozen=True)
class SourceConfig:
    """1ソースの定義 (sources.yaml の1エントリ).

    fetch_kind="rss" (デフォルト) は feedparser 経路、"scraper" は
    `crawler.scrapers` に登録された per-source HTML parser を使う.

    tier (Phase 2): 既存配信優先度 1-5。査読・正しさ・品質の証拠ではない。
        Discord 配信スコアの第1因子。yaml 未指定なら 3。
    provenance: 発見元の説明。DB/記事へ暗黙継承せず、スコアと独立。
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
    # Phase 2: 既存配信優先度。数値/既定値は維持し、査読とは分離。
    tier: int = 3
    provenance: SourceProvenance = field(default_factory=SourceProvenance)


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
        provenance_data = entry.get("provenance", {})
        if not isinstance(provenance_data, dict):
            raise ValueError(f"{entry.get('slug')!r}: provenance は mapping が必要")
        try:
            provenance = SourceProvenance(**provenance_data)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{entry.get('slug')!r}: provenance: {exc}") from exc
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
                provenance=provenance,
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
