"""RL-Execution layer (Sprint C12).

Production-ready scaffolding for the order-execution and sizing pipeline that
sits *downstream* of the regel- + ML-based setup detection. Heavy backends
(``stable_baselines3``, ``gymnasium``, ``torch``) are optional; deterministic
baselines (TWAP, VWAP, fixed-fraction sizing) and the Almgren-Chriss
calibrator + execution simulator are pure-numpy and always available.

Live-data onboarding is a dataset swap: build a ``TradeBlotter`` from the C8
outcome stream, fit ``AlmgrenChrissCalibrator``, plug it into
``ExecutionEnv`` and either run a baseline (TWAP/VWAP) or a learned agent
through ``HardConstraintLayer.guard_action(...)`` /
``HardConstraintLayer.guard_size_fraction(...)``. See ``rl/README.md``.
"""
from rl.types import (
    ExecutionAction,
    ExecutionState,
    SlippageEstimate,
    TradeRecord,
    TradeBlotter,
)

__all__ = [
    "ExecutionAction",
    "ExecutionState",
    "SlippageEstimate",
    "TradeRecord",
    "TradeBlotter",
]
