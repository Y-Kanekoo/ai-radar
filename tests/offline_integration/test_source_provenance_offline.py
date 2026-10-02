"""合成HTML→parser→DB: 人気やソース査読情報を記事の査読主張に昇格しない."""

from __future__ import annotations

import socket
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from ai_radar.crawler.orchestrator import run_crawl
from ai_radar.crawler.scoring import compute_score
from ai_radar.crawler.scrapers.hf_papers import parse_hf_papers
from ai_radar.db import init_db
from ai_radar.sources import BlockedConfig, load_sources

FIXTURE = Path(__file__).parents[1] / "fixtures" / "provenance_sources.yaml"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network forbidden in offline integration test")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.mark.asyncio
@pytest.mark.parametrize("votes", ["0", "1", "999999"])
async def test_popularity_is_not_review_evidence(tmp_path: Path, votes: str) -> None:
    source = replace(load_sources(FIXTURE)[2], enabled=True)
    html = (
        '<article><h3><a href="/papers/2601.00001">Synthetic study</a></h3>'
        f'<div class="leading-none">{votes}</div></article>'
    ).encode()
    item = parse_hf_papers(html)[0]
    assert item.body == f"upvotes={votes}"
    assert source.provenance.review_status == "unknown"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "example.invalid"
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        assert request.url.path == "/papers"
        return httpx.Response(200, content=html)

    conn = init_db(tmp_path / "synthetic.db")
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await run_crawl(conn, [source], BlockedConfig(frozenset()), client=client)
        assert result.articles_added == 1
        assert result.errors == []
        row = dict(conn.execute("SELECT * FROM articles").fetchone())
        assert row["body"] == f"upvotes={votes}"
        assert row["snippet"] == f"upvotes={votes}"
        assert "review_status" not in row
        assert "peer_reviewed" not in str(dict(row))
        tier = conn.execute("SELECT tier FROM sources").fetchone()["tier"]
        assert compute_score(tier=tier, category="paper", age_seconds=0) == 1.0
        assert requests == ["/robots.txt", "/papers"]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_source_review_is_not_inherited_by_article(tmp_path: Path) -> None:
    source = replace(load_sources(FIXTURE)[1], enabled=True)
    assert source.provenance.review_status == "peer_reviewed"
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>Synthetic venue</title>
      <entry><id>editorial</id><title>Synthetic editorial</title>
      <link href="https://example.invalid/editorial"/><content>Editorial content</content>
      <published>2026-01-01T00:00:00Z</published></entry></feed>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "example.invalid"
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        assert request.url.path == "/venue"
        return httpx.Response(200, content=atom)

    conn = init_db(tmp_path / "synthetic.db")
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await run_crawl(conn, [source], BlockedConfig(frozenset()), client=client)
        assert result.articles_added == 1
        row = dict(conn.execute("SELECT * FROM articles").fetchone())
        assert row["title"] == "Synthetic editorial"
        assert "review_status" not in row
        assert "publication_venue" not in row
        assert "peer_reviewed" not in str(row)
    finally:
        conn.close()
