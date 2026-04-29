"""Tests for scripts/f2_rotate_rollback_history.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_rotate_rollback_history import (
    DEFAULT_ARCHIVE_SUBDIR,
    main,
    rotate_history,
)

# ---------------------------------------------------------------------------
# rotate_history()
# ---------------------------------------------------------------------------


def test_rotate_archives_existing_and_resets_to_empty(tmp_path: Path) -> None:
    history = tmp_path / "rollback_history.json"
    history.write_text(json.dumps([0.01, -0.02, 0.005]), encoding="utf-8")

    receipt = rotate_history(history_path=history, timestamp="2026-04-21T10-00-00Z")

    assert receipt["action"] == "rotated"
    assert receipt["archived_len"] == 3
    assert receipt["new_len"] == 0
    assert json.loads(history.read_text(encoding="utf-8")) == []

    archived = Path(receipt["archived"])  # type: ignore[arg-type]
    assert archived.parent.name == DEFAULT_ARCHIVE_SUBDIR
    assert archived.name == "2026-04-21T10-00-00Z.json"
    assert json.loads(archived.read_text(encoding="utf-8")) == [0.01, -0.02, 0.005]


def test_rotate_with_seed(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.5]), encoding="utf-8")
    receipt = rotate_history(
        history_path=history,
        seed=[-0.001],
        timestamp="2026-04-21T11-00-00Z",
    )
    assert receipt["new_len"] == 1
    assert json.loads(history.read_text(encoding="utf-8")) == [-0.001]


def test_rotate_custom_archive_dir(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([1.0]), encoding="utf-8")
    archive_dir = tmp_path / "custom_archive"
    receipt = rotate_history(
        history_path=history,
        archive_dir=archive_dir,
        timestamp="2026-04-21T12-00-00Z",
    )
    archived = Path(receipt["archived"])  # type: ignore[arg-type]
    assert archived.parent == archive_dir
    assert archived.exists()


def test_rotate_missing_without_allow_empty_raises(tmp_path: Path) -> None:
    history = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="does not exist"):
        rotate_history(history_path=history)


def test_rotate_missing_with_allow_empty_creates_fresh(tmp_path: Path) -> None:
    history = tmp_path / "missing.json"
    receipt = rotate_history(history_path=history, allow_empty=True)
    assert receipt["action"] == "created"
    assert receipt["archived"] is None
    assert json.loads(history.read_text(encoding="utf-8")) == []


def test_rotate_archive_collision_raises(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.1]), encoding="utf-8")
    archive_dir = tmp_path / "arch"
    archive_dir.mkdir()
    (archive_dir / "2026-04-21T13-00-00Z.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="archive collision"):
        rotate_history(
            history_path=history,
            archive_dir=archive_dir,
            timestamp="2026-04-21T13-00-00Z",
        )
    # Live file untouched.
    assert json.loads(history.read_text(encoding="utf-8")) == [0.1]


def test_rotate_rejects_non_list_history(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps({"oops": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a JSON list"):
        rotate_history(history_path=history)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_happy_path(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.01]), encoding="utf-8")
    rc = main(["--history", str(history)])
    assert rc == 0
    assert json.loads(history.read_text(encoding="utf-8")) == []


def test_cli_seed_flag(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.01, 0.02]), encoding="utf-8")
    rc = main([
        "--history", str(history),
        "--seed", "[-0.005]",
    ])
    assert rc == 0
    assert json.loads(history.read_text(encoding="utf-8")) == [-0.005]


def test_cli_invalid_seed_returns_1(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.01]), encoding="utf-8")
    rc = main([
        "--history", str(history),
        "--seed", "{not json",
    ])
    assert rc == 1


def test_cli_seed_must_be_list(tmp_path: Path) -> None:
    history = tmp_path / "h.json"
    history.write_text(json.dumps([0.01]), encoding="utf-8")
    rc = main([
        "--history", str(history),
        "--seed", "42",
    ])
    assert rc == 1


def test_cli_missing_history_returns_1(tmp_path: Path) -> None:
    rc = main(["--history", str(tmp_path / "nope.json")])
    assert rc == 1


def test_cli_missing_history_with_allow_empty_returns_0(tmp_path: Path) -> None:
    history = tmp_path / "nope.json"
    rc = main(["--history", str(history), "--allow-empty"])
    assert rc == 0
    assert json.loads(history.read_text(encoding="utf-8")) == []
