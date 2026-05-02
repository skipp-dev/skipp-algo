"""Soft-skip behaviour for ``run_smc_pre_release_artifact_refresh``.

Regression guard for Bug-Hunt 2026-05-01 Finding F-03: the
``smc-deeper-integration-gates`` workflow ran on ephemeral GitHub runners
that do not carry the canonical Databento export bundle; every per-
timeframe refresh therefore raised ``RuntimeError`` with a message
containing ``No export manifest found ... manifest_prefix=
databento_volatility_production_``. The script previously exited 1, which
turned every deeper-gates run red.

The fix introduces ``--soft-skip-on-missing-inputs``: when *every* failure
is a ``REFRESH_EXECUTION_FAILED`` whose message mentions ``manifest``,
the script exits with rc=78 (soft-skip) instead of rc=1, and the JSON
report carries ``overall_status="skipped"``. Any other failure class
(e.g. ``REFRESH_MANIFEST_ERRORS``, ``REFRESH_INCOMPLETE_REFERENCE_SET``)
still propagates as rc=1, even with the flag set.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_smc_pre_release_artifact_refresh.py"


@pytest.fixture
def script_module() -> ModuleType:
    """Import the CLI script as a module so we can monkeypatch its globals.

    Per ``/memories/python-testing.md``: insert into ``sys.modules`` *before*
    ``exec_module`` so dataclass-style annotation introspection works.
    """
    spec = importlib.util.spec_from_file_location(
        "_test_pre_release_refresh", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _patch_resolution_to_empty(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Make ``resolve_structure_artifact_inputs`` return a no-op resolution.

    The script's own resolution call would still try to discover bundles on
    disk; we short-circuit it to a stable, empty resolution so the test does
    not depend on filesystem layout.
    """
    monkeypatch.setattr(
        module,
        "resolve_structure_artifact_inputs",
        lambda **kwargs: {
            "workbook_path": None,
            "export_bundle_root": None,
            "structure_artifacts_dir": tmp_path / "artifacts",
            "warnings": [],
            "resolution_mode": "test",
        },
    )
    # Bypass the per-timeframe symbol-availability discovery (otherwise
    # the missing bundle would warn-and-skip before we ever reach the
    # write call we want to fail).
    monkeypatch.setattr(
        module,
        "_discover_available_reference_symbols",
        lambda **kwargs: None,
    )


