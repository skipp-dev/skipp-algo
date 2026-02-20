"""Backward-compatible import shim.

Prefer importing from `open_prep.trade_cards`.
"""

from .trade_cards import build_trade_cards

__all__ = ["build_trade_cards"]
