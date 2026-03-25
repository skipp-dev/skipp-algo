from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.smc_microstructure_base_runtime import run_streamlit_micro_base_app


def main() -> None:
    run_streamlit_micro_base_app()


if __name__ == "__main__":
    main()