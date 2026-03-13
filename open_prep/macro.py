from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FMPClient:
    api_key: str

    def get_profile_bulk(self) -> list[dict[str, Any]]:
        return []

    def get_company_screener(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def screener(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []
