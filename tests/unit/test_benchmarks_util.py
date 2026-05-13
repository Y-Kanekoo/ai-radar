"""benchmarks/_util.py の URL 組み立てとリトライ (Phase 3)."""

from __future__ import annotations

import asyncio

import httpx

from ai_radar.crawler.benchmarks._util import (
    HF_DATASETS_SERVER,
    fetch_json_with_retry,
    fetch_text_with_retry,
    hf_resolve_url,
    hf_rows_url,
)


def test_hf_rows_url_encodes_dataset_slash() -> None:
    """``owner/repo`` のスラッシュは URL エンコードされる."""
    url = hf_rows_url(
        "lmarena-ai/leaderboard-dataset",
        config="text_style_control",
        split="latest",
        offset=0,
        length=5,
    )
    assert url.startswith(HF_DATASETS_SERVER + "/rows?")
    assert "dataset=lmarena-ai%2Fleaderboard-dataset" in url
    assert "config=text_style_control" in url
    assert "split=latest" in url
    assert "length=5" in url


def test_hf_resolve_url_default_revision_main() -> None:
    """revision 未指定なら main."""
    url = hf_resolve_url("mteb/results", path="paths.json")
    assert url == "https://huggingface.co/datasets/mteb/results/resolve/main/paths.json"


def test_hf_resolve_url_custom_revision() -> None:
    """revision を渡せばパスに反映される."""
    url = hf_resolve_url("mteb/results", path="foo.json", revision="abc123")
    assert "/resolve/abc123/" in url


def test_fetch_json_with_retry_success_first_try() -> None:
    """1 回目で 200 + 有効 JSON なら即返す."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [{"x": 1}]})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        data = asyncio.run(
            fetch_json_with_retry(
                "https://example.com/x",
                client=client,
                max_attempts=3,
                backoff_seconds=0.01,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert data == {"rows": [{"x": 1}]}


def test_fetch_json_with_retry_retries_on_501() -> None:
    """501 を 2 回返した後 200 → 3 回目で成功."""
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        if counter["n"] < 3:
            return httpx.Response(501)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        data = asyncio.run(
            fetch_json_with_retry(
                "https://example.com/x",
                client=client,
                max_attempts=3,
                backoff_seconds=0.01,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert data == {"ok": True}
    assert counter["n"] == 3


def test_fetch_json_with_retry_returns_none_on_permanent_failure() -> None:
    """全 attempt で 5xx なら None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        data = asyncio.run(
            fetch_json_with_retry(
                "https://example.com/x",
                client=client,
                max_attempts=2,
                backoff_seconds=0.01,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert data is None


def test_fetch_json_with_retry_returns_none_on_non_retryable_4xx() -> None:
    """404 は retry せず None."""
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        data = asyncio.run(
            fetch_json_with_retry(
                "https://example.com/x",
                client=client,
                max_attempts=3,
                backoff_seconds=0.01,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert data is None
    assert counter["n"] == 1  # retry されていない


def test_fetch_text_with_retry_success() -> None:
    """200 で text を返す."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>hi</html>")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    try:
        text = asyncio.run(
            fetch_text_with_retry(
                "https://example.com/page",
                client=client,
                max_attempts=2,
                backoff_seconds=0.01,
            )
        )
    finally:
        asyncio.run(client.aclose())
    assert text == "<html>hi</html>"
