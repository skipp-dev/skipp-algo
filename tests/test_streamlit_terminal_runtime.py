from __future__ import annotations

from types import SimpleNamespace

from streamlit_terminal_runtime import resolve_live_story_state_kwargs, safe_float_mov, should_poll


def test_resolve_live_story_state_kwargs_uses_cfg_values() -> None:
    cfg = SimpleNamespace(live_story_ttl_s=1800.0, live_story_cooldown_s=120.0)

    assert resolve_live_story_state_kwargs(cfg) == {
        "ttl_s": 1800.0,
        "cooldown_s": 120.0,
    }


def test_resolve_live_story_state_kwargs_uses_defaults_without_cfg() -> None:
    assert resolve_live_story_state_kwargs(None) == {
        "ttl_s": 7200.0,
        "cooldown_s": 900.0,
    }


def test_safe_float_mov_returns_default_on_invalid() -> None:
    assert safe_float_mov("bad", default=1.5) == 1.5


def test_safe_float_mov_coerces_numeric_values() -> None:
    assert safe_float_mov("2.75") == 2.75


def test_should_poll_requires_provider_and_elapsed_interval() -> None:
    assert should_poll(
        poll_interval=30.0,
        last_poll_ts=50.0,
        provider_available=True,
        now=81.0,
    ) is True


def test_should_poll_stays_false_without_provider() -> None:
    assert should_poll(
        poll_interval=30.0,
        last_poll_ts=50.0,
        provider_available=False,
        now=1_000.0,
    ) is False