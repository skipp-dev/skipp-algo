"""Sprint C3.1 — inference helpers (bootstrap, permutation).

See ``docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md`` (X1-X3 + C2.1-C12.1).
"""
from smc_core.inference.bootstrap import (
    BootstrapConfig,
    BootstrapResult,
    CIMethod,
    bootstrap_ci,
)

__all__ = ["BootstrapConfig", "BootstrapResult", "CIMethod", "bootstrap_ci"]
