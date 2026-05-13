"""benchmarks 共通ヘルパー.

- HuggingFace Datasets Server API のクエリ組み立て.
- 短い retry/backoff. HF の `rows` API は dataset auto-conversion 中に
  501 LockedDatasetTimeoutError を返すことがあるため、production cron では
  リトライで吸収する.
- 共通 User-Agent.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote, urlencode

import httpx

from ai_radar import __version__

logger = logging.getLogger("ai_radar.benchmarks")

HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"
USER_AGENT = f"ai-radar/{__version__} (+https://github.com/Y-Kanekoo/ai-radar)"
DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
RETRYABLE_STATUSES = frozenset({500, 501, 502, 503, 504})


def hf_rows_url(
    dataset: str,
    *,
    config: str,
    split: str,
    offset: int = 0,
    length: int = 100,
) -> str:
    """Datasets Server の rows API URL を組み立てる.

    Args:
        dataset: ``"owner/repo"`` 形式. URL エンコードする.
        config: dataset config 名.
        split: ``"latest"`` / ``"full"`` / ``"train"`` 等.
        offset: 取得開始 offset.
        length: 1 ≤ length ≤ 100 (HF API 仕様).

    Returns:
        完全な URL.
    """
    qs = urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        },
        quote_via=quote,
    )
    return f"{HF_DATASETS_SERVER}/rows?{qs}"


def hf_resolve_url(dataset: str, *, path: str, revision: str = "main") -> str:
    """HF dataset の raw ファイル URL を組み立てる.

    Args:
        dataset: ``"owner/repo"``.
        path: dataset 内のパス. 例: ``"paths.json"``.
        revision: ブランチ / commit. デフォルト main.

    Returns:
        ``https://huggingface.co/datasets/<owner>/<repo>/resolve/<rev>/<path>``.
    """
    return f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{path}"


async def fetch_json_with_retry(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
    max_attempts: int = 3,
    backoff_seconds: float = 5.0,
    headers: dict[str, str] | None = None,
) -> dict | list | None:
    """JSON を取得する. 一時的な 5xx / network エラーは指数バックオフで retry.

    Args:
        url: 取得先.
        client: 共有 httpx.AsyncClient. None なら関数内で生成.
        timeout: 1 リクエストのタイムアウト.
        max_attempts: 最大試行回数 (>= 1).
        backoff_seconds: 1 回目の retry までの待機. 以降 ``× 2`` で増える.
        headers: 追加ヘッダ. None なら DEFAULT_HEADERS のみ.

    Returns:
        パース済み JSON (dict or list). 永続失敗で None.
    """
    h = dict(DEFAULT_HEADERS)
    if headers:
        h.update(headers)

    own = client is None
    used = client if client is not None else httpx.AsyncClient(timeout=timeout)
    try:
        wait = backoff_seconds
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await used.get(url, headers=h)
            except httpx.HTTPError as e:
                logger.warning("fetch 失敗 attempt=%d url=%s err=%s", attempt, url, e)
                if attempt == max_attempts:
                    return None
                await asyncio.sleep(wait)
                wait *= 2
                continue

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as e:
                    logger.warning("JSON パース失敗 url=%s err=%s", url, e)
                    return None

            if resp.status_code in RETRYABLE_STATUSES and attempt < max_attempts:
                logger.info(
                    "一時的エラー status=%d attempt=%d url=%s, %.1fs 待機",
                    resp.status_code,
                    attempt,
                    url,
                    wait,
                )
                await asyncio.sleep(wait)
                wait *= 2
                continue

            logger.warning(
                "fetch 失敗 status=%d url=%s body=%r", resp.status_code, url, resp.text[:200]
            )
            return None
        return None
    finally:
        if own:
            await used.aclose()


async def fetch_text_with_retry(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
    max_attempts: int = 3,
    backoff_seconds: float = 5.0,
    headers: dict[str, str] | None = None,
) -> str | None:
    """HTML/テキストを取得する. リトライ方針は ``fetch_json_with_retry`` と同じ."""
    h = dict(DEFAULT_HEADERS)
    h["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
    if headers:
        h.update(headers)

    own = client is None
    used = (
        client if client is not None else httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    )
    try:
        wait = backoff_seconds
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await used.get(url, headers=h)
            except httpx.HTTPError as e:
                logger.warning("fetch 失敗 attempt=%d url=%s err=%s", attempt, url, e)
                if attempt == max_attempts:
                    return None
                await asyncio.sleep(wait)
                wait *= 2
                continue

            if resp.status_code == 200:
                return resp.text

            if resp.status_code in RETRYABLE_STATUSES and attempt < max_attempts:
                logger.info(
                    "一時的エラー status=%d attempt=%d url=%s, %.1fs 待機",
                    resp.status_code,
                    attempt,
                    url,
                    wait,
                )
                await asyncio.sleep(wait)
                wait *= 2
                continue

            logger.warning("fetch 失敗 status=%d url=%s", resp.status_code, url)
            return None
        return None
    finally:
        if own:
            await used.aclose()
