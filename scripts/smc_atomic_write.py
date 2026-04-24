"""Atomic dataframe writes for the SMC microstructure pipeline.

Audit finding A-1 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24): the microstructure
runtime previously called ``DataFrame.to_parquet`` / ``DataFrame.to_csv``
directly on the destination path. A crash mid-write left a truncated file
behind that propagated silently downstream (Pine export, calibration,
Streamlit UI). The repository already uses the ``tempfile + os.replace``
pattern in ``plan_2_8_history_rotate`` and ``f2_*`` modules; this helper
generalises it for the microstructure pipeline.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

__all__ = ["atomic_write_parquet", "atomic_write_csv"]


def _atomic_write(df: pd.DataFrame, target: Path, suffix: str, writer_name: str, **kwargs: Any) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=suffix, dir=str(target.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        getattr(df, writer_name)(tmp_path, **kwargs)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_parquet(df: pd.DataFrame, target: str | os.PathLike[str], **kwargs: Any) -> None:
    """Write ``df`` to ``target`` as parquet via tempfile + os.replace."""
    _atomic_write(df, Path(target), suffix=".parquet.tmp", writer_name="to_parquet", **kwargs)


def atomic_write_csv(df: pd.DataFrame, target: str | os.PathLike[str], **kwargs: Any) -> None:
    """Write ``df`` to ``target`` as CSV via tempfile + os.replace."""
    _atomic_write(df, Path(target), suffix=".csv.tmp", writer_name="to_csv", **kwargs)
