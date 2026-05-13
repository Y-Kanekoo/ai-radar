"""HTML per-source scrapers (Phase 0.5).

各 scraper モジュールはトップレベルで `@register(slug)` を呼び出し、import 時に
parser を登録する. このパッケージを import すること自体が全 parser の登録になる.
"""

from __future__ import annotations

# 各 scraper モジュールを import することで `register()` を実行する.
# 並びは scrapers ディレクトリの ABC 順 = ソース slug の ABC 順.
from ai_radar.crawler.scrapers import (  # noqa: F401
    ai2,
    anthropic,
    bfl,
    cursor,
    elyza,
    hf_papers,
    kimi,
    luma,
)
