"""GitHub Trending スクレイパー (Phase 3).

データソース: ``https://github.com/trending`` の HTML (公式 API はないため scraping).
huchenme/github-trending-api は 2026-05 時点で死亡確認のため使わない.

設計:
- ``since=daily`` のみ取得 (weekly/monthly は別 snapshot にして拡張可能だが Phase 3 では daily に絞る).
- ``language`` パラメータは指定しない (AI 領域に直結する言語は無いため全言語スキャン).
- AI/LLM 関連リポは、description / repo 名に AI キーワードが含まれるものをフィルタ.
  キーワード: llm, gpt, agent, transformer, embedding, rag, ai-, mcp, sora, claude,
  whisper, diffusion, langchain 等. Phase 4 でリアクション学習に置き換える前提.

DOM 構造 (2026-05 確認):
- 各リポは ``article.Box-row``
- ``h2.h3 a`` の ``href="/owner/repo"``
- 説明文は ``p.col-9.color-fg-muted``
- 言語は ``span[itemprop="programmingLanguage"]``
- Stars は ``a[href$="/stargazers"]`` のテキスト
- 今期 Stars は ``span.d-inline-block.float-sm-right`` のテキスト ("123 stars today")
"""

from __future__ import annotations

import logging
import re
import time

import httpx
from bs4 import BeautifulSoup

from ai_radar.crawler.benchmarks import BenchmarkEntry, BenchmarkSnapshot, register
from ai_radar.crawler.benchmarks._util import fetch_text_with_retry

logger = logging.getLogger("ai_radar.benchmarks.github_trending")

TRENDING_URL = "https://github.com/trending?since=daily"
TOP_N = 25
SLUG = "github_trending_daily"
DISPLAY_NAME = "GitHub Trending (daily, AI-filtered)"

# AI/LLM に関連するリポ名 / description キーワード (lower-case 比較).
# Phase 3 はキーワード固定. Phase 4 でリアクション学習に置き換える.
AI_KEYWORDS = (
    "llm",
    "gpt",
    "agent",
    "transformer",
    "embedding",
    "rag",
    "ai-",
    "mcp",
    "diffusion",
    "langchain",
    "vector",
    "claude",
    "whisper",
    "stable-diffusion",
    "vllm",
    "ollama",
    "openai",
    "anthropic",
    "hugging",
    "fine-tun",
    "multimodal",
    "neural",
    "deeplearn",
    "deep-learn",
)


def _is_ai_related(name: str, description: str) -> bool:
    """リポ名 or description に AI キーワードが含まれるか判定."""
    haystack = f"{name} {description}".lower()
    return any(kw in haystack for kw in AI_KEYWORDS)


def _parse_int_with_commas(text: str) -> int:
    """``"1,234"`` のような表記を int に. 失敗で 0."""
    cleaned = re.sub(r"[^0-9]", "", text or "")
    return int(cleaned) if cleaned else 0


def _parse_trending(html: str) -> list[BenchmarkEntry]:
    """trending HTML から AI 関連リポを抽出して BenchmarkEntry リストに."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[BenchmarkEntry] = []

    for art in soup.select("article.Box-row"):
        link = art.select_one("h2 a")
        if link is None:
            continue
        href = (link.get("href") or "").strip()
        if not href.startswith("/"):
            continue
        repo_full = href.lstrip("/")  # owner/repo
        if "/" not in repo_full:
            continue

        desc_tag = art.select_one("p")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        if not _is_ai_related(repo_full, description):
            continue

        lang_tag = art.select_one('span[itemprop="programmingLanguage"]')
        language = lang_tag.get_text(strip=True) if lang_tag else ""

        # Stars 総数: stargazers リンクのテキスト
        stars = 0
        star_link = art.select_one('a[href$="/stargazers"]')
        if star_link is not None:
            stars = _parse_int_with_commas(star_link.get_text(strip=True))

        # 今期 (today) Stars
        today_stars = 0
        today_tag = art.select_one("span.float-sm-right")
        if today_tag is not None:
            today_stars = _parse_int_with_commas(today_tag.get_text(strip=True))

        payload: dict[str, str] = {
            "url": f"https://github.com/{repo_full}",
            "description": description[:300],
            "language": language,
            "stars": str(stars),
            "stars_today": str(today_stars),
        }
        entries.append(
            BenchmarkEntry(
                rank=len(entries) + 1,
                identifier=repo_full,
                score=float(today_stars or stars),
                payload=payload,
            )
        )
        if len(entries) >= TOP_N:
            break

    # 元の trending 順 = i 昇順 を保つ (AI フィルタ後の rank を 1.. で振り直し済み)
    return entries


@register(SLUG)
async def fetch_github_trending(client: httpx.AsyncClient | None = None) -> BenchmarkSnapshot:
    """GitHub Trending (daily) を取得し、AI 関連リポを snapshot 化する."""
    html = await fetch_text_with_retry(TRENDING_URL, client=client)
    if not html:
        logger.warning("GitHub Trending fetch 失敗")
        return BenchmarkSnapshot(
            source_slug=SLUG,
            category="trend",
            captured_at=int(time.time()),
            entries=(),
            display_name=DISPLAY_NAME,
        )

    entries = _parse_trending(html)
    return BenchmarkSnapshot(
        source_slug=SLUG,
        category="trend",
        captured_at=int(time.time()),
        entries=tuple(entries),
        display_name=DISPLAY_NAME,
    )
