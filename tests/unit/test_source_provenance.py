"""出所情報の契約: 査読・掲載先・人気・既存配信重みを混同しない."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_radar.crawler.scoring import compute_score, source_tier_score
from ai_radar.sources import SourceConfig, SourceProvenance, load_sources

FIXTURE = Path(__file__).parents[1] / "fixtures" / "provenance_sources.yaml"


def _load(tmp_path: Path, provenance: object) -> SourceConfig:
    data = yaml.safe_load(FIXTURE.read_text())
    data["sources"] = [data["sources"][0]]
    data["sources"][0]["provenance"] = provenance
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(data))
    return load_sources(path)[0]


def test_preprint_venue_and_popularity_are_independent() -> None:
    preprint, venue, popular = load_sources(FIXTURE)
    assert preprint.provenance.source_type == "preprint_repository"
    assert preprint.provenance.publication_venue is None
    assert preprint.provenance.review_status == "unknown"
    assert venue.provenance.publication_venue == "Example Conference 2026"
    assert venue.provenance.review_status == "peer_reviewed"
    assert venue.provenance.review_evidence_url == "https://example.invalid/review-policy"
    assert popular.provenance.source_type == "research_aggregator"
    assert popular.provenance.popularity_signal == "community_upvotes"
    assert popular.provenance.review_status == "unknown"
    assert popular.provenance.publication_venue is None
    assert popular.provenance.review_evidence_url is None


def test_venue_alone_does_not_confirm_review(tmp_path: Path) -> None:
    source = _load(tmp_path, {"publication_venue": "Example Conference 2026"})
    assert source.provenance.review_status == "unknown"


def test_legacy_sources_default_to_unknown(tmp_path: Path) -> None:
    source = _load(tmp_path, {})
    assert source.provenance.source_type == "unknown"
    assert source.provenance.review_status == "unknown"
    assert source.provenance.publication_venue is None
    assert source.provenance.popularity_signal == "none"


@pytest.mark.parametrize(
    "provenance",
    [
        None,
        [],
        "peer_reviewed",
        {"review_status": "peer_reviewed"},
        {"review_status": "peer_reviewed", "publication_venue": "Example Conference"},
        {"review_status": "peer_reviewed", "review_evidence_url": "https://example.invalid/policy"},
        {"review_status": "trusted"},
        {"source_type": "official_means_reviewed"},
        {"popularity_signal": "quality_guaranteed"},
        {"publication_venue": " "},
        {"publication_venue": 123},
        {"review_evidence_url": "javascript:alert(1)"},
        {"review_evidence_url": "https://"},
        {"review_evidence_url": " "},
        {"review_evidence_url": False},
        {"review_status": []},
        {"review_sttaus": "peer_reviewed"},
    ],
)
def test_invalid_provenance_is_rejected(tmp_path: Path, provenance: object) -> None:
    with pytest.raises(ValueError, match="provenance"):
        _load(tmp_path, provenance)


def test_provenance_never_changes_ranking() -> None:
    preprint, venue, popular = load_sources(FIXTURE)
    assert [source_tier_score(t) for t in range(1, 6)] == [1.0, 0.8, 0.7, 0.5, 0.3]
    assert [
        compute_score(tier=s.tier, category=s.category, age_seconds=0)
        for s in [preprint, venue, popular]
    ] == [0.8, 0.8, 1.0]


def test_registry_claims_are_conservative() -> None:
    sources = {s.slug: s for s in load_sources()}
    arxiv = sources["arxiv-cs-lg"]
    popular = sources["hf-papers"]
    assert arxiv.provenance.source_type == "preprint_repository"
    assert arxiv.provenance.review_status == "unknown"
    assert arxiv.provenance.publication_venue is None
    assert popular.provenance.source_type == "research_aggregator"
    assert popular.provenance.popularity_signal == "community_upvotes"
    assert popular.provenance.review_status == "unknown"
    assert "品質保証" not in popular.license_note
    assert arxiv.tier == 2
    assert popular.tier == 1


def test_direct_construction_enforces_review_evidence() -> None:
    with pytest.raises(ValueError, match="provenance"):
        SourceProvenance(review_status="peer_reviewed", publication_venue="Example Conference")


def test_missing_provenance_is_backward_compatible(tmp_path: Path) -> None:
    data = yaml.safe_load(FIXTURE.read_text())
    del data["sources"][0]["provenance"]
    path = tmp_path / "legacy.yaml"
    path.write_text(yaml.safe_dump(data))
    assert load_sources(path)[0].provenance == SourceProvenance()
