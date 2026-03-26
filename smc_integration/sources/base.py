from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass(frozen=True)
class SourceCapabilities:
    has_structure: bool
    has_meta: bool
    structure_mode: Literal["full", "partial", "none"]
    meta_mode: Literal["full", "partial", "none"]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SourceDescriptor:
    name: str
    path_hint: str
    capabilities: SourceCapabilities
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["capabilities"] = self.capabilities.to_dict()
        return payload
