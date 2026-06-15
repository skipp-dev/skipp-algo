"""Feature-flag SSOT (audit-L-1 R4, 2026-05-12).

Background
==========
Before this module, the ``ENABLE_OPRA_UOA`` flag was read at four
different call sites (`newsstack_fmp/config.py`, `open_prep/streamlit_monitor.py`
twice, `scripts/probe_providers.py`) using slightly different idioms:

  * ``os.getenv("ENABLE_OPRA_UOA", "1") == "1"``
  * ``os.environ.get("ENABLE_OPRA_UOA", "1").strip() == "1"``
  * ``os.getenv("ENABLE_OPRA_UOA", "1") != "1"`` (negated form)

The drift was real: the ``.strip()`` variants tolerated trailing whitespace
that the bare ``getenv`` variants rejected. An operator who exported
``ENABLE_OPRA_UOA="1 "`` (with a trailing space) would see the streamlit
panel render the OPRA path while the probe + config refused.

This module is the **single source of truth** for ``ENABLE_*`` env-var
feature flags. All call sites must import the helper rather than reading
``os.environ`` directly.

Convention:
    * Each flag is a single function ``is_<flag>_enabled() -> bool``.
    * The helper reads the env var on every call (cheap, no caching) so
      that runtime overrides via ``os.environ[...] = "0"`` take effect
      immediately. This matches the historical behaviour of the inline
      ``os.getenv(...) == "1"`` checks.
    * ``.strip()`` is applied uniformly so that ``"1 "``, ``" 1"`` and
      ``"\t1\n"`` all parse as enabled (matches the streamlit monitor's
      historical lenient behaviour, which is the safer default).

See ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`` \xa7R4.
"""

from __future__ import annotations

import os


def _bool_env(name: str, default: str = "1") -> bool:
    """Lenient bool read: trims whitespace, treats only ``"1"`` as enabled."""

    return os.environ.get(name, default).strip() == "1"


def is_opra_uoa_enabled() -> bool:
    """Return True iff ``ENABLE_OPRA_UOA`` is set to ``"1"`` (default ON).

    The flag gates the Databento OPRA.PILLAR options-flow ingestion path.
    When False, callers must fall back to the legacy Unusual Whales /
    dormant-feature path. Default is ``"1"`` so the new path is on by
    default; operators flip to ``"0"`` only to force the legacy fallback
    during incident investigation.
    """

    return _bool_env("ENABLE_OPRA_UOA", "1")


# ---------------------------------------------------------------------------
# newsstack_fmp feature flags (audit F-002 centralization, 2026-06-14)
# Previously read inline via ``os.getenv(...) == "1"`` in
# ``newsstack_fmp/config.py``.  Moved here so the SSOT contract is
# complete and the centralization guard test can enforce zero raw reads.
# ---------------------------------------------------------------------------


def is_fmp_enabled() -> bool:
    """Return True iff ``ENABLE_FMP`` is set to ``"1"`` (default ON)."""
    return _bool_env("ENABLE_FMP", "1")


def is_fmp_articles_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_ARTICLES`` is set to ``"1"`` (default ON)."""
    return _bool_env("ENABLE_FMP_ARTICLES", "1")


def is_benzinga_rest_enabled() -> bool:
    """Return True iff ``ENABLE_BENZINGA_REST`` is set to ``"1"`` (default OFF)."""
    return _bool_env("ENABLE_BENZINGA_REST", "0")


def is_benzinga_ws_enabled() -> bool:
    """Return True iff ``ENABLE_BENZINGA_WS`` is set to ``"1"`` (default OFF)."""
    return _bool_env("ENABLE_BENZINGA_WS", "0")


def is_tradingview_news_enabled() -> bool:
    """Return True iff ``ENABLE_TRADINGVIEW_NEWS`` is set to ``"1"`` (default OFF)."""
    return _bool_env("ENABLE_TRADINGVIEW_NEWS", "0")


def is_newsapi_ai_enabled() -> bool:
    """Return True iff ``ENABLE_NEWSAPI_AI`` is set to ``"1"`` (default ON)."""
    return _bool_env("ENABLE_NEWSAPI_AI", "1")


def is_uw_news_enabled() -> bool:
    """Return True iff ``ENABLE_UW_NEWS`` is set to ``"1"`` (default OFF).

    Unusual Whales /news/headlines endpoint.  Default-OFF because availability
    depends on UW plan tier; the DISABLED-pattern auto-suppresses on
    401/403/404 responses.
    """
    return _bool_env("ENABLE_UW_NEWS", "0")


def is_fmp_general_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_GENERAL`` is set to ``"1"`` (default ON)."""
    return _bool_env("ENABLE_FMP_GENERAL", "1")


def is_fmp_senate_trades_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_SENATE_TRADES`` is set to ``"1"`` (default OFF).

    Requires a dedicated FMP plan tier; DISABLED-pattern auto-suppresses.
    """
    return _bool_env("ENABLE_FMP_SENATE_TRADES", "0")


def is_fmp_house_trades_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_HOUSE_TRADES`` is set to ``"1"`` (default OFF).

    Requires a dedicated FMP plan tier; DISABLED-pattern auto-suppresses.
    """
    return _bool_env("ENABLE_FMP_HOUSE_TRADES", "0")


def is_fmp_8k_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_8K`` is set to ``"1"`` (default OFF).

    Requires a dedicated FMP plan tier; DISABLED-pattern auto-suppresses.
    """
    return _bool_env("ENABLE_FMP_8K", "0")


def is_fmp_13f_enabled() -> bool:
    """Return True iff ``ENABLE_FMP_13F`` is set to ``"1"`` (default OFF).

    FMP /sec-filings/13F-HR-latest.  Requires dedicated plan tier.
    """
    return _bool_env("ENABLE_FMP_13F", "0")
