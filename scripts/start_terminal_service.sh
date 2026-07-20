#!/usr/bin/env bash
set -Eeuo pipefail

env -u TERMINAL_ACCESS_TOKEN streamlit run streamlit_terminal.py \
  --server.port=8501 \
  --server.address=127.0.0.1 &
streamlit_pid=$!

env -u TERMINAL_ACCESS_TOKEN python -m scripts.run_terminal_candidate_mirror &
candidate_mirror_pid=$!

/usr/local/bin/terminal-access-proxy &
proxy_pid=$!

shutdown() {
  kill -TERM "$streamlit_pid" "$candidate_mirror_pid" "$proxy_pid" 2>/dev/null || true
  wait "$streamlit_pid" "$candidate_mirror_pid" "$proxy_pid" 2>/dev/null || true
}
trap shutdown EXIT INT TERM

wait -n "$streamlit_pid" "$candidate_mirror_pid" "$proxy_pid"
status=$?
exit "$status"
