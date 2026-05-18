# Performance profiling reports

Generated artifacts from the perf-profiling helpers. None of these reports
are read by any production code path; they exist purely as historical
baselines for the optimization program.

## Helpers

- `scripts/profile_pytest_durations.py` — wraps `pytest --durations` and
  writes `pytest_durations_<UTC-date>.md` here.

> Reports may be regenerated and committed at any time; older ones can be
> deleted whenever their data is no longer interesting.
