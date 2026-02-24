"""newsstack_fmp – multi-source news polling for realtime signals.

Supports FMP (polling) + Benzinga (REST delta + WebSocket streaming)
with unified normalisation, cursor/state, dedupe/novelty, scoring,
enrichment, and open_prep JSON export.

Designed to be polled synchronously on each Streamlit refresh via
``poll_once()``.  Benzinga WebSocket (if enabled) runs in a daemon
thread and feeds items through a thread-safe queue.
"""
