"""Regression test for PR-K (audit pass 2 closeout, 2026-05-10).

Pin that the Benzinga WS adapter logs (at DEBUG) when the optional
subscribe handshake raises. Pre-fix it was ``except: pass`` which
hid observability of upstream protocol changes.

The handshake itself is optional (Benzinga's server pushes news
regardless), so this is observability hardening, not a bug fix.
"""

from __future__ import annotations

import inspect

from newsstack_fmp import ingest_benzinga


def test_benzinga_ws_subscribe_handshake_logs_on_failure():
    """Source-pin: the optional subscribe handshake MUST log at
    debug with exc_info on failure, never silently swallow."""
    src = inspect.getsource(ingest_benzinga)
    # The legacy pattern MUST be gone.
    assert "await ws.send(auth_msg)\n                    except Exception:\n                        pass" not in src, (
        "PR-K: silent except: pass on Benzinga WS subscribe handshake "
        "must be replaced with logger.debug(..., exc_info=True)."
    )
    # The new pattern MUST be present.
    assert "optional subscribe handshake" in src, (
        "PR-K: Benzinga WS subscribe handshake failure must be logged "
        "with a recognisable message."
    )
    assert "exc_info=True" in src, (
        "PR-K: Benzinga WS subscribe handshake failure must include "
        "exc_info=True for operator triage."
    )
