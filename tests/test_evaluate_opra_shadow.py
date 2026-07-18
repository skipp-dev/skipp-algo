from scripts.evaluate_opra_shadow import evaluate, wilson_interval


def _row(session: int, *, success: bool | None = True):
    return {
        "session": f"2026-07-{session:02d}",
        "observed_at": f"2026-07-{session:02d}T14:30:00+00:00",
        "data_age_seconds": 1.0,
        "definition_known": True,
        "aggressor_signed": True,
        "duplicate": False,
        "gap": False,
        "ablation": {"premium": True, "aggressor": True, "cluster": False, "full": True},
        "outcome_success": success,
        "shadow_only": True,
    }


def test_wilson_interval_is_bounded() -> None:
    interval = wilson_interval(8, 10)
    assert interval is not None
    assert 0.0 <= interval[0] < 0.8 < interval[1] <= 1.0


def test_fewer_than_seven_sessions_is_insufficient() -> None:
    report = evaluate([_row(day) for day in range(1, 7)])
    assert report["decision"] == "insufficient_evidence"
    assert report["minimum_session_gate_met"] is False


def test_seven_sessions_with_outcomes_is_ready_for_human_review() -> None:
    report = evaluate([_row(day) for day in range(1, 8)])
    assert report["decision"] == "ready_for_human_review"
    assert report["ablations"]["full"]["confidence_interval_95"] is not None
    assert report["time_slices"] == {"open": 7}


def test_missing_outcomes_never_becomes_zero_lift() -> None:
    report = evaluate([_row(day, success=None) for day in range(1, 8)])
    assert report["decision"] == "insufficient_evidence"
    assert report["ablations"]["full"]["success_rate"] is None
