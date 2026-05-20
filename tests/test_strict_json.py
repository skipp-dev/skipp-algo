from __future__ import annotations

import json
from decimal import Decimal

import pytest

from scripts.strict_json import dumps_strict_json


def test_dumps_strict_json_sanitizes_native_non_finite_numbers() -> None:
    payload = json.loads(
        dumps_strict_json(
            {
                "nan": float("nan"),
                "pos_inf": float("inf"),
                "neg_inf": float("-inf"),
                "finite": 1.25,
            },
            sort_keys=True,
        )
    )
    assert payload == {"finite": 1.25, "nan": None, "neg_inf": None, "pos_inf": None}


def test_dumps_strict_json_sanitizes_decimal_non_finite_numbers() -> None:
    payload = json.loads(
        dumps_strict_json(
            {
                "nan": Decimal("NaN"),
                "pos_inf": Decimal("Infinity"),
                "finite": Decimal("1.5"),
            },
            sort_keys=True,
        )
    )
    assert payload == {"finite": 1.5, "nan": None, "pos_inf": None}


def test_dumps_strict_json_sanitizes_numpy_scalar_numbers() -> None:
    np = pytest.importorskip("numpy")
    payload = json.loads(
        dumps_strict_json(
            {
                "nan64": np.float64("nan"),
                "inf32": np.float32("inf"),
                "finite32": np.float32("1.25"),
                "int64": np.int64(7),
            },
            sort_keys=True,
        )
    )
    assert payload == {"finite32": 1.25, "inf32": None, "int64": 7, "nan64": None}
