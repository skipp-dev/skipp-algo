"""Guard the Databento live-client start() contract assumed by feed.py.

feed.py instantiates db.Live(key=...) and iterates without calling
client.start(). In databento>=0.79, calling start() explicitly after
subscribe() raises ValueError. This test pins that behaviour so a future
dependency upgrade cannot silently invalidate the feed loop assumptions.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import databento as db
import pytest


class TestDatabentoLiveStartContract:
    """db.Live.start() must raise after subscribe() in current contract."""

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
