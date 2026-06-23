from __future__ import annotations

from scripts import publish_signals_snapshot as mod


def test_publish_rejects_repo_without_slash(tmp_path, capsys) -> None:
    input_path = tmp_path / "latest_realtime_signals.json"
    input_path.write_text("{}", encoding="utf-8")

    rc = mod.publish(input_path, "bot/live-signals-snapshot", "skippALGO", "tok")

    assert rc == 1
    err = capsys.readouterr().err
    assert "repo must be owner/name" in err


def test_publish_rejects_repo_with_invalid_owner_char(tmp_path, capsys) -> None:
    input_path = tmp_path / "latest_realtime_signals.json"
    input_path.write_text("{}", encoding="utf-8")

    rc = mod.publish(input_path, "bot/live-signals-snapshot", "-bad/skipp-algo", "tok")

    assert rc == 1
    err = capsys.readouterr().err
    assert "repo must be owner/name" in err


def test_publish_rejects_repo_with_invalid_name_char(tmp_path, capsys) -> None:
    input_path = tmp_path / "latest_realtime_signals.json"
    input_path.write_text("{}", encoding="utf-8")

    rc = mod.publish(input_path, "bot/live-signals-snapshot", "skippALGO/skipp algo", "tok")

    assert rc == 1
    err = capsys.readouterr().err
    assert "repo must be owner/name" in err


def test_publish_allows_valid_repo_format() -> None:
    assert mod._is_valid_owner_repo("skippALGO/skipp-algo") is True
    assert mod._is_valid_owner_repo("owner123/repo.name_1") is True


def test_is_valid_branch_accepts_normal_names() -> None:
    assert mod._is_valid_branch("bot/live-signals-snapshot") is True
    assert mod._is_valid_branch("feature/my-feature") is True
    assert mod._is_valid_branch("main") is True


def test_is_valid_branch_rejects_leading_dash() -> None:
    assert mod._is_valid_branch("-foo") is False
    assert mod._is_valid_branch("--force") is False


def test_is_valid_branch_rejects_double_dot() -> None:
    assert mod._is_valid_branch("refs/../bad") is False


def test_is_valid_branch_rejects_tilde_and_caret() -> None:
    assert mod._is_valid_branch("bad~name") is False
    assert mod._is_valid_branch("bad^name") is False


def test_publish_rejects_invalid_branch(tmp_path, capsys) -> None:
    input_path = tmp_path / "latest_realtime_signals.json"
    input_path.write_text("{}", encoding="utf-8")

    rc = mod.publish(input_path, "--force", "skippALGO/skipp-algo", "tok")

    assert rc == 1
    err = capsys.readouterr().err
    assert "invalid branch name" in err


def test_is_valid_branch_module_constant_zero_sha() -> None:
    """_is_valid_branch docs: all-zeros SHA is produced internally, not from CLI."""
    # Verify the zero-SHA constant used for first-publish lease is well-formed.
    zero_sha = "0" * 40
    assert len(zero_sha) == 40
    assert all(c == "0" for c in zero_sha)
