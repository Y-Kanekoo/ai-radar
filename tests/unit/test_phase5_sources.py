"""Phase 5 の設定・日本語フィード・音声付きRSSを通信なしで検証する。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from ai_radar.crawler.normalize import strip_html
from ai_radar.crawler.orchestrator import run_crawl
from ai_radar.crawler.parse import parse_feed
from ai_radar.db import init_db
from ai_radar.sources import BlockedConfig, load_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "phase5"
SOURCE_CASES = [
    ("zenn-llm", "zenn.xml", "ja", "jp", 4),
    ("zenn-generative-ai", "zenn.xml", "ja", "jp", 4),
    ("qiita-llm", "qiita.xml", "ja", "jp", 4),
    ("qiita-generative-ai", "qiita.xml", "ja", "jp", 4),
    ("hatena-ai", "hatena.xml", "ja", "jp", 5),
    ("cognitive-revolution", "cognitive_revolution.xml", "en", "newsletter", 3),
]


@pytest.mark.parametrize("slug,fixture,language,category,tier", SOURCE_CASES)
def test_phase5_source_config(
    slug: str, fixture: str, language: str, category: str, tier: int
) -> None:
    """実設定を読み、既存のカテゴリ・Tier・RSS経路で有効化される。"""
    source = next(source for source in load_sources() if source.slug == slug)
    assert source.language == language
    assert source.category == category
    assert source.tier == tier
    assert source.enabled
    assert source.fetch_kind == "rss"
    assert source.feed_url.startswith("https://")
    assert source.site_url
    assert source.fetch_policy.min_interval_seconds >= 21600
    assert source.fetch_policy.max_items_per_fetch > 0
    assert "2026-10-31" in source.license_note
    assert "robots.txt" in source.license_note
    assert (FIXTURES / fixture).is_file()


@pytest.mark.parametrize(
    "fixture,title,url,body,author",
    [
        (
            "zenn.xml",
            "ローカルLLMの評価方法",
            "https://zenn.dev/test_author/articles/local-llm",
            "日本語モデルを比較する手順。",
            "テスト著者",
        ),
        (
            "qiita.xml",
            "生成AIで検索を組み立てる",
            "https://qiita.com/test_author/items/rag-example",
            "検索結果を使って日本語で回答する。",
            "テスト著者",
        ),
        (
            "hatena.xml",
            "AI研究の新しい評価指標",
            "https://example.com/ai-research",
            "日本語で読む研究動向。",
            None,
        ),
        (
            "cognitive_revolution.xml",
            "Evaluating language models with researchers",
            "https://www.cognitiverevolution.ai/test-evaluation/",
            "言語モデルの評価について対談する。",
            "テスト司会者",
        ),
    ],
)
def test_phase5_feed_fields(
    fixture: str, title: str, url: str, body: str, author: str | None
) -> None:
    """RSS 2.0・Atom・RDFの日本語、日時、著者、記事リンクを維持する。"""
    parsed = parse_feed((FIXTURES / fixture).read_bytes())
    assert not parsed.bozo
    item = parsed.items[0]
    assert item.guid
    assert item.title == title
    assert item.url == url
    assert strip_html(item.body) == body
    assert item.author == author
    assert item.published_struct == (2026, 10, 31, 9, 0, 0)


def test_podcast_without_page_uses_audio_enclosure() -> None:
    """記事リンクを優先し、リンク・GUIDがない場合も音声URLで識別する。"""
    items = parse_feed((FIXTURES / "cognitive_revolution.xml").read_bytes()).items
    assert len(items) == 3
    assert items[0].guid == "episode-with-page"
    assert items[0].url == "https://www.cognitiverevolution.ai/test-evaluation/"
    assert items[1].guid == "episode-without-page"
    assert items[1].url == "https://example.com/audio/robotics.mp3"
    assert items[2].guid == items[2].url == "https://example.com/audio/tools.mp3"


def test_image_enclosure_is_not_an_article_link() -> None:
    """画像だけのenclosureを記事URLとして採用しない。"""
    content = (FIXTURES / "zenn.xml").read_text(encoding="utf-8")
    content = content.replace(
        "<link>https://zenn.dev/test_author/articles/local-llm</link>", ""
    ).replace('isPermaLink="true"', 'isPermaLink="false"')
    assert parse_feed(content).items[0].url == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("slug,fixture,language,category,tier", SOURCE_CASES)
async def test_phase5_crawl_stores_and_deduplicates(
    tmp_path: Path, slug: str, fixture: str, language: str, category: str, tier: int
) -> None:
    """実設定からDB保存・再取り込みの重複排除まで行い、音声は取得しない。"""
    source = next(source for source in load_sources() if source.slug == slug)
    source = replace(source, fetch_policy=replace(source.fetch_policy, min_interval_seconds=0))
    content = (FIXTURES / fixture).read_bytes()
    expected = parse_feed(content).items
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        assert str(request.url) == source.feed_url
        return httpx.Response(200, content=content)

    conn = init_db(tmp_path / "articles.db")
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await run_crawl(conn, [source], BlockedConfig(frozenset()), client=client)
            second = await run_crawl(conn, [source], BlockedConfig(frozenset()), client=client)
        assert first.sources_processed == 1
        assert first.errors == second.errors == []
        assert first.articles_added == len(expected)
        assert second.articles_added == 0
        rows = conn.execute("SELECT * FROM articles ORDER BY id").fetchall()
        for row, item in zip(rows, expected, strict=True):
            assert row["guid"] == item.guid
            assert row["title"] == item.title
            assert row["body"] == strip_html(item.body)
            assert row["author"] == item.author
            assert row["published_at"] is not None
            assert row["url"] == item.url.rstrip("/")
        stored = conn.execute("SELECT language, category, tier FROM sources").fetchone()
        assert tuple(stored) == (language, category, tier)
        assert len(requests) == 4  # 各クロールでrobots.txtとフィードを1回ずつ取得
    finally:
        conn.close()
