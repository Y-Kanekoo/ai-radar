"""ai-radar — AI/LLM領域の最新情報を集約するMCPサーバー兼RSSアグリゲーター."""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__", "main"]


def main() -> None:
    """`ai-radar` スクリプトと `python -m ai_radar` のエントリポイント.

    MCP サーバーを stdio で起動する. DB が存在しない場合はヒント付きエラーを
    stderr に出力して終了する.
    """
    from ai_radar.server import run_stdio

    run_stdio()
