"""Preset questions for the Terminal AI Insights tab.

Historical note (wire-or-remove, 2026-07-21): this module used to carry a
full OpenAI query engine (``query_llm``, ``assemble_context``, response
cache). That path had no production caller — all Terminal LLM egress goes
through the private Signals Producer, which uses ``terminal_fmp_insights``
— so the dead engine was removed to stop it drifting against the live one.
"""

from __future__ import annotations

PRESET_QUESTIONS: list[tuple[str, str]] = [
    ("📊 Market Pulse", "Give a concise market pulse summary based on the current news feed. Highlight the dominant sentiment, most-mentioned tickers, and any notable theme shifts."),
    ("🔥 Top Movers", "Which tickers have the strongest positive or negative sentiment signals right now? List the top 5 bullish and top 5 bearish, with their scores and key headlines."),
    ("⚠️ Risk Signals", "Identify any risk signals, red flags, or negative catalysts in the current feed. Focus on high-impact items like earnings misses, regulatory actions, downgrades, or sector-wide concerns."),
    ("🏗️ Sector Themes", "What are the dominant sector themes in the current news cycle? Infer sector/industry from tickers and headlines, and highlight cross-sector signals."),
    ("💡 Trade Ideas", "Based on the current sentiment data and any available technicals, suggest high-conviction trade ideas with rationale. Include both long and short opportunities. Provide at least 5 ideas (up to 10) when there are enough tickers with strong scores (|score| >= 0.3). For each idea cite the supporting article headlines with their source links."),
    ("🔮 Outlook", "What is the likely near-term direction based on the current news flow? Consider sentiment momentum, volume of coverage, and any macro signals."),
]
