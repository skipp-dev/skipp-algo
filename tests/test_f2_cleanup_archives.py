"""Tests for scripts/f2_cleanup_archives.py."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

import pytest

from scripts.f2_cleanup_archives import cleanup_archives, main


def _mk(archive: Path, name: str) -> Path:
    archive.mkdir(parents=True, exist_ok=True)
    p = archive / name
    p.write_text(json.dumps({"status": "shadow"}), encoding="utf-8")
    return p


NOW = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)


def test_deletes_older_than_cutoff(tmp_path: Path) -> None:
    arc = tmp_path / "contextual_calibration.archive"
    old = _mk(arc, "treatment_calibration.2026-01-01T10-00-00Z.json")
    new = _mk(arc, "treatment_calibration.2026-04-20T10-00-00Z.json")
    manifest = cleanup_archives(archive_dir=arc, max_age_days=90, now=NOW)
    assert not old.exists()
    assert new.exists()
    assert [d["name"] for d in manifest["deleted"]] == [old.name]
    assert [k["name"] for k in manifest["kept"]] == [new.name]


def test_dry_run_deletes_nothing(tmp_path: Path) -> None:
    arc = tmp_path / "archive"
    old = _mk(arc, "x.2026-01-01T10-00-00Z.json")
    manifest = cleanup_archives(archive_dir=arc, max_age_days=90, now=NOW, dry_run=True)
    assert old.exists()
    assert manifest["deleted"][0]["name"] == old.name
    assert manifest["dry_run"] is True


def test_skips_unparseable_and_non_json(tmp_path: Path) -> None:
    arc = tmp_path / "archive"
    _mk(arc, "no-timestamp.json")
    (arc / "readme.txt").write_text("hi", encoding="utf-8")
    manifest = cleanup_archives(archive_dir=arc, max_age_days=1, now=NOW)
    assert manifest["deleted"] == []
    assert manifest["skipped_unparseable"] == ["no-timestamp.json"]


def test_missing_archive_dir_is_ok(tmp_path: Path) -> None:
    manifest = cleanup_archives(archive_dir=tmp_path / "absent", max_age_days=30, now=NOW)
    assert manifest["deleted"] == []
    assert manifest["kept"] == []


def test_max_age_days_zero_deletes_everything(tmp_path: Path) -> None:
    arc = tmp_path / "archive"
    a = _mk(arc, "a.2026-04-20T10-00-00Z.json")
    b = _mk(arc, "b.2026-04-21T11-00-00Z.json")
    manifest = cleanup_archives(archive_dir=arc, max_age_days=0, now=NOW)
    # Both are older than 'now' with zero retention.
    assert not a.exists()
    assert not b.exists()
    assert len(manifest["deleted"]) == 2


def test_negative_max_age_days_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        cleanup_archives(archive_dir=tmp_path, max_age_days=-1, now=NOW)


def test_journal_appends_on_real_run(tmp_path: Path) -> None:
    arc = tmp_path / "archive"
    _mk(arc, "x.2026-01-01T10-00-00Z.json")
    journal = tmp_path / "journal.jsonl"
    cleanup_archives(
        archive_dir=arc, max_age_days=30, now=NOW, journal_path=journal
    )
    cleanup_archives(
        archive_dir=arc, max_age_days=30, now=NOW, journal_path=journal
    )
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        rec = json.loads(line)
        assert rec["schema_version"] == 1
        assert rec["max_age_days"] == 30


def test_journal_not_touched_on_dry_run(tmp_path: Path) -> None:
    arc = tmp_path / "archive"
    _mk(arc, "x.2026-01-01T10-00-00Z.json")
    journal = tmp_path / "journal.jsonl"
    cleanup_archives(
        archive_dir=arc, max_age_days=30, now=NOW, dry_run=True, journal_path=journal
    )
    assert not journal.exists()


def test_cli_happy_path_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arc = tmp_path / "archive"
    _mk(arc, "x.2026-01-01T10-00-00Z.json")
    rc = main([
        "--archive-dir", str(arc),
        "--max-age-days", "30",
        "--journal", str(tmp_path / "j.jsonl"),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "F2 archive cleanup" in out
    assert "deleted: 1" in out


def test_cli_quiet_one_liner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arc = tmp_path / "archive"
    _mk(arc, "x.2026-01-01T10-00-00Z.json")
    rc = main([
        "--archive-dir", str(arc),
        "--max-age-days", "30",
        "--quiet",
        "--journal", str(tmp_path / "j.jsonl"),
    ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("cleanup:")
    assert "deleted=1" in out


def test_cli_output_writes_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arc = tmp_path / "archive"
    _mk(arc, "x.2026-01-01T10-00-00Z.json")
    out_path = tmp_path / "out.json"
    rc = main([
        "--archive-dir", str(arc),
        "--max-age-days", "30",
        "--output", str(out_path),
        "--journal", str(tmp_path / "j.jsonl"),
        "--quiet",
    ])
    assert rc == 0
    manifest = json.loads(out_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert len(manifest["deleted"]) == 1


def test_cli_dry_run_suffix_in_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arc = tmp_path / "archive"
    _mk(arc, "x.2026-01-01T10-00-00Z.json")
    rc = main([
        "--archive-dir", str(arc),
        "--max-age-days", "30",
        "--dry-run",
        "--journal", str(tmp_path / "j.jsonl"),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "(dry-run)" in out
