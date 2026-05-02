"""Shared CI / CLI logging bootstrap.

Audit marker: F-V5-A1-2 / F-CI-O1 (2026-05-01).

Why this exists
---------------
Long-running entry-point scripts invoked from ``.github/workflows/`` are
expected to surface progress with ``logger.info(...)`` calls. Without an
explicit root-logger configuration those messages are dropped by Python's
default ``WARNING``-only handler — leading to the silent-failure mode where
a 60-minute pipeline run produces zero log output before runner eviction.

The 2026-05-01 V5 audit caught this for ``databento_production_export.main``
and the per-script fix was hard-coded inline (F-V5-A1). This module is the
shared helper so the same fix can be applied to ~20 sibling entry points
without duplicating the ``basicConfig`` boilerplate.

Usage (in any entry-point script)
---------------------------------
At the top of the file, after the docstring / ``from __future__`` line::

    try:
        from scripts._logging_init import init_cli_logging
    except ImportError:  # script-style invocation: `python scripts/X.py`
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]

Then call ``init_cli_logging()`` as the first line of ``main()`` (preferred,
keeps test imports side-effect-free) or inside the ``if __name__ ==
"__main__":`` block.

Idempotence
-----------
``init_cli_logging`` is a no-op when the root logger already has handlers
attached. This protects test harnesses, REPL sessions, and downstream
wrappers that configure logging themselves.
"""
from __future__ import annotations

import logging
import sys

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def init_cli_logging(level: int = logging.INFO) -> None:
    """Configure the root logger for CI / CLI output.

    Parameters
    ----------
    level:
        Root logger level. Defaults to ``logging.INFO`` because the CI
        observability contract is that progress messages from long-running
        pipelines must reach the GHA log stream.
    """
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=level,
        format=_DEFAULT_FORMAT,
        stream=sys.stderr,
    )
