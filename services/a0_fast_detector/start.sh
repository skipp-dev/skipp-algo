#!/usr/bin/env bash
# A0-Fast shadow worker entrypoint.
#
# Default: exec the worker directly (behavior identical to the previous
# startCommand). With RT_PRE_A0_PILOT=1 the worker's log stream is piped
# through the read-only pilot alert tailer (see README, "PRE-A0 Pilotbetrieb").
# pipefail keeps ON_FAILURE restart semantics tied to the worker's exit code.
set -euo pipefail
if [ "${RT_PRE_A0_PILOT:-0}" = "1" ]; then
  exec bash -o pipefail -c \
    'python -m services.a0_fast_detector.worker 2>&1 | python -m services.a0_fast_detector.pilot_alert_tailer'
else
  exec python -m services.a0_fast_detector.worker
fi
