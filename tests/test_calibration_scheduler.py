"""_log_bucket_readiness: the one-line arm-readiness summary that makes the
"enough calibration data yet?" check a log grep instead of a volume dig."""
import json
import logging

from open_prep import calibration_scheduler


def test_bucket_readiness_counts_and_details(tmp_path, caplog, monkeypatch):
    out = tmp_path / "calibration_latest.json"
    out.write_text(json.dumps({"table": {
        "A1|2.0-3.0": {"n": 34, "hit_target_rate": 0.58},
        "A0|>=3.0": {"n": 41, "hit_target_rate": 0.71},
        "A1|1.0-1.5": {"n": 5, "hit_target_rate": 0.40},
    }}), encoding="utf-8")
    monkeypatch.setenv("RT_CALIBRATION_MIN_SAMPLES", "20")
    with caplog.at_level(logging.INFO):
        calibration_scheduler._log_bucket_readiness(str(out))
    assert "2/3 buckets have n>=20" in caplog.text
    assert "A1|2.0-3.0 n=34 P=58%" in caplog.text
    assert "A0|>=3.0 n=41 P=71%" in caplog.text
    assert "A1|1.0-1.5" not in caplog.text  # below floor -> not arm-ready


def test_bucket_readiness_none_ready(tmp_path, caplog, monkeypatch):
    out = tmp_path / "calibration_latest.json"
    out.write_text(json.dumps({"table": {"A1|2.0-3.0": {"n": 3, "hit_target_rate": 0.5}}}), encoding="utf-8")
    monkeypatch.setenv("RT_CALIBRATION_MIN_SAMPLES", "20")
    with caplog.at_level(logging.INFO):
        calibration_scheduler._log_bucket_readiness(str(out))
    assert "0/1 buckets have n>=20 (arm-ready: none)" in caplog.text


def test_bucket_readiness_missing_file_never_raises(tmp_path):
    # A missing / unreadable file must not raise (best-effort logging).
    calibration_scheduler._log_bucket_readiness(str(tmp_path / "nope.json"))
