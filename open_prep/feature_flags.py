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
