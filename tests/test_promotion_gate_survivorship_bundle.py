"""Production survivorship enforcement via bundle provenance (no --universe-trade-date).

The daily gate CI does not pass --universe-trade-date, so the survivorship flag
rides the bundle: build_promotion_gate_bundle stamps universe_survivorship_bias_risk
(read from the databento export manifest) into every entry's provenance, and
run_promotion_gate ORs it into the demote-not-promote (rc 2) path.
"""
from __future__ import annotations

import json

import scripts.build_promotion_gate_bundle as bpb
from scripts.run_promotion_gate import main as run_gate_main


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_read_universe_survivorship_flag_fail_soft(tmp_path) -> None:
    assert bpb._read_universe_survivorship_flag(None) is None
    assert bpb._read_universe_survivorship_flag(tmp_path / "missing.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("not json{", encoding="utf-8")
    assert bpb._read_universe_survivorship_flag(bad) is None

    assert bpb._read_universe_survivorship_flag(_write(tmp_path / "absent.json", {"other": 1})) is None
    assert bpb._read_universe_survivorship_flag(
        _write(tmp_path / "t.json", {"universe_survivorship_bias_risk": True})
    ) is True
    assert bpb._read_universe_survivorship_flag(
        _write(tmp_path / "f.json", {"universe_survivorship_bias_risk": False})
    ) is False


def test_build_bundle_stamps_flag_on_every_entry(tmp_path) -> None:
    bundle = bpb.build_bundle(scoring_root=tmp_path, universe_survivorship_bias_risk=True)
    assert bundle
    assert all(e["provenance"]["universe_survivorship_bias_risk"] is True for e in bundle)


def test_build_bundle_omits_flag_when_none(tmp_path) -> None:
    bundle = bpb.build_bundle(scoring_root=tmp_path)
    assert all("universe_survivorship_bias_risk" not in e["provenance"] for e in bundle)


def test_gate_demotes_to_rc2_on_bundle_carried_flag(tmp_path) -> None:
    # No --universe-trade-date (the production path): the flag rides the bundle.
    bundle = bpb.build_bundle(scoring_root=tmp_path, universe_survivorship_bias_risk=True)
    metrics = _write(tmp_path / "bundle.json", bundle)
    out = tmp_path / "out.json"
    rc = run_gate_main(["--metrics", str(metrics), "--output", str(out)])
    assert rc == 2  # flag True => never PROMOTE (demote if it would have promoted)
    assert json.loads(out.read_text(encoding="utf-8"))["universe_survivorship_bias_risk"] is True


def test_gate_no_flag_reports_false(tmp_path) -> None:
    bundle = bpb.build_bundle(scoring_root=tmp_path)
    metrics = _write(tmp_path / "bundle.json", bundle)
    out = tmp_path / "out.json"
    run_gate_main(["--metrics", str(metrics), "--output", str(out)])
    assert json.loads(out.read_text(encoding="utf-8"))["universe_survivorship_bias_risk"] is False
