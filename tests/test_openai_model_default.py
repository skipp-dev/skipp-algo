from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import terminal_ai_insights as ai
import terminal_fmp_insights as fmp


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"choices": [{"message": {"content": "answer"}}]}


@pytest.mark.parametrize(
    ("module", "query"),
    [
        (ai, ai.query_llm),
        (fmp, fmp.query_fmp_llm),
    ],
)
def test_openai_default_uses_luna_with_gpt_4o_compatible_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    query: object,
) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _Response()
    monkeypatch.setattr(module, "inspect_messages", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module.httpx, "Client", lambda *_args, **_kwargs: client)
    module._cache.clear()

    result = query("question", "{}", "openai-test-key")

    assert result.model == "gpt-5.6-luna"
    payload = client.post.call_args.kwargs["json"]
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["reasoning_effort"] == "none"
    assert payload["max_completion_tokens"] == 2500
    assert "max_tokens" not in payload
