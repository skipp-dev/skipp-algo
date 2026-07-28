"""Inference primitives package.

2026-07-28: the C3.1 public bootstrap API re-exports were removed together
with the stranded API itself (see ``smc_core/inference/bootstrap.py`` — same
REMOVED treatment as C4.1's permutation stack). The package now only hosts
the resampling primitives ``governance.family_significance`` imports directly.
"""
