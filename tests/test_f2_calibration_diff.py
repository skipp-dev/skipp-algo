"""Tests for ``scripts.f2_calibration_diff`` (issue #43).

Pure stdlib; no Databento, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_calibration_diff import build_markdown, main


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


_NEW = {
    "global_weights": {"BOS": 0.55, "CHOCH": 0.48, "FVG": 0.50},
    "promoted_buckets": ["htf_bias=bull", "session=NY"],
    "frozen_provenance": {"frozen_at": "2026-05-25T06:00:00Z"},
}


def test_missing_old_emits_full_snapshot(tmp_path: Path) -> None:
    new = _write(tmp_path / "new.json", _NEW)
    out = tmp_path / "pr_body.md"
    rc = main(["--new", str(new), "--out", str(out)])
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "no prior artifact, full snapshot" in body
    assert "`htf_bias=bull`" in body
    assert "`BOS`" in body


def test_identical_old_and_new_marks_no_change(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _NEW)
    new = _write(tmp_path / "new.json", _NEW)
    out = tmp_path / "pr_body.md"
    rc = main(["--old", str(old), "--new", str(new), "--out", str(out)])
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "no change vs. prior artifact" in body


def test_bucket_partition_add_remove_keep(tmp_path: Path) -> None:
    old = _write(
        tmp_path / "old.json",
        {
            **_NEW,
            "promoted_buckets": ["htf_bias=bull", "session=LDN"],
        },
    )
    new = _write(tmp_path / "new.json", _NEW)  # promotes NY, drops LDN, keeps bull
    out = tmp_path / "pr_body.md"
    main(["--old", str(old), "--new", str(new), "--out", str(out)])
    body = out.read_text(encoding="utf-8")
    # added: session=NY ; removed: session=LDN ; kept: htf_bias=bull
    assert "**added** (1): `session=NY`" in body
    assert "**removed** (1): `session=LDN`" in body
    assert "**kept** (1): `htf_bias=bull`" in body


def test_global_weights_signed_delta_format(tmp_path: Path) -> None:
    old = _write(
        tmp_path / "old.json",
        {**_NEW, "global_weights": {"BOS": 0.50, "CHOCH": 0.52, "FVG": 0.50}},
    )
    new = _write(tmp_path / "new.json", _NEW)  # BOS +0.05, CHOCH -0.04
    out = tmp_path / "pr_body.md"
    main(["--old", str(old), "--new", str(new), "--out", str(out)])
    body = out.read_text(encoding="utf-8")
    assert "0.5000 → 0.5500 (+0.0500)" in body  # BOS up
    assert "0.5200 → 0.4800 (-0.0400)" in body  # CHOCH down


def test_n_events_delta_extracted_from_manifest(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _NEW)
    new = _write(tmp_path / "new.json", _NEW)
    new_man = _write(tmp_path / "new_man.json", {"n_events": 12000})
    old_man = _write(tmp_path / "old_man.json", {"n_events": 10025})
    out = tmp_path / "pr_body.md"
    rc = main(
        [
            "--old",
            str(old),
            "--new",
            str(new),
            "--new-manifest",
            str(new_man),
            "--old-manifest",
            str(old_man),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert "**n_events**: 10025 → 12000 (+1975)" in body


def test_main_returns_nonzero_on_missing_new(tmp_path: Path) -> None:
    out = tmp_path / "pr_body.md"
    rc = main(["--new", str(tmp_path / "nope.json"), "--out", str(out)])
    assert rc == 2


def test_build_markdown_renders_metadata_section_keys(tmp_path: Path) -> None:
    md = build_markdown(
        old=None,
        new=_NEW,
        old_manifest=None,
        new_manifest={"n_events": 10025},
    )
    assert "### metadata" in md
    assert "**frozen_at**" in md
    assert "**n_events**" in md


def test_frozen_at_change_appears_in_metadata(tmp_path: Path) -> None:
    md = build_markdown(
        old={**_NEW, "frozen_provenance": {"frozen_at": "2026-02-01T00:00:00Z"}},
        new=_NEW,
        old_manifest=None,
        new_manifest=None,
    )
    assert "`2026-02-01T00:00:00Z` → `2026-05-25T06:00:00Z`" in md


@pytest.mark.parametrize(
    "missing_key",
    ["global_weights", "promoted_buckets"],
)
def test_full_snapshot_tolerates_missing_keys(tmp_path: Path, missing_key: str) -> None:
    payload = dict(_NEW)
    payload.pop(missing_key)
    new = _write(tmp_path / "new.json", payload)
    out = tmp_path / "pr_body.md"
    rc = main(["--new", str(new), "--out", str(out)])
    assert rc == 0
