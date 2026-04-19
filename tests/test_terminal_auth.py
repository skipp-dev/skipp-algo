"""Tests for B6 terminal auth guard."""
from __future__ import annotations

import pytest

from terminal_auth import _constant_time_compare, _get_required_token


class TestGetRequiredToken:
    def test_returns_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STREAMLIT_AUTH_TOKEN", raising=False)
        assert _get_required_token() is None

    def test_returns_none_for_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STREAMLIT_AUTH_TOKEN", "  ")
        assert _get_required_token() is None

    def test_returns_token_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STREAMLIT_AUTH_TOKEN", "my-secret-token")
        assert _get_required_token() == "my-secret-token"

    def test_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STREAMLIT_AUTH_TOKEN", "  tok123  ")
        assert _get_required_token() == "tok123"


class TestConstantTimeCompare:
    def test_matching_strings(self) -> None:
        assert _constant_time_compare("abc", "abc") is True

    def test_non_matching_strings(self) -> None:
        assert _constant_time_compare("abc", "xyz") is False

    def test_empty_strings(self) -> None:
        assert _constant_time_compare("", "") is True

    def test_partial_match(self) -> None:
        assert _constant_time_compare("abcdef", "abcxyz") is False

    def test_unicode(self) -> None:
        assert _constant_time_compare("tök€n", "tök€n") is True
        assert _constant_time_compare("tök€n", "token") is False


class TestRequireAuth:
    def test_returns_true_when_no_token_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STREAMLIT_AUTH_TOKEN", raising=False)
        from terminal_auth import require_auth
        assert require_auth() is True
