"""Phase E — SMT / Correlation Divergence Layer (scaffold).

Smart Money Theory (SMT) divergence occurs when two historically correlated
instruments form divergent swing structures simultaneously: one makes a higher
high (or lower low) while its correlated pair fails to confirm.  This divergence
signals institutional distribution or accumulation.

Current status
--------------
This module is a **scaffold** for Phase E.  The core data structures and known
pair list are defined here, but :func:`classify_smt_divergence` raises
``NotImplementedError`` until Phase E.0 (correlated-pair data feed in
``open_prep/realtime_signals.py``) is implemented.

Phase E.0 pre-requisite
-----------------------
The live engine (``open_prep/realtime_signals.py``) is currently single-symbol-
centric.  Before Phase E can produce live signals, the engine must ingest at
least the paired symbol's OHLC data concurrently.  Phase E.0 scopes that
data-ingest change separately; it may touch the urlopen / http ledgers and must
be justified in the relevant ``pin_registry.toml`` and test entries.

Known SMT pairs
---------------
+--------------+---------------+-------------------------------------------------+
| Base         | Correlated    | Rationale                                       |
+==============+===============+=================================================+
| XAUUSD       | XAGUSD        | Precious metals — historically r > 0.85         |
+--------------+---------------+-------------------------------------------------+
| BTCUSD       | ETHUSD        | Crypto — high beta correlation                  |
+--------------+---------------+-------------------------------------------------+
| US100        | US500         | Equity indices — divergence signals sector bias |
+--------------+---------------+-------------------------------------------------+
| EURUSD       | GBPUSD        | FX majors — divergence signals USD-specific flow|
+--------------+---------------+-------------------------------------------------+
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class SMTPair(NamedTuple):
    """A pair of instruments to monitor for SMT divergence."""

    base_symbol: str
    corr_symbol: str


#: Canonical list of instrument pairs monitored for SMT divergence.
#: Extend this list in Phase E.0 once the data feed is confirmed.
KNOWN_SMT_PAIRS: list[SMTPair] = [
    SMTPair("XAUUSD", "XAGUSD"),
    SMTPair("BTCUSD", "ETHUSD"),
    SMTPair("US100", "US500"),
    SMTPair("EURUSD", "GBPUSD"),
]


@dataclass(frozen=True, slots=True)
class SMTDivergenceResult:
    """SMT divergence descriptor.

    All fields are ``None`` / ``False`` / ``0.0`` until Phase E.0 is live.

    Parameters
    ----------
    pair_corr_window:
        Look-back bars used to compute the rolling correlation between base
        and correlated symbol.
    pair_corr_value:
        Rolling Pearson correlation coefficient, −1.0–1.0.
    smt_high_divergence:
        ``True`` when base makes a new higher high but correlated symbol
        fails to confirm (prints a lower high or equal high).
    smt_low_divergence:
        ``True`` when base makes a new lower low but correlated symbol
        fails to confirm (prints a higher low or equal low).
    smt_strength:
        0.0–1.0 composite divergence strength.  Combines the magnitude of
        the divergence with the rolling correlation level (high correlation
        → stronger signal when divergence occurs).
    """

    pair_corr_window: int
    pair_corr_value: float
    smt_high_divergence: bool
    smt_low_divergence: bool
    smt_strength: float


def classify_smt_divergence(  # noqa: D401
    *,
    base_symbol: str,
    corr_symbol: str,
    base_bars: object,
    corr_bars: object,
    window: int = 20,
) -> SMTDivergenceResult:
    """Classify SMT divergence between ``base_symbol`` and ``corr_symbol``.

    .. note::
        **Not yet implemented** — Phase E.0 (correlated-pair data feed) must be
        completed before this function can produce live results.

    Raises
    ------
    NotImplementedError
        Always, until Phase E.0 is merged and this scaffold is replaced.
    """
    raise NotImplementedError(
        "classify_smt_divergence is not yet implemented.  "
        "Complete Phase E.0 (correlated-pair data feed in "
        "open_prep/realtime_signals.py) before enabling ENABLE_SMT_DIVERGENCE."
    )
