"""Helper for flushing progress streams in long-running CLI scripts.

Extracted 2026-05-13 (Phase P5.4 A3) from inline duplications in 4 sibling
``_progress`` callbacks:

* ``scripts/databento_preopen_fast.py``
* ``scripts/generate_smc_micro_base_from_databento.py``
* ``scripts/databento_production_export.py``
* ``scripts/smc_microstructure_base_runtime.py``

Without explicit flushes after each progress log, GHA SIGTERM/SIGKILL drops
the last 4-8KB of buffered stderr/stdout and hides the dominant bottleneck
step in D-profiles.

The companion module :mod:`scripts._logging_init` configures
``basicConfig(stream=sys.stderr)`` via ``init_cli_logging()``; this helper
covers both streams defensively in case ``progress_callback`` or other
writers also use stdout.
"""

from __future__ import annotations

import sys


def flush_progress_streams() -> None:
    """Flush stderr first (logger), then stdout (defensive).

    Order matters: stderr carries the canonical ``logger.info`` output from
    ``init_cli_logging()``-configured handlers; stdout is a defensive flush
    in case a ``progress_callback`` or other writer emits there.
    """
    sys.stderr.flush()
    sys.stdout.flush()
