"""Entry point: ``python -m newsstack_fmp.run``

Standalone polling loop.  For Streamlit integration, use
``newsstack_fmp.pipeline.poll_once()`` instead.

Environment variables control which sources are active:
    ENABLE_FMP=1              (default: on)
    ENABLE_BENZINGA_REST=0    (default: off)
    ENABLE_BENZINGA_WS=0      (default: off)
"""

from __future__ import annotations

import logging
import sys

from .config import Config
from .pipeline import run_pipeline


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    cfg = Config()
    logging.getLogger(__name__).info(
        "Active sources: %s", cfg.active_sources,
    )
    run_pipeline(cfg)


if __name__ == "__main__":
    main()
