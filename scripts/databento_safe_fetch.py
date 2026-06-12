"""Databento safe-fetch helpers (F-V4-E1).

Wrappers around ``client.timeseries.get_range`` that swallow the most common
"data not yet available" errors and convert them into a structured ``status``
return so callers can emit a GitHub Actions ``::warning::`` annotation and
``exit 0`` instead of failing a pipeline run.

This was extracted from the inline guard in
``scripts/databento_preopen_fast.py`` (the original site of the pattern) after
the 2026-05-01 audit found three other workflows that hit
``HTTP/422 data_start_after_available_end`` without a guard
(open-prep-outcome-backfill, backfill_live_outcomes, etc).

The module deliberately does **not** import ``databento`` at module top level
so it can be unit-tested without the SDK installed; exception detection is by
string-match on the lowercased exception message, which is what the existing
guard in ``databento_preopen_fast`` already does.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Status tokens returned by safe_get_range. Keep strings stable — callers
# branch on them for telemetry.
STATUS_OK = "ok"
STATUS_SKIPPED_DATA_AFTER_END = "skipped_data_start_after_end"
STATUS_SKIPPED_OTHER_422 = "skipped_other_422"

# Substrings that indicate the requested window precedes available data.
# Lowercased, matched as substrings on str(exc).lower().
_DATA_AFTER_END_MARKERS: tuple[str, ...] = (
    "data_start_after_available_end",
    "after the available end",
)

# Substrings that indicate Databento HTTP 422 client error in general.
_OTHER_422_MARKERS: tuple[str, ...] = (
    "http 422",
    "http/422",
    "status 422",
    "bentoclienterror",
)


def _classify(exc: BaseException) -> str:
    """Classify a Databento exception into one of the STATUS_* tokens.

    Returns STATUS_OK only as a default for unexpected non-422 errors that the
    caller should re-raise; safe_get_range itself does the re-raise.
    """
    text = str(exc).lower()
    for marker in _DATA_AFTER_END_MARKERS:
        if marker in text:
            return STATUS_SKIPPED_DATA_AFTER_END
    for marker in _OTHER_422_MARKERS:
        if marker in text:
            return STATUS_SKIPPED_OTHER_422
    return STATUS_OK  # sentinel for "not classified, re-raise"


def _emit_actions_warning(message: str) -> None:
    """Emit a GitHub Actions ``::warning::`` annotation when running in CI."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # Annotation syntax: ::warning::message
        # No file/line — this is a runtime data-availability warning, not a
        # source-code issue.
        sys.stdout.write(f"::warning::{message}\n")
        sys.stdout.flush()


def safe_get_range(
    client: Any,
    *,
    dataset: str,
    schema: str,
    symbols: Any,
    start: str,
    end: str,
    **kwargs: Any,
) -> tuple[Any | None, str]:
    """Call ``client.timeseries.get_range`` with structured 422 handling.

    Parameters mirror the upstream Databento API. ``client`` must have a
    ``timeseries.get_range(...)`` callable; no other interface is assumed (so
    fakes are trivial in tests).

    Returns:
        ``(store, STATUS_OK)`` on success.
        ``(None, STATUS_SKIPPED_DATA_AFTER_END)`` when the requested window
            precedes available data — emits ``::warning::`` and returns
            normally so the caller can ``return 0`` from main().
        ``(None, STATUS_SKIPPED_OTHER_422)`` for other 422 client errors —
            same warning + return-zero contract.

    Other exceptions are re-raised unchanged so they fail loudly.
    """
    try:
        store = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            start=start,
            end=end,
            **kwargs,
        )
        return store, STATUS_OK
    except Exception as exc:
        status = _classify(exc)
        if status == STATUS_SKIPPED_DATA_AFTER_END:
            msg = (
                f"Databento data not yet available for {dataset}/{schema} "
                f"{start}->{end}: {exc}. Skipping (exit 0)."
            )
            logger.warning(msg)
            _emit_actions_warning(msg)
            return None, STATUS_SKIPPED_DATA_AFTER_END
        if status == STATUS_SKIPPED_OTHER_422:
            msg = (
                f"Databento HTTP 422 for {dataset}/{schema} "
                f"{start}->{end}: {exc}. Skipping (exit 0)."
            )
            logger.warning(msg)
            _emit_actions_warning(msg)
            return None, STATUS_SKIPPED_OTHER_422
        # Unclassified — re-raise so the pipeline still fails loudly on real
        # errors (auth, network, schema mismatch, etc.).
        raise
