"""Tests for the WS1-FT-04 TV-validation stage normalization.

Pins:

- the new ``classify_tv_validation_stage`` helper maps each known
  post-release failure code to a stable stage label,
- the helper carves out input-tab visibility (PREFLIGHT_FAILED) and pure
  auth failures from the release-blocking set,
- the ``post_release_validation`` gate carries a ``tv_validation_stage``
  block when it fails,
- and the runner unconditionally downgrades a soft-only TV gate to
  ``blocking=False`` even outside ``--ci-mode``.
"""
from __future__ import annotations

from unittest import mock

from scripts.run_smc_release_gates import (
    _run_post_release_validation_gate,
    _tv_gate_is_soft_only,
    classify_tv_validation_stage,
)


def _gate_with(failure_codes: list[str]) -> dict:
    return {
        "name": "post_release_validation",
        "status": "fail",
        "details": {
            "failures": [{"code": c} for c in failure_codes],
        },
    }


class TestStageClassification:
    def test_no_failures_is_ok_and_not_blocking(self) -> None:
        result = classify_tv_validation_stage({"details": {"failures": []}})
        assert result["stage"] == "ok"
        assert result["per_code"] == []
        assert result["release_blocking"] is False

    def test_compile_add_runtime_is_blocking(self) -> None:
        result = classify_tv_validation_stage(_gate_with(["TARGET_FAILED"]))
        assert result["stage"] == "compile_add_runtime"
        assert result["release_blocking"] is True

    def test_manifest_publish_is_blocking(self) -> None:
        result = classify_tv_validation_stage(
            _gate_with(["VERSION_MISMATCH", "MANIFEST_STALE"])
        )
        assert result["stage"] == "manifest_or_publish"
        assert result["release_blocking"] is True

    def test_input_visibility_is_soft(self) -> None:
        result = classify_tv_validation_stage(_gate_with(["PREFLIGHT_FAILED"]))
        assert result["stage"] == "input_visibility"
        assert result["release_blocking"] is False

    def test_target_preflight_failed_is_soft(self) -> None:
        # A target that loaded on the chart but whose Settings/Inputs surface
        # could not be opened is a UI-interaction flake, not semantic drift.
        # It belongs in the soft input-visibility stage, never compile/runtime.
        result = classify_tv_validation_stage(_gate_with(["TARGET_PREFLIGHT_FAILED"]))
        assert result["stage"] == "input_visibility"
        assert result["release_blocking"] is False

    def test_run_628_surface_shape_is_soft(self) -> None:
        # The exact run-628 shape once the surface failure is classified
        # correctly: report-level PREFLIGHT_FAILED + target-level
        # TARGET_PREFLIGHT_FAILED. Both soft → the gate must not block.
        result = classify_tv_validation_stage(
            _gate_with(["PREFLIGHT_FAILED", "TARGET_PREFLIGHT_FAILED"])
        )
        assert result["stage"] == "input_visibility"
        assert result["release_blocking"] is False

    def test_auth_only_is_soft(self) -> None:
        result = classify_tv_validation_stage(
            _gate_with(["AUTH_FAILED", "AUTH_NOT_REUSED"])
        )
        assert result["stage"] == "auth"
        assert result["release_blocking"] is False

    def test_missing_post_release_input_is_soft(self) -> None:
        result = classify_tv_validation_stage(
            _gate_with(["POST_RELEASE_VALIDATION_FAILED", "NO_TARGETS"])
        )
        assert result["stage"] == "validation_input_absent"
        assert result["release_blocking"] is False

    def test_mixed_stages_label_is_mixed(self) -> None:
        result = classify_tv_validation_stage(
            _gate_with(["PREFLIGHT_FAILED", "TARGET_FAILED"])
        )
        assert result["stage"] == "mixed"
        # The presence of compile/add/runtime in a mix forces blocking back on.
        assert result["release_blocking"] is True

    def test_unknown_code_is_blocking_by_default(self) -> None:
        result = classify_tv_validation_stage(_gate_with(["NEW_UNSEEN_CODE"]))
        assert result["stage"] == "unknown"
        assert result["release_blocking"] is True

    def test_per_code_preserves_failure_order(self) -> None:
        codes = ["TARGET_FAILED", "PREFLIGHT_FAILED", "AUTH_FAILED"]
        result = classify_tv_validation_stage(_gate_with(codes))
        assert [entry["code"] for entry in result["per_code"]] == codes


