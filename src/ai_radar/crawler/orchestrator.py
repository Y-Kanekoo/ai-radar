"""クローラーの並列実行コーディネータ. fetch / parse / store を束ねる."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ai_radar.crawler.dedup import (
    find_cluster_id,
    find_cross_source_duplicate,
    find_similar_title,
    find_thread_id,
    is_known,
    is_known_by_normalized_url,
    next_cluster_id,
    next_thread_id,
)
from ai_radar.crawler.fetch import DEFAULT_TIMEOUT, RobotsCache, fetch_feed
from ai_radar.crawler.normalize import (
    compute_body_hash,
    make_snippet,
    normalize_published,
    normalize_url,
    strip_html,
)
from ai_radar.crawler.parse import parse_feed
from ai_radar.crawler.scraper import fetch_html, parse_html
from ai_radar.crawler.store import (
    ArticleRow,
    finish_crawl_run,
    get_source_fetch_state,
    insert_article,
    start_crawl_run,
    update_source_fetch_state,
    upsert_source,
)
from ai_radar.sources import BlockedConfig, SourceConfig
from ai_radar.tagger.engine import assign_tags
from ai_radar.tagger.rules import TaggerConfig, load_tagger_config

logger = logging.getLogger("ai_radar.crawler")


@dataclass
class CrawlResult:
    """`run_crawl()` の戻り値."""

    sources_processed: int
    articles_added: int
    errors: list[dict[str, object]]


def _is_blocked(url: str, blocked: BlockedConfig) -> bool:
    """URL のホストが blocked_domains に含まれるか (サブドメイン対応)."""
    netloc = urlparse(url).netloc.lower()
    if not netloc:
        return False
    return any(netloc == d or netloc.endswith("." + d) for d in blocked.blocked_domains)


async def _process_source(
    conn: sqlite3.Connection,
    source: SourceConfig,
    blocked: BlockedConfig,
    client: httpx.AsyncClient,
    robots: RobotsCache,
    tagger: TaggerConfig,
) -> tuple[int, dict[str, object] | None]:
    """1ソースを処理する. (追加件数, エラー情報 or None) を返す."""
    if _is_blocked(source.feed_url, blocked):
        logger.warning("%s: blocked_domain", source.slug)
        return (0, {"slug": source.slug, "reason": "blocked_domain"})

    source_id = upsert_source(conn, source)
    if not source.enabled:
        logger.debug("%s: enabled=False", source.slug)
        return (0, None)

    etag, last_modified, last_fetched_at = get_source_fetch_state(conn, source_id)

    # min_interval 制限: 前回取得から min_interval_seconds 未満なら今回はスキップ
    if last_fetched_at is not None:
        elapsed = int(time.time()) - last_fetched_at
        if elapsed < source.fetch_policy.min_interval_seconds:
            logger.debug(
                "%s: min_intervalスキップ (経過%ds < %ds)",
                source.slug,
                elapsed,
                source.fetch_policy.min_interval_seconds,
            )
            return (0, None)

    # robots.txt は実際にフェッチする直前に確認する (disabled / min_intervalスキップ時には不要)
    if not await robots.is_allowed(source.feed_url, client):
        logger.warning("%s: robots.txt Disallow", source.slug)
        return (0, {"slug": source.slug, "reason": "robots_disallow"})

    # Phase 0.5: fetch_kind で RSS/HTML を切り替える. 後段の dedup / tag / store は共通.
    if source.fetch_kind == "scraper":
        result = await fetch_html(
            source.feed_url,
            etag=etag,
            last_modified=last_modified,
            client=client,
        )
    else:
        result = await fetch_feed(
            source.feed_url,
            etag=etag,
            last_modified=last_modified,
            client=client,
        )

    if result.error:
        update_source_fetch_state(
            conn,
            source_id,
            etag=etag,
            last_modified=last_modified,
            success=False,
        )
        return (0, {"slug": source.slug, "reason": "fetch_error", "detail": result.error})

    if result.is_not_modified:
        update_source_fetch_state(
            conn,
            source_id,
            etag=etag,
            last_modified=last_modified,
            success=True,
        )
        logger.info("%s: 304 Not Modified", source.slug)
        return (0, None)

    if not result.is_modified or result.content is None:
        update_source_fetch_state(
            conn,
            source_id,
            etag=etag,
            last_modified=last_modified,
            success=False,
        )
        return (
            0,
            {"slug": source.slug, "reason": "unexpected_status", "status": result.status_code},
        )

    parsed = (
        parse_html(result.content, source.slug)
        if source.fetch_kind == "scraper"
        else parse_feed(result.content)
    )
    if parsed.bozo and not parsed.items:
        update_source_fetch_state(
            conn,
            source_id,
            etag=etag,
            last_modified=last_modified,
            success=False,
        )
        return (
            0,
            {"slug": source.slug, "reason": "parse_error", "detail": parsed.bozo_exception},
        )

    added = 0
    items = parsed.items[: source.fetch_policy.max_items_per_fetch]
    for item in items:
        if not item.guid or not item.url:
            continue
        if is_known(conn, source_id, item.guid):
            continue

        body_plain = strip_html(item.body)
        title_clean = item.title.strip()
        normalized = normalize_url(item.url)
        body_hash = compute_body_hash(item.body)
        published_at = normalize_published(item.published_struct)

        # ----- Phase 1 dedup 5層: 層1〜3 は重複判定 (skip), 層4〜5 はクラスタ ID 割り当て
        # 層1: URL 正規化マッチ
        if is_known_by_normalized_url(conn, normalized):
            continue
        # 層2: タイトル類似度 (>= 0.85) で 24h 窓内に類似記事があれば重複
        if find_similar_title(conn, title_clean, published_at) is not None:
            continue
        # 層3: 別ソースに同 body_hash がある場合は転載重複
        if find_cross_source_duplicate(conn, body_hash, source_id) is not None:
            continue

        # 層4: 引用元クラスタリング (title 類似 >= 0.9 で同 thread_id)
        thread_id = find_thread_id(conn, title_clean, published_at)
        if thread_id is None:
            thread_id = next_thread_id(conn)
        # 層5: 時系列クラスタリング (title 類似 >= 0.8 で同 cluster_id)
        cluster_id = find_cluster_id(conn, title_clean, published_at)
        if cluster_id is None:
            cluster_id = next_cluster_id(conn)

        article = ArticleRow(
            source_id=source_id,
            guid=item.guid,
            url=normalized,
            title=title_clean,
            snippet=make_snippet(item.body, max_chars=100),
            body_hash=body_hash,
            body=body_plain,
            author=item.author,
            published_at=published_at,
            tags=assign_tags(title_clean, body_plain, tagger, source_slug=source.slug),
            normalized_url=normalized,
            thread_id=thread_id,
            cluster_id=cluster_id,
        )
        if insert_article(conn, article):
            added += 1

    update_source_fetch_state(
        conn,
        source_id,
        etag=result.etag,
        last_modified=result.last_modified,
        success=True,
    )
    logger.info("%s: %d 件追加 (取得 %d 件)", source.slug, added, len(items))
    return (added, None)


async def run_crawl(
    conn: sqlite3.Connection,
    sources: list[SourceConfig],
    blocked: BlockedConfig,
    *,
    concurrency: int = 5,
    client: httpx.AsyncClient | None = None,
    tagger: TaggerConfig | None = None,
) -> CrawlResult:
    """全ソースを並列にクロールする.

    Args:
        conn: SQLite 接続. クローラー専用に開いたものを推奨.
        sources: 対象ソース.
        blocked: ブロックリスト.
        concurrency: 同時実行数. 5以下推奨 (相手サーバ負荷).
        client: 共有 AsyncClient. None なら関数内で生成する.
        tagger: タガー設定. None なら `config/tag_rules.yaml` から読む.

    Returns:
        CrawlResult.
    """
    run_id = start_crawl_run(conn)
    sem = asyncio.Semaphore(concurrency)
    robots = RobotsCache()
    tagger_config = tagger if tagger is not None else load_tagger_config()

    async def _process_with_sem(
        s: SourceConfig, c: httpx.AsyncClient
    ) -> tuple[int, dict[str, object] | None]:
        async with sem:
            return await _process_source(conn, s, blocked, c, robots, tagger_config)

    if client is None:
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
        ) as owned:
            tasks = [_process_with_sem(s, owned) for s in sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)
    else:
        tasks = [_process_with_sem(s, client) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    total_added = 0
    sources_processed = 0
    errors: list[dict[str, object]] = []
    for source, res in zip(sources, results, strict=True):
        if isinstance(res, BaseException):
            errors.append({"slug": source.slug, "reason": "exception", "detail": str(res)})
            continue
        added, err = res
        sources_processed += 1
        total_added += added
        if err is not None:
            errors.append(err)

    finish_crawl_run(
        conn,
        run_id,
        sources_processed=sources_processed,
        articles_added=total_added,
        errors=errors,
    )
    return CrawlResult(
        sources_processed=sources_processed,
        articles_added=total_added,
        errors=errors,
    )
