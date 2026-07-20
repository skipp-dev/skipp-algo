"""Private Producer client for interactive Terminal AI Insights."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from terminal_internal_feed import private_producer_url

_SCHEMA_VERSION = 1
_MAX_REQUEST_BYTES = 900_000
_MAX_RESPONSE_BYTES = 500_000


class ProducerAIError(RuntimeError):
    """A safe, operator-facing Producer AI failure."""


@dataclass(frozen=True)
class ProducerAIResponse:
    """Validated AI response returned by the private Producer."""

    answer: str
    model: str
    cached: bool
    context_articles: int
    context_tickers: int
    fmp_tickers: int
    error: str = ""


class ProducerAIInsightsClient:
    """Send bounded AI Insights requests over Railway private networking."""

    def __init__(
        self,
        producer_url: str,
        token: str,
        *,
        timeout_s: float = 150.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = private_producer_url(producer_url, endpoint_path="/ai-insights")
        self._token = str(token or "").strip()
        if not self._token:
            raise ValueError("producer AI token is empty")
        if timeout_s <= 0:
            raise ValueError("producer AI timeout must be greater than zero")
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(float(timeout_s)),
            follow_redirects=False,
        )

    def query(self, *, question: str, context_json: str) -> ProducerAIResponse:
        """Return one inspected Producer-side LLM response."""
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "question": str(question or "").strip(),
            "context_json": str(context_json or ""),
        }
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if not payload["question"]:
            raise ProducerAIError("AI question is empty")
        if len(encoded) > _MAX_REQUEST_BYTES:
            raise ProducerAIError("AI Insights request exceeds the size limit")

        try:
            with self._client.stream(
                "POST",
                self._url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                content=encoded,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise ProducerAIError(
                        f"Producer AI request failed with HTTP {response.status_code}"
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise ProducerAIError("Producer AI response exceeds the size limit")
        except ProducerAIError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise ProducerAIError(
                f"Producer AI transport failed ({type(exc).__name__})"
            ) from exc

        try:
            data: Any = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProducerAIError("Producer AI returned invalid JSON") from exc
        if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
            raise ProducerAIError("Producer AI schema version is unsupported")

        answer = data.get("answer")
        if not isinstance(answer, str):
            raise ProducerAIError("Producer AI response is missing an answer")
        return ProducerAIResponse(
            answer=answer,
            model=str(data.get("model") or ""),
            cached=bool(data.get("cached", False)),
            context_articles=int(data.get("context_articles") or 0),
            context_tickers=int(data.get("context_tickers") or 0),
            fmp_tickers=int(data.get("fmp_tickers") or 0),
            error=str(data.get("error") or ""),
        )
