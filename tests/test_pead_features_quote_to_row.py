"""PEAD/earnings features must survive the quote → ranked-row → outcome chain.

The premarket enrichment computes four earnings features and stamps them on
the QUOTE (`run_open_prep`): ``recent_eps_surprise_pct``,
``days_since_last_earnings``, ``days_to_next_earnings``,
``revenue_surprise_pct``. ``prepare_outcome_snapshot`` reads the first two
from the ranked ROW — but the scorer never carried them across, so the
outcome/FI columns were structurally ``None`` from the day they were
introduced (0/140 non-null across all July production outcome files), and the
other two had no reader at all. The FI evidence that the C2b comment says
should decide a future scorer weight could never accumulate.

These tests pin the full chain end-to-end so the edge cannot silently
disappear again. The fields are observe-only pass-throughs (no weight, not a
score input) — asserted here too.
"""
from __future__ import annotations

from datetime import date

from open_prep.outcomes import (
    FEATURE_KEYS,
    PASS_THROUGH_FEATURE_KEYS,
    prepare_outcome_snapshot,
)
from open_prep.scorer import filter_candidate, score_candidate

PEAD_FIELDS = {
    "recent_eps_surprise_pct": 12.5,
    "days_since_last_earnings": 9,
    "days_to_next_earnings": 82,
    "revenue_surprise_pct": -3.25,
}


def _quote(**extra: object) -> dict[str, object]:
    q: dict[str, object] = {
        "symbol": "PEAD",
        "price": 50.0,
        "previousClose": 48.0,
        "avgVolume": 2_000_000,
        "volume": 900_000,
        "name": "PEAD Test Corp",
    }
    q.update(extra)
    return q


def test_pead_fields_reach_the_ranked_row() -> None:
    fr = filter_candidate(_quote(**PEAD_FIELDS), bias=0.0)
    row = score_candidate(fr, bias=0.0)
    for key, value in PEAD_FIELDS.items():
        assert row.get(key) == value, f"{key} lost between quote and ranked row"


def test_pead_fields_missing_on_quote_stay_none_not_zero() -> None:
    """Absent data must stay ``None`` (not measured), never coerce to 0."""
    fr = filter_candidate(_quote(), bias=0.0)
    row = score_candidate(fr, bias=0.0)
    for key in PEAD_FIELDS:
        assert key in row, f"{key} key missing from row contract"
        assert row[key] is None, f"{key} must be None when the quote lacks it"


def test_pead_fields_flow_into_the_outcome_record() -> None:
    fr = filter_candidate(_quote(**PEAD_FIELDS), bias=0.0)
    row = score_candidate(fr, bias=0.0)
    record = prepare_outcome_snapshot([row], run_date=date(2026, 7, 27))[0]
    for key, value in PEAD_FIELDS.items():
        assert record.get(key) == value, f"{key} lost between row and outcome record"


def test_all_four_are_observe_only_pass_throughs() -> None:
    """Declared for FI but never weighted — the C2b contract."""
    for key in PEAD_FIELDS:
        assert key in FEATURE_KEYS, f"{key} missing from FEATURE_KEYS"
        assert key in PASS_THROUGH_FEATURE_KEYS, f"{key} must be pass-through (no weight)"


def test_pead_fields_do_not_change_the_score() -> None:
    """Observe-only: identical score with and without the fields."""
    base = score_candidate(filter_candidate(_quote(), bias=0.0), bias=0.0)
    with_fields = score_candidate(filter_candidate(_quote(**PEAD_FIELDS), bias=0.0), bias=0.0)
    assert with_fields["score"] == base["score"]
