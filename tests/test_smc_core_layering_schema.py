from __future__ import annotations

import inspect

from smc_core import apply_layering, derive_base_signals, normalize_meta
from smc_core.layering import BaseLayerSignals, NormalizedMeta


def test_layering_public_signatures() -> None:
    assert tuple(inspect.signature(apply_layering).parameters) == ("structure", "meta")
    assert tuple(inspect.signature(normalize_meta).parameters) == ("meta",)
    assert tuple(inspect.signature(derive_base_signals).parameters) == ("normalized",)


def test_layering_internal_typed_dicts_exist() -> None:
    assert isinstance(NormalizedMeta.__annotations__, dict)
    assert isinstance(BaseLayerSignals.__annotations__, dict)