def _run_main(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    extra_argv: list[str],
    output_path: Path,
) -> int:
    argv = [
        "run_smc_pre_release_artifact_refresh.py",
        "--symbols",
        "AAPL",
        "--timeframes",
        "5m",
        "--output",
        str(output_path),
        *extra_argv,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return int(module.main())


def _read_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_soft_skip_when_only_manifest_missing_failures(
    script_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_resolution_to_empty(script_module, monkeypatch, tmp_path)

    def _raise_manifest_missing(**_kwargs: object) -> dict:
        raise RuntimeError(
            "No export manifest found for /tmp/x required_frames=['full_universe_second_detail_open'] "
            "manifest_prefix=databento_volatility_production_"
        )

    monkeypatch.setattr(
        script_module,
        "write_structure_artifacts_from_workbook",
        _raise_manifest_missing,
    )

    out = tmp_path / "report.json"
    rc = _run_main(
        script_module,
        monkeypatch,
        extra_argv=["--soft-skip-on-missing-inputs"],
        output_path=out,
    )

    assert rc == 78, "soft-skip path must return rc=78 for ::warning gating"
    report = _read_report(out)
    assert report["overall_status"] == "skipped"
    assert report["runner"]["soft_skipped"] is True
    assert report["runner"]["exit_code"] == 78
    assert report["failures"], "failures list must be preserved for diagnostics"
    assert all(f["code"] == "REFRESH_EXECUTION_FAILED" for f in report["failures"])


def test_no_soft_skip_without_flag(
    script_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Default behaviour must remain rc=1 — protects upstream consumers."""
    _patch_resolution_to_empty(script_module, monkeypatch, tmp_path)

    def _raise_manifest_missing(**_kwargs: object) -> dict:
        raise RuntimeError(
            "No export manifest found for /tmp/x manifest_prefix=databento_volatility_production_"
        )

    monkeypatch.setattr(
        script_module,
        "write_structure_artifacts_from_workbook",
        _raise_manifest_missing,
    )

    out = tmp_path / "report.json"
    rc = _run_main(script_module, monkeypatch, extra_argv=[], output_path=out)

    assert rc == 1
    report = _read_report(out)
    assert report["overall_status"] == "fail"
    assert report["runner"]["soft_skipped"] is False
    assert report["runner"]["exit_code"] == 1


def test_soft_skip_does_not_swallow_other_failure_classes(
    script_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-manifest failures still surface as rc=1 even when the flag is set."""
    _patch_resolution_to_empty(script_module, monkeypatch, tmp_path)

    # Return a manifest with explicit errors -> REFRESH_MANIFEST_ERRORS.
    def _return_manifest_with_errors(**_kwargs: object) -> dict:
        return {
            "errors": [{"code": "BAD_THING", "message": "synthetic"}],
            "counts": {"symbols_requested": 1, "artifacts_written": 1},
        }

    monkeypatch.setattr(
        script_module,
        "write_structure_artifacts_from_workbook",
        _return_manifest_with_errors,
    )

    out = tmp_path / "report.json"
    rc = _run_main(
        script_module,
        monkeypatch,
        extra_argv=["--soft-skip-on-missing-inputs"],
        output_path=out,
    )

    assert rc == 1, "non-manifest failures must NOT be soft-skipped"
    report = _read_report(out)
    assert report["overall_status"] == "fail"
    assert report["runner"]["soft_skipped"] is False
    codes = {failure.get("code") for failure in report["failures"]}
    assert "REFRESH_MANIFEST_ERRORS" in codes


def test_soft_skip_classifies_missing_prefixed_manifest_errors(
    script_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """REFRESH_MANIFEST_ERRORS soft-skips ONLY when every detail.code starts MISSING_.

    F-V8-followup PR #2026 round-2 (Copilot review). Genuine refresh bugs
    such as ``BUILD_SYMBOL_ARTIFACT_FAILED`` arrive via the same
    ``REFRESH_MANIFEST_ERRORS`` envelope and must NOT be soft-skipped;
    only manifests whose every detail uses the canonical ``MISSING_*``
    prefix may be classified as missing-input.
    """
    _patch_resolution_to_empty(script_module, monkeypatch, tmp_path)

    def _return_manifest_missing_only(**_kwargs: object) -> dict:
        return {
            "errors": [
                {"code": "MISSING_STRUCTURE_INPUTS", "message": "no bundle"},
                {"code": "MISSING_REFERENCE_ARTIFACT", "message": "no rs"},
            ],
            "counts": {"symbols_requested": 1, "artifacts_written": 0},
        }

    monkeypatch.setattr(
        script_module,
        "write_structure_artifacts_from_workbook",
        _return_manifest_missing_only,
    )

    out = tmp_path / "report.json"
    rc = _run_main(
        script_module,
        monkeypatch,
        extra_argv=["--soft-skip-on-missing-inputs"],
        output_path=out,
    )

    assert rc == 78, (
        "manifest with only MISSING_-prefixed details must classify as "
        "missing-input and soft-skip"
    )
    report = _read_report(out)
    assert report["overall_status"] == "skipped"
    assert report["runner"]["soft_skipped"] is True


def test_soft_skip_rejects_mixed_missing_and_genuine_manifest_errors(
    script_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A single non-MISSING detail in the manifest blocks soft-skip."""
    _patch_resolution_to_empty(script_module, monkeypatch, tmp_path)

    def _return_manifest_mixed(**_kwargs: object) -> dict:
        return {
            "errors": [
                {"code": "MISSING_STRUCTURE_INPUTS", "message": "no bundle"},
                {"code": "BUILD_SYMBOL_ARTIFACT_FAILED", "message": "real bug"},
            ],
            "counts": {"symbols_requested": 1, "artifacts_written": 0},
        }

    monkeypatch.setattr(
        script_module,
        "write_structure_artifacts_from_workbook",
        _return_manifest_mixed,
    )

    out = tmp_path / "report.json"
    rc = _run_main(
        script_module,
        monkeypatch,
        extra_argv=["--soft-skip-on-missing-inputs"],
        output_path=out,
    )

    assert rc == 1, (
        "any non-MISSING_ detail in REFRESH_MANIFEST_ERRORS must surface "
        "as rc=1 — genuine refresh bugs must not be hidden"
    )
    report = _read_report(out)
    assert report["overall_status"] == "fail"
    assert report["runner"]["soft_skipped"] is False