class TestSoftOnlyHelper:
    def test_input_visibility_only_is_soft(self) -> None:
        assert _tv_gate_is_soft_only(_gate_with(["PREFLIGHT_FAILED"])) is True

    def test_auth_only_is_soft(self) -> None:
        assert _tv_gate_is_soft_only(_gate_with(["AUTH_FAILED"])) is True

    def test_missing_post_release_input_is_soft(self) -> None:
        assert _tv_gate_is_soft_only(
            _gate_with(["POST_RELEASE_VALIDATION_FAILED", "NO_TARGETS"])
        ) is True

    def test_compile_add_runtime_is_not_soft(self) -> None:
        assert _tv_gate_is_soft_only(_gate_with(["TARGET_FAILED"])) is False

    def test_target_preflight_failed_only_is_soft(self) -> None:
        assert _tv_gate_is_soft_only(_gate_with(["TARGET_PREFLIGHT_FAILED"])) is True

    def test_run_628_surface_shape_is_soft(self) -> None:
        assert (
            _tv_gate_is_soft_only(
                _gate_with(["PREFLIGHT_FAILED", "TARGET_PREFLIGHT_FAILED"])
            )
            is True
        )

    def test_no_failures_is_not_soft(self) -> None:
        # An OK gate is never "soft-only" — the predicate only applies to
        # failed gates being considered for downgrade.
        assert _tv_gate_is_soft_only({"details": {"failures": []}}) is False


class TestGateAnnotation:
    def test_failed_gate_carries_tv_validation_stage_block(self, tmp_path) -> None:
        report = tmp_path / "validation_report.json"
        report.write_text(
            '{"overall_status": "fail", "validated_target_count": 1, '
            '"failures": [{"code": "PREFLIGHT_FAILED"}]}',
            encoding="utf-8",
        )
        gate = _run_post_release_validation_gate(str(report))
        assert gate["status"] == "fail"
        stage_block = gate["tv_validation_stage"]
        assert stage_block["stage"] == "input_visibility"
        assert stage_block["release_blocking"] is False
        codes = [entry["code"] for entry in stage_block["per_code"]]
        assert codes == ["PREFLIGHT_FAILED"]

    def test_missing_input_report_is_external_and_non_blocking_stage(
        self, tmp_path
    ) -> None:
        report = tmp_path / "validation_report.json"
        report.write_text(
            '{"overall_status": "fail", "validated_target_count": 0, '
            '"failures": [{"code": "POST_RELEASE_VALIDATION_FAILED"}]}',
            encoding="utf-8",
        )
        gate = _run_post_release_validation_gate(str(report))
        assert gate["status"] == "fail"
        assert gate["tv_failure_class"] == "external_tv_drift"
        stage_block = gate["tv_validation_stage"]
        assert stage_block["stage"] == "validation_input_absent"
        assert stage_block["release_blocking"] is False

    def test_ok_gate_has_no_stage_block(self, tmp_path) -> None:
        report = tmp_path / "validation_report.json"
        report.write_text(
            '{"overall_status": "ok", "validated_target_count": 1, "failures": []}',
            encoding="utf-8",
        )
        gate = _run_post_release_validation_gate(str(report))
        assert gate["status"] == "ok"
        assert "tv_validation_stage" not in gate

    def test_file_not_found_report_is_blocking_fail(self, tmp_path) -> None:
        """Pin: missing report file → fail gate that is NOT soft-only."""
        nonexistent = tmp_path / "no_such_report.json"
        gate = _run_post_release_validation_gate(str(nonexistent))
        assert gate["status"] == "fail"
        assert "report not found" in gate["details"]["message"]
        # No tv_validation_stage → _tv_gate_is_soft_only must return False,
        # keeping the gate blocking.
        assert "tv_validation_stage" not in gate
        assert _tv_gate_is_soft_only(gate) is False

    def test_unreadable_report_is_blocking_fail(self, tmp_path) -> None:
        """Pin: unreadable (corrupt) report → fail gate that is NOT soft-only."""
        corrupt = tmp_path / "corrupt_report.json"
        corrupt.write_text("<<<not json>>>", encoding="utf-8")
        gate = _run_post_release_validation_gate(str(corrupt))
        assert gate["status"] == "fail"
        assert "unreadable" in gate["details"]["message"]
        assert "tv_validation_stage" not in gate
        assert _tv_gate_is_soft_only(gate) is False


