"""Issue #28 scaffolding: CLI surface for the E3 dual-arm F2 promotion gate.

This is the *scaffolding* PR. It pins:

  * the new ``--weights-mode {static_global,contextual}`` flag exists with
    the right choices and the right (production-preserving) default,
  * the new ``--weights-artifact PATH`` flag exists and defaults to ``None``,
  * ``contextual`` raises ``NotImplementedError`` until the follow-up PR
    wires the contextual calibration weights through ``_score_zone_event``
    and proves byte-identity of the control arm,
  * ``--weights-artifact`` validation rejects non-existent paths,
  * the existing flags (``--symbols``, ``--timeframes``, ``--output-dir``,
    ``--require-evidence``) are unchanged.

Behavioural changes (actually swapping calibration sources, dual-arm
workflow output paths, byte-identity validation against the current
single-arm artifact, etc.) land in the follow-up PR per AC #2.
"""

from __future__ import annotations

import pytest

from scripts.run_smc_measurement_benchmark import build_parser, main


def test_weights_mode_defaults_to_static_global() -> None:
    ns = build_parser().parse_args([])
    assert ns.weights_mode == "static_global"


def test_weights_artifact_defaults_to_none() -> None:
    ns = build_parser().parse_args([])
    assert ns.weights_artifact is None


def test_weights_mode_accepts_contextual() -> None:
    ns = build_parser().parse_args(["--weights-mode", "contextual"])
    assert ns.weights_mode == "contextual"


def test_weights_mode_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--weights-mode", "bogus"])


def test_weights_artifact_accepts_path_string() -> None:
    ns = build_parser().parse_args(["--weights-artifact", "some/path.json"])
    assert ns.weights_artifact == "some/path.json"


def test_pre_existing_flags_remain(monkeypatch: pytest.MonkeyPatch) -> None:
    ns = build_parser().parse_args([])
    for attr in ("symbols", "timeframes", "output_dir", "require_evidence"):
        assert hasattr(ns, attr), f"pre-existing flag '{attr}' must remain"
    assert ns.require_evidence is False


def test_main_raises_not_implemented_for_contextual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_smc_measurement_benchmark.py", "--weights-mode", "contextual"],
    )
    with pytest.raises(NotImplementedError, match=r"#28"):
        main()


def test_main_raises_on_missing_weights_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_smc_measurement_benchmark.py",
            "--weights-artifact",
            str(missing),
            "--symbols",
            "",
            "--timeframes",
            "",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    with pytest.raises(FileNotFoundError, match=r"weights-artifact"):
        main()
