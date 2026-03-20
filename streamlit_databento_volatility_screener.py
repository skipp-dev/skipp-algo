from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(PROJECT_ROOT))

from databento_volatility_screener import run_streamlit_app


def main() -> None:
	run_streamlit_app()


if __name__ == "__main__":
	main()