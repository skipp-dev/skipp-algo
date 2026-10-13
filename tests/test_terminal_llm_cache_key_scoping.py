"""Regression tests for PR-J3 (audit pass 2, 2026-05-10).

Pin api_key fingerprint scoping of the LLM response cache in
``terminal_ai_insights`` and ``terminal_fmp_insights``.

Pre-PR-J3, ``_cache_key(question, context_digest, model)`` did NOT
include the OpenAI API key. Two callers with different OpenAI keys
submitting the same (question, context, model) tuple shared cached
LLM completions — cross-account response leakage.
"""

from __future__ import annotations

import inspect

import pytest

import terminal_ai_insights as ai
import terminal_fmp_insights as fmp


@pytest.mark.parametrize("module", [ai, fmp], ids=["ai_insights", "fmp_insights"])
def test_cache_key_signature_includes_api_key(module):
    """Contract: _cache_key MUST accept api_key as a parameter."""
    sig = inspect.signature(module._cache_key)
    assert "api_key" in sig.parameters, (
        f"PR-J3: {module.__name__}._cache_key must accept an api_key "
        "parameter to partition the cache by OpenAI key."
    )


@pytest.mark.parametrize("module", [ai, fmp], ids=["ai_insights", "fmp_insights"])
def test_cache_key_differs_across_api_keys(module):
    """Same question + context + model but different api_key MUST
    produce different cache keys (no cross-account leakage)."""
    k_a = module._cache_key("What is AAPL?", "ctxhash", "gpt-4", "sk-aaa-111")
    k_b = module._cache_key("What is AAPL?", "ctxhash", "gpt-4", "sk-bbb-222")
    assert k_a != k_b, (
        f"PR-J3: {module.__name__}._cache_key must differ across "
        "OpenAI API keys to prevent cross-account LLM response sharing."
    )


@pytest.mark.parametrize("module", [ai, fmp], ids=["ai_insights", "fmp_insights"])
def test_cache_key_stable_for_same_api_key(module):
    """Determinism: same inputs MUST yield the same key."""
    k1 = module._cache_key("Q", "ctx", "gpt-4", "sk-same")
    k2 = module._cache_key("Q", "ctx", "gpt-4", "sk-same")
    assert k1 == k2


@pytest.mark.parametrize("module", [ai, fmp], ids=["ai_insights", "fmp_insights"])
def test_cache_key_differs_across_questions(module):
    """Sanity: question still participates in the key."""
    k_q1 = module._cache_key("Q1", "ctx", "gpt-4", "sk-same")
    k_q2 = module._cache_key("Q2", "ctx", "gpt-4", "sk-same")
    assert k_q1 != k_q2


@pytest.mark.parametrize(
    "module,call_site_line",
    [(ai, 223), (fmp, 425)],
    ids=["ai_insights", "fmp_insights"],
)
def test_call_site_passes_api_key(module, call_site_line):
    """Source-pin: the production call site MUST pass api_key into
    _cache_key, otherwise the fingerprint scoping is dead code."""
    src = inspect.getsource(module)
    assert "_cache_key(question, digest, model, api_key)" in src, (
        f"PR-J3: {module.__name__} call site must invoke "
        "_cache_key(question, digest, model, api_key)."
    )
    # And the legacy 3-arg call form MUST be gone.
    assert "_cache_key(question, digest, model)" not in src.replace(
        "_cache_key(question, digest, model, api_key)", ""
    )
