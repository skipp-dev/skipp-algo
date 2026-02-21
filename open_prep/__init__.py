"""Utilities for US-open breakout candidate preparation.

This package combines macro-event awareness, candidate ranking,
and optional trade-card generation.
"""

from .bea import build_bea_audit_payload
from .macro import macro_bias_score, macro_bias_with_components
from .news import build_news_scores
from .screen import rank_candidates
from .trade_cards import build_trade_cards

__all__: list[str] = [
	"build_bea_audit_payload",
	"build_news_scores",
	"build_trade_cards",
	"macro_bias_score",
	"macro_bias_with_components",
	"rank_candidates",
]
