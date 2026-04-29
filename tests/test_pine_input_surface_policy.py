"""Tests for input-surface reduction policy (ENG-WS6-02)."""
from __future__ import annotations

from scripts.pine_input_surface_policy import (
    INPUT_GROUP_POLICY,
    VISIBILITIES_REQUIRING_DISPLAY_NONE,
    InputVisibility,
    classify_group,
    evaluate_inputs,
)


def _inp(group: str | None, label: str, has_dn: bool) -> dict:
    return {"group": group, "label": label, "has_display_none": has_dn}


class TestClassify:
    def test_known_user_groups(self) -> None:
        assert classify_group("Hero Surface") is InputVisibility.USER_VISIBLE
        assert classify_group("Action") is InputVisibility.USER_VISIBLE

    def test_known_operator_groups(self) -> None:
        assert classify_group("Engine") is InputVisibility.OPERATOR_ONLY
        assert classify_group("Diagnostics") is InputVisibility.OPERATOR_ONLY

    def test_known_legacy_group(self) -> None:
        assert classify_group("Legacy") is InputVisibility.LEGACY

    def test_unknown_group(self) -> None:
        assert classify_group("totally-new-group") is None
        assert classify_group(None) is None
        assert classify_group("") is None


class TestEvaluate:
    def test_clean_surface_passes(self) -> None:
        inputs = [
            _inp("Hero Surface", "show_hero", False),
            _inp("Action", "verb_locale", False),
            _inp("Engine", "engine_seed", True),     # operator must be hidden
            _inp("Experimental", "lab_toggle", True),
            _inp("Legacy", "old_choch_window", True),
        ]
        v = evaluate_inputs(inputs)
        assert v.passes
        assert v.user_visible_count == 2
        assert v.isolated_count == 3
        assert v.unknown_group_count == 0

    def test_user_input_with_display_none_violates(self) -> None:
        inputs = [_inp("Hero Surface", "show_hero", True)]
        v = evaluate_inputs(inputs)
        assert not v.passes
        assert "Produktrelevanter Input" in v.violations[0].reason

    def test_operator_input_without_display_none_violates(self) -> None:
        inputs = [_inp("Engine", "engine_seed", False)]
        v = evaluate_inputs(inputs)
        assert not v.passes
        assert "operator_only-Input" in v.violations[0].reason

    def test_experimental_input_without_display_none_violates(self) -> None:
        inputs = [_inp("Experimental", "lab", False)]
        v = evaluate_inputs(inputs)
        assert not v.passes
        assert v.violations[0].expected_visibility is InputVisibility.EXPERIMENTAL

    def test_legacy_input_without_display_none_violates(self) -> None:
        inputs = [_inp("Legacy", "old", False)]
        v = evaluate_inputs(inputs)
        assert not v.passes
        assert v.violations[0].expected_visibility is InputVisibility.LEGACY

    def test_unknown_group_violates(self) -> None:
        inputs = [_inp("UnclassifiedGroup", "x", False)]
        v = evaluate_inputs(inputs)
        assert not v.passes
        assert v.unknown_group_count == 1
        assert "INPUT_GROUP_POLICY" in v.violations[0].reason

    def test_visible_count_smaller_than_total(self) -> None:
        # DoD: 'sichtbare Input-Flaeche ist deutlich kleiner als heute'.
        inputs = [
            _inp("Hero Surface", "x", False),
            _inp("Engine", "a", True),
            _inp("Engine", "b", True),
            _inp("Diagnostics", "c", True),
            _inp("Experimental", "d", True),
            _inp("Legacy", "e", True),
        ]
        v = evaluate_inputs(inputs)
        assert v.user_visible_count < len(inputs)
        assert v.user_visible_count <= v.isolated_count


class TestPolicyTable:
    def test_isolated_classes_known(self) -> None:
        assert set(VISIBILITIES_REQUIRING_DISPLAY_NONE) == {
            InputVisibility.OPERATOR_ONLY,
            InputVisibility.EXPERIMENTAL,
            InputVisibility.LEGACY,
        }

    def test_at_least_one_user_group_declared(self) -> None:
        user_groups = [g for g, v in INPUT_GROUP_POLICY.items()
                       if v is InputVisibility.USER_VISIBLE]
        assert len(user_groups) >= 3
