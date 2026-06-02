"""EV-02 — frozen edge-hypothesis register integrity tests.

Guards the Phase 0 deliverable of the Edge-Validation Roadmap: every gate
``EventFamily`` carries exactly one pre-registered, falsifiable hypothesis
whose ``primary_metric`` is a metric the X2 PromotionGate actually
consumes. Lives in the fast (``not slow``) partition.
"""
from __future__ import annotations

import datetime as dt
from typing import get_args

import pytest

from governance.edge_hypotheses import (
    ALLOWED_PRIMARY_METRICS,
    REQUIRED_FIELDS,
    get_hypothesis,
    list_hypotheses,
    validate,
)
from governance.types import EventFamily

# get_args(EventFamily) -> the canonical gate families.
_FAMILIES = sorted(get_args(EventFamily))


def test_default_register_loads_and_is_non_empty() -> None:
    hyps = list_hypotheses()
    assert hyps, "edge_hypotheses.json must not be empty"


def test_register_validates() -> None:
    # validate() raises on any contract violation; success returns the list.
    assert validate()


def test_every_family_has_exactly_one_hypothesis() -> None:
    hyps = list_hypotheses()
    families = [h["family"] for h in hyps]
    assert sorted(families) == _FAMILIES
    assert len(families) == len(set(families)), "duplicate family entries"


@pytest.mark.parametrize("family", _FAMILIES)
def test_get_hypothesis_round_trip(family: str) -> None:
    hyp = get_hypothesis(family)
    assert hyp["family"] == family


@pytest.mark.parametrize("family", _FAMILIES)
def test_required_fields_present(family: str) -> None:
    hyp = get_hypothesis(family)
    for field in REQUIRED_FIELDS:
        assert field in hyp, f"{family}: missing {field}"
        assert hyp[field] not in (None, ""), f"{family}: empty {field}"


@pytest.mark.parametrize("family", _FAMILIES)
def test_primary_metric_is_gate_consumed(family: str) -> None:
    hyp = get_hypothesis(family)
    assert hyp["primary_metric"] in ALLOWED_PRIMARY_METRICS


@pytest.mark.parametrize("family", _FAMILIES)
def test_min_sample_n_is_positive_int(family: str) -> None:
    hyp = get_hypothesis(family)
    n = hyp["min_sample_n"]
    assert isinstance(n, int) and not isinstance(n, bool) and n > 0


@pytest.mark.parametrize("family", _FAMILIES)
def test_frozen_at_is_iso_date(family: str) -> None:
    hyp = get_hypothesis(family)
    # Falsifiability requires the claim to be frozen before the test —
    # an unparseable / future-only placeholder would defeat the purpose.
    parsed = dt.date.fromisoformat(hyp["frozen_at"])
    assert parsed <= dt.date.today(), f"{family}: frozen_at is in the future"
