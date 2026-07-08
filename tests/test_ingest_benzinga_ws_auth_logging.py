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
    debug with exc_info on failure, never silently swallow.

    Hardened 2026-07-08: the old assertions matched the WHOLE module
    source — any ``exc_info=True`` anywhere (or the phrase surviving in
    a comment) kept them green even if the handshake handler regressed
    to ``except: pass``. The legacy-pattern check was also pinned to an
    exact 20-space indentation, so a re-indent would have blinded it.
    Anchor on the handshake send and assert within that block only,
    whitespace-normalised.
    """
    src = inspect.getsource(ingest_benzinga)
    anchor = src.index("await ws.send(auth_msg)")
    block = src[anchor : anchor + 900]
    normalized = " ".join(block.split())
    # The legacy silent-swallow pattern MUST be gone (indentation-proof).
    assert "except Exception: pass" not in normalized, (
        "PR-K: silent except: pass on Benzinga WS subscribe handshake "
        "must be replaced with logger.debug(..., exc_info=True)."
    )
    # The handler itself (not some other code path) must log with traceback.
    assert "logger.debug(" in block, (
        "PR-K: the subscribe-handshake except handler must log at debug."
    )
    assert "exc_info=True" in block, (
        "PR-K: Benzinga WS subscribe handshake failure must include "
        "exc_info=True for operator triage."
    )
    assert "optional subscribe handshake" in block, (
        "PR-K: Benzinga WS subscribe handshake failure must be logged "
        "with a recognisable message."
    )
    # The handler must swallow-and-continue (handshake is optional): no
    # re-raise inside the handler block.
    handler_start = normalized.index("except Exception:")
    handler = normalized[handler_start:]
    assert "raise" not in handler.split("async for", 1)[0], (
        "PR-K: the optional handshake must not abort the connection on failure"
    )
