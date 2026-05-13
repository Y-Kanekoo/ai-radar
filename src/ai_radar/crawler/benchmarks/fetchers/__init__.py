"""benchmark fetcher パッケージ.

各 fetcher モジュールはトップレベルで `@register(slug)` を呼ぶ.
import 時の side-effect で全 fetcher が登録される.
"""

from __future__ import annotations

# 並びは slug の ABC 順 (registered_slugs() の安定化用).
from ai_radar.crawler.benchmarks.fetchers import (  # noqa: F401
    alpaca_eval,
    bigcodebench,
    github_trending,
    lmarena,
    mteb,
)
