"""Guard the Databento live-client contract assumed by feed.py.

feed.py instantiates db.Live(key=...) and iterates without calling
client.start(). In databento>=0.79 this is the documented path; calling
start() explicitly would raise ValueError. This test pins that behaviour
so a future dependency upgrade cannot silently invalidate the feed loop.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import databento as db


class TestDatabentoLiveIteratorContract:
    """db.Live must be iterable without an explicit start() call."""

    def test_live_start_before_iteration_raises_value_error(self) -> None:
        """Calling start() before iterating must fail per current Databento contract."""
        client = db.Live(key="dummy-key-for-contract-test")

        # Prevent any real network connection; we only care about the state
        # machine contract between subscribe() and start().
        fake_session = MagicMock()
        fake_session.is_connected.return_value = True
        with patch.object(client, "_session", fake_session):
            client.subscribe(
                dataset="EQUS.MINI",
                schema="ohlcv-1m",
                symbols="ALL_SYMBOLS",
                stype_in="raw_symbol",
            )
            with pytest.raises(ValueError):
                client.start()
