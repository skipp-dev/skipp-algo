"""Importing :mod:`scripts.smc_atomic_write` must not require ``pandas``.

Regression guard for Bug-Hunt 2026-05-01 Finding F-05.

Several CI jobs (e.g. ``c13-daily-cron`` step
``emit_public_calibration_report``) deliberately install only the
minimal IBKR-free dependency set and rely on ``atomic_write_text`` /
``atomic_write_json``. ``pandas`` is only referenced as a type
annotation in ``atomic_write_csv`` / ``atomic_write_parquet`` and must
remain ``TYPE_CHECKING``-gated so those minimal jobs can import the
module without a hard runtime dependency on pandas.

If a future refactor ever needs ``pandas`` at runtime here, either:
  1. add ``pandas`` to ``requirements.txt`` AND every workflow that
     imports this module, OR
  2. extract the pandas-dependent helpers into a separate module that
     callers opt into.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_smc_atomic_write_imports_without_pandas() -> None:
    """Run a fresh subprocess where ``pandas`` resolution raises ImportError."""
    code = (
        "import sys\n"
        "class _BlockPandas:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'pandas' or name.startswith('pandas.'):\n"
        "            raise ImportError('pandas is intentionally blocked for this test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _BlockPandas())\n"
        "sys.modules.pop('pandas', None)\n"
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('saw', r'{REPO_ROOT / 'scripts' / 'smc_atomic_write.py'}')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert callable(module.atomic_write_text)\n"
        "assert callable(module.atomic_write_json)\n"
        "assert callable(module.atomic_write_csv)\n"
        "assert callable(module.atomic_write_parquet)\n"
        "print('IMPORT_OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "scripts/smc_atomic_write.py raised at import time when pandas was "
        "blocked. Re-gate the pandas import behind `if TYPE_CHECKING:`.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "IMPORT_OK" in result.stdout, result.stdout