class TestRunnerDowngrade:
    """Pin that main() unconditionally downgrades a soft-only TV gate."""

    def test_main_downgrades_input_visibility_only_outside_ci_mode(
        self, tmp_path, capsys
    ) -> None:
        from scripts import run_smc_release_gates as runner

        # Build a synthetic post-release validation report that would block
        # the operational pass under the old rules.
        validation_report = tmp_path / "validation_report.json"
        validation_report.write_text(
            '{"overall_status": "fail", "validated_target_count": 1, '
            '"failures": [{"code": "PREFLIGHT_FAILED"}]}',
            encoding="utf-8",
        )

        # Patch heavy gates to known-good no-op results so we only exercise
        # the downgrade plumbing.
        ok_gate = {"name": "noop", "status": "ok", "details": {}}

        def _noop_provider(*_a, **_kw):
            return {
                "overall_status": "ok",
                "domain_alerts": [],
                "failures": [],
                "warnings": [],
                "degradations_detected": [],
                "smoke_bundles": {("AAPL", "1m"): {}},
                "smoke_test_results": [{"symbol": "AAPL", "timeframe": "1m"}],
            }

        with mock.patch.object(runner, "run_provider_health_check", _noop_provider), \
            mock.patch.object(runner, "_run_reference_bundle_gate", lambda *a, **kw: dict(ok_gate)), \
            mock.patch.object(runner, "_run_publish_contract_gate", lambda *a, **kw: dict(ok_gate)), \
            mock.patch.object(runner, "_run_measurement_gate", lambda *a, **kw: dict(ok_gate)), \
            mock.patch.object(runner, "build_evidence_lane_gate", lambda: dict(ok_gate)):
            output = tmp_path / "report.json"
            argv = [
                "run_smc_release_gates",
                "--symbols", "AAPL",
                "--timeframes", "1m",
                "--output", str(output),
                "--post-release-validation-report", str(validation_report),
            ]
            with mock.patch("sys.argv", argv):
                exit_code = runner.main()

        # Soft-only TV gate must NOT block the operational release pass.
        assert exit_code == 0
        import json
        report_payload = json.loads(output.read_text(encoding="utf-8"))
        post_release = next(
            g for g in report_payload["gates"] if g["name"] == "post_release_validation"
        )
        assert post_release["status"] == "fail"
        assert post_release["blocking"] is False
        assert post_release.get("tv_soft_only_downgraded") is True
        assert "post_release_validation" in report_payload["runner"]["tv_soft_downgrades"]
        assert report_payload["operational_release_pass"] is True

    def test_main_downgrades_missing_post_release_input_outside_ci_mode(
        self, tmp_path
    ) -> None:
        from scripts import run_smc_release_gates as runner

        validation_report = tmp_path / "validation_report.json"
        validation_report.write_text(
            '{"overall_status": "fail", "validated_target_count": 0, '
            '"failures": [{"code": "POST_RELEASE_VALIDATION_FAILED"}]}',
            encoding="utf-8",
        )

        ok_gate = {"name": "noop", "status": "ok", "details": {}}

        def _noop_provider(*_a, **_kw):
            return {
                "overall_status": "ok",
                "domain_alerts": [],
                "failures": [],
                "warnings": [],
                "degradations_detected": [],
                "smoke_bundles": {("AAPL", "1m"): {}},
                "smoke_test_results": [{"symbol": "AAPL", "timeframe": "1m"}],
            }

        with mock.patch.object(runner, "run_provider_health_check", _noop_provider), \
            mock.patch.object(runner, "_run_reference_bundle_gate", lambda *a, **kw: dict(ok_gate)), \
            mock.patch.object(runner, "_run_publish_contract_gate", lambda *a, **kw: dict(ok_gate)), \
            mock.patch.object(runner, "_run_measurement_gate", lambda *a, **kw: dict(ok_gate)), \
            mock.patch.object(runner, "build_evidence_lane_gate", lambda: dict(ok_gate)):
            output = tmp_path / "report.json"
            argv = [
                "run_smc_release_gates",
                "--symbols", "AAPL",
                "--timeframes", "1m",
                "--output", str(output),
                "--post-release-validation-report", str(validation_report),
            ]
            with mock.patch("sys.argv", argv):
                exit_code = runner.main()

        assert exit_code == 0
        import json
        report_payload = json.loads(output.read_text(encoding="utf-8"))
        post_release = next(
            g for g in report_payload["gates"] if g["name"] == "post_release_validation"
        )
        assert post_release["status"] == "fail"
        assert post_release["blocking"] is False
        assert post_release["tv_failure_class"] == "external_tv_drift"
        assert post_release["tv_validation_stage"]["stage"] == "validation_input_absent"
        assert post_release.get("tv_soft_only_downgraded") is True
        assert report_payload["operational_release_pass"] is True
