"""Coverage for the active-signal lifecycle merge (audit P1 MED).

``RealtimeEngine._reconcile_new_signal`` decides whether a freshly-detected
signal upgrades, flips, dedupes, or newly appends against the active set — a
regression here could double-fire alerts or leave a stale LONG active after a
SHORT flip. The four branches are exercised directly (no full poll_once seeding
needed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from open_prep.realtime_signals import RealtimeEngine


@dataclass
class _Sig:
    symbol: str
    level: str
    direction: str
    expired: bool = False
    details: dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        return self.expired


def _engine(active: list[_Sig]) -> RealtimeEngine:
    import threading

    eng = RealtimeEngine.__new__(RealtimeEngine)
    eng._lock = threading.Lock()
    eng._active_signals = list(active)
    return eng


def _reconcile(eng: RealtimeEngine, sig: _Sig) -> list[_Sig]:
    new_signals: list = []
    eng._reconcile_new_signal(sig.symbol, sig, new_signals)
    return new_signals


def test_no_existing_signal_appends() -> None:
    eng = _engine([])
    new = _reconcile(eng, _Sig("NVDA", "A1", "LONG"))
    assert len(new) == 1 and new[0].symbol == "NVDA"


def test_level_upgrade_replaces_active() -> None:
    existing = _Sig("NVDA", "A1", "LONG")
    eng = _engine([existing])
    new = _reconcile(eng, _Sig("NVDA", "A0", "LONG"))  # A1 → A0 upgrade
    assert len(new) == 1 and new[0].level == "A0"
    # old active entry for the symbol was cleared
    assert all(s.symbol != "NVDA" for s in eng._active_signals)


def test_direction_flip_replaces_active() -> None:
    existing = _Sig("NVDA", "A0", "LONG")
    eng = _engine([existing])
    new = _reconcile(eng, _Sig("NVDA", "A0", "SHORT"))  # same level, opposite dir
    assert len(new) == 1 and new[0].direction == "SHORT"
    assert all(s.symbol != "NVDA" for s in eng._active_signals)


def test_same_level_same_direction_is_deduped() -> None:
    existing = _Sig("NVDA", "A0", "LONG")
    eng = _engine([existing])
    new = _reconcile(eng, _Sig("NVDA", "A0", "LONG"))  # duplicate → skip
    assert new == []
    # existing active signal is untouched
    assert eng._active_signals == [existing]


def test_lower_level_same_direction_is_deduped() -> None:
    existing = _Sig("NVDA", "A0", "LONG")
    eng = _engine([existing])
    new = _reconcile(eng, _Sig("NVDA", "A1", "LONG"))  # A1 is lower rank than A0
    assert new == []
    assert eng._active_signals == [existing]


def test_expired_active_is_ignored_and_new_appends() -> None:
    stale = _Sig("NVDA", "A0", "LONG", expired=True)
    eng = _engine([stale])
    new = _reconcile(eng, _Sig("NVDA", "A1", "LONG"))
    # expired active is not "existing" → the new signal appends
    assert len(new) == 1 and new[0].level == "A1"


def test_other_symbols_are_not_disturbed_on_replace() -> None:
    other = _Sig("AAPL", "A1", "LONG")
    nvda = _Sig("NVDA", "A1", "LONG")
    eng = _engine([other, nvda])
    _reconcile(eng, _Sig("NVDA", "A0", "LONG"))  # upgrade NVDA
    # AAPL active entry survives the NVDA replace
    assert any(s.symbol == "AAPL" for s in eng._active_signals)
    assert all(s.symbol != "NVDA" for s in eng._active_signals)


# ── Watchlist rotation ────────────────────────────────────────────────
# `_reconcile_new_signal` above only ever runs when a NEW signal arrives for a
# symbol. Nothing there retracts a signal whose symbol was dropped by a
# rotation, and expiry is wall-clock only (MAX_SIGNAL_AGE_SECONDS = 480) while
# `--reload-interval` defaults to 300 — so the two windows overlap and the
# retraction has to happen in `reload_watchlist` itself.


class _Tracker:
    """Stand-in for the per-symbol collaborators ``reload_watchlist`` prunes."""

    def __init__(self) -> None:
        self._prev: dict = {}
        self._streaks: dict = {}
        self._state: dict = {}
        self.pruned_to: set | None = None
        self.cleared = False

    def prune_stale(self, symbols: set) -> None:
        self.pruned_to = set(symbols)

    def clear(self) -> None:
        self.cleared = True


def _rotating_engine(active: list[_Sig], watchlist: list[str]) -> RealtimeEngine:
    """Engine wired just enough to run the real ``reload_watchlist``."""
    eng = _engine(active)
    eng._watchlist = [{"symbol": s} for s in watchlist]
    eng._load_watchlist = lambda: None  # watchlist injected, never read from disk
    for name in (
        "_last_prices", "_price_history", "_quote_hashes",
        "_vd_last_change_epoch", "_avg_vol_cache",
    ):
        setattr(eng, name, {})
    eng._delta_tracker = _Tracker()
    eng._hysteresis = _Tracker()
    eng._dynamic_cooldown = _Tracker()
    eng._technical_scorer = _Tracker()
    eng._databento_feed = None
    eng._quote_source = None
    return eng


def test_signal_is_retracted_when_its_symbol_leaves_the_watchlist() -> None:
    nvda = _Sig("NVDA", "A0", "LONG")
    aapl = _Sig("AAPL", "A1", "LONG")
    eng = _rotating_engine([nvda, aapl], watchlist=["AAPL"])
    eng.reload_watchlist()
    # NVDA is gone from the rotation, so its signal must not stay published
    assert [s.symbol for s in eng._active_signals] == ["AAPL"]


def test_a_still_watched_symbol_keeps_its_signal_across_a_rotation() -> None:
    nvda = _Sig("NVDA", "A0", "LONG")
    eng = _rotating_engine([nvda], watchlist=["NVDA", "AAPL"])
    eng.reload_watchlist()
    assert eng._active_signals == [nvda]


def test_an_empty_reload_does_not_clear_the_active_set() -> None:
    """A degraded snapshot must not read as "every symbol was dropped"."""
    nvda = _Sig("NVDA", "A0", "LONG")
    eng = _rotating_engine([nvda], watchlist=[])
    eng.reload_watchlist()
    assert eng._active_signals == [nvda]


def test_symbol_match_ignores_case_and_padding() -> None:
    sig = _Sig(" nvda ", "A0", "LONG")
    eng = _rotating_engine([sig], watchlist=["NVDA"])
    eng.reload_watchlist()
    assert eng._active_signals == [sig]
