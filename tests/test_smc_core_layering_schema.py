from __future__ import annotations

import inspect

from smc_core import apply_layering, derive_base_signals, normalize_meta
from smc_core.layering import BaseLayerSignals, NormalizedMeta


def test_layering_public_signatures() -> None:
    sig = inspect.signature(apply_layering)
    assert tuple(sig.parameters) == ("structure", "meta", "generated_at")
    assert sig.parameters["generated_at"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["generated_at"].default is None
    assert tuple(inspect.signature(normalize_meta).parameters) == ("meta",)
    assert tuple(inspect.signature(derive_base_signals).parameters) == ("nm",)


def test_layering_internal_typed_dicts_exist() -> None:
    assert isinstance(NormalizedMeta.__annotations__, dict)
    assert isinstance(BaseLayerSignals.__annotations__, dict)
