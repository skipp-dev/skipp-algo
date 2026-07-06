"""Tests for ``governance.magnitude_stage_policy`` (ADR-0023 Stage 2 arming).

Covers the SSOT policy file contract:

* the checked-in repo policy is loadable and arms exactly BOS+SWEEP;
* missing file → unarmed Stage-1 default (arming is opt-in);
* malformed file → ``ValueError`` (never silently disarm);
* invariant validation (stage values, k<=n, stage-1-must-be-unarmed);
* ``demote_family`` removes the family, appends an audit event, and drops
  back to Stage 1 when the armed set empties;
* save/load round-trip via the atomic writer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.magnitude_stage_policy import (
    DEFAULT_ARMED_PLANE,
    DEFAULT_POLICY_PATH,
    FAMILY_CLASSIFICATION,
    MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION,
    MagnitudeStagePolicy,
    classification_of,
    demote_family,
    load_policy,
    policy_to_dict,
    save_policy,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---- checked-in repo policy ----------------------------------------------


def test_repo_policy_file_exists_and_loads() -> None:
    policy = load_policy(_REPO_ROOT / DEFAULT_POLICY_PATH)
    assert policy.stage == 2
    assert policy.armed_families == frozenset({"BOS", "SWEEP"})
    assert policy.k == 3
    assert policy.n == 4
    # Every arming must be on the audit trail.
    armed_events = [h for h in policy.history if h.get("action") == "arm"]
    assert {e["family"] for e in armed_events} >= {"BOS", "SWEEP"}


# ---- load_policy ----------------------------------------------------------


def test_missing_file_resolves_to_unarmed_default(tmp_path: Path) -> None:
    policy = load_policy(tmp_path / "nope.json")
    assert policy == MagnitudeStagePolicy()
    assert policy.stage == 1
    assert policy.armed_families == frozenset()


def test_malformed_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "policy.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        load_policy(p)


def test_non_object_payload_raises(tmp_path: Path) -> None:
    p = tmp_path / "policy.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_policy(p)


def test_wrong_schema_version_raises(tmp_path: Path) -> None:
    p = tmp_path / "policy.json"
    p.write_text(
        json.dumps({"schema_version": 99, "stage": 1}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="schema_version"):
        load_policy(p)


def test_non_string_armed_families_raises(tmp_path: Path) -> None:
    p = tmp_path / "policy.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION,
                "stage": 2,
                "armed_families": [1, 2],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="armed_families"):
        load_policy(p)


# ---- invariants ------------------------------------------------------------


def test_stage1_with_armed_families_raises() -> None:
    with pytest.raises(ValueError, match="measure-only"):
        MagnitudeStagePolicy(stage=1, armed_families=frozenset({"BOS"}))


def test_invalid_stage_raises() -> None:
    with pytest.raises(ValueError, match="stage"):
        MagnitudeStagePolicy(stage=4)


def test_k_greater_than_n_raises() -> None:
    with pytest.raises(ValueError, match="k <= n"):
        MagnitudeStagePolicy(k=5, n=4)


# ---- demote_family ---------------------------------------------------------


def _armed_policy() -> MagnitudeStagePolicy:
    return MagnitudeStagePolicy(
        stage=2, armed_families=frozenset({"BOS", "SWEEP"})
    )


def test_demote_removes_family_and_records_history() -> None:
    p2 = demote_family(
        _armed_policy(), "BOS", reason="k-of-n regression", date="2026-06-15"
    )
    assert p2.armed_families == frozenset({"SWEEP"})
    assert p2.stage == 2  # still one armed family left
    assert p2.history[-1] == {
        "action": "demote",
        "family": "BOS",
        "reason": "k-of-n regression",
        "date": "2026-06-15",
    }


def test_demoting_last_family_drops_to_stage_1() -> None:
    p = MagnitudeStagePolicy(stage=2, armed_families=frozenset({"SWEEP"}))
    p2 = demote_family(p, "SWEEP", reason="r", date="2026-06-15")
    assert p2.stage == 1
    assert p2.armed_families == frozenset()


def test_demote_unarmed_family_raises() -> None:
    with pytest.raises(ValueError, match="not armed"):
        demote_family(_armed_policy(), "FVG", reason="r", date="2026-06-15")


def test_demote_does_not_mutate_input() -> None:
    p = _armed_policy()
    demote_family(p, "BOS", reason="r", date="2026-06-15")
    assert p.armed_families == frozenset({"BOS", "SWEEP"})


# ---- save/load round-trip --------------------------------------------------


def test_save_load_roundtrip(tmp_path: Path) -> None:
    p = MagnitudeStagePolicy(
        stage=2,
        armed_families=frozenset({"BOS"}),
        armed_plane="1D",
        history=({"action": "arm", "family": "BOS", "date": "2026-06-11"},),
    )
    path = tmp_path / "policy.json"
    save_policy(p, path)
    assert load_policy(path) == p
    # On-disk shape is the documented stable representation.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == policy_to_dict(p)
    assert payload["armed_families"] == ["BOS"]
    assert payload["armed_plane"] == "1D"


# ---- armed_plane (cross-plane non-demotion, 2026-07-06) --------------------


def test_armed_plane_defaults_to_15m() -> None:
    assert MagnitudeStagePolicy().armed_plane == DEFAULT_ARMED_PLANE == "15m"


def test_v1_policy_without_armed_plane_defaults_to_15m(tmp_path: Path) -> None:
    """Backward compat: a pre-2026-07 policy JSON without the field loads
    with the 15m plane its arming was judged on (no schema bump)."""
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": MAGNITUDE_STAGE_POLICY_SCHEMA_VERSION,
                "stage": 2,
                "armed_families": ["BOS", "SWEEP"],
                "k": 3,
                "n": 4,
            }
        ),
        encoding="utf-8",
    )
    assert load_policy(path).armed_plane == "15m"


def test_empty_armed_plane_raises() -> None:
    with pytest.raises(ValueError, match="armed_plane"):
        MagnitudeStagePolicy(armed_plane="")


def test_repo_policy_armed_plane_is_15m() -> None:
    """The checked-in arming rests on the 15m proof."""
    assert load_policy(_REPO_ROOT / DEFAULT_POLICY_PATH).armed_plane == "15m"


# ---- family classification (SWEEP reclassification, 2026-07-06) ------------


def test_family_classification_stance() -> None:
    assert classification_of("BOS") == "operational"
    assert classification_of("SWEEP") == "proof_of_concept_15m"
    assert classification_of("FVG") == "control"
    assert classification_of("OB") == "control"
    assert classification_of("UNKNOWN") == "unclassified"
    # SWEEP is reclassified but NOT de-armed — the proof + protection stand.
    assert set(FAMILY_CLASSIFICATION) == {"BOS", "SWEEP", "FVG", "OB"}
    assert "SWEEP" in load_policy(_REPO_ROOT / DEFAULT_POLICY_PATH).armed_families
