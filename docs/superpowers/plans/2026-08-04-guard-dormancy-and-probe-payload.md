# Deploy-Trigger Guard: Dormancy Declaration + Probe Payload Redaction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two findings from the 2026-08-04 code review of `scripts/check_live_overlay_deploy_trigger.py` that were deliberately left open: exit code 0 still means two different things, and the credential probe still prints unaudited remote data into a CI log.

**Architecture:** Two independent changes to one script plus its test file. (1) The repo *declares* whether the watched deployment is configured, so a missing secret becomes exit 2 instead of a silent green — and the declaration is coupled to observable repo state so it cannot be flipped merely to silence the guard. (2) The probe's success payload is summarised through a field allowlist: structure and allowlisted leaves are printed, every other value is replaced by its type.

**Tech Stack:** Python 3.12 (stdlib only — `ast`, `json`, `urllib`), pytest, GitHub Actions, Railway GraphQL API.

## Global Constraints

- **Python:** always `/Users/spreuss/Documents/skipp-algo/.venv/bin/python`. The system `python3` is 3.9 and produces misleading `datetime.UTC` import errors.
- **Test invocation:** prefix `PYTHONPATH=/Users/spreuss/Documents/skipp-algo-wt-posix`. Work in the worktree `/Users/spreuss/Documents/skipp-algo-wt-posix`, never in `/Users/spreuss/Documents/skipp-algo` (that checkout holds a stale HEAD).
- **Never `--no-verify`.** A failing pre-push hook is signal.
- **Line-pinned ledger:** `pin_registry.toml` → `[urllib_urlopen_ledger.sites]` pins the exact line of the single `urllib.request.urlopen(` call in this script (currently `[131]`). If any edit shifts that line, re-pin it **in the same commit**, with a dated comment appended to the existing chain.
- **Push:** always `git push` via a backgrounded Bash call (`run_in_background: true`). A foreground timeout orphans the pre-push hook and reports a false exit code.
- **Stale bytecode:** run `find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null` before each test run.
- **Ruff:** `.venv/bin/python -m ruff check .` must be clean before every push. Exception classes need an `Error` suffix (N818); test function names must be snake_case (N802) or the lint-debt ledger regresses.
- **No secret values in output**, ever — neither token material nor remote payloads that were never audited.
- **Counter-proof rule:** every behavioural test in this plan must be shown to FAIL when its feature is reverted. A test that passes both ways is not evidence.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/check_live_overlay_deploy_trigger.py` | The guard: asks Railway whether the service has a native deploy trigger; `--probe` mode reports what each credential can read | Modify — add `_DEPLOYMENT_IS_CONFIGURED` + missing-secret branch (Task 1); add `_PAYLOAD_FIELDS` / `_summarize()` and use it in `_classify` (Task 2) |
| `tests/test_check_live_overlay_deploy_trigger.py` | The guard's exit-code and message contract; network is always mocked | Modify — 4 tests in Task 1, 4 tests in Task 2 |
| `pin_registry.toml` | Line-pinned ledgers | Modify only if the urlopen line moves |

Both tasks touch the same two files but disjoint regions. Task 1 edits `main()` (near line 453) and adds a constant near line 73. Task 2 edits `_classify` (near line 348). They can be done in either order; the plan assumes Task 1 first.

---

### Task 1: Dormancy must be declared, not inferred

**Why:** `main()` returns 0 both for "verified, no drift" and for "not configured, did not run". A deleted Actions secret therefore parks the guard on a permanent green whose message reads like the designed dormant state. This is the same failure family that kept the guard red for a week (a missing secret arrives as `""`, #4359) — silent this time instead of loud.

**Files:**
- Modify: `scripts/check_live_overlay_deploy_trigger.py` (constant near `:73`; `main()` at `:453-469`)
- Test: `tests/test_check_live_overlay_deploy_trigger.py`

**Interfaces:**
- Produces: module constant `_DEPLOYMENT_IS_CONFIGURED: bool` — read by `main()` and asserted by the coupling test. No function signature changes; `main(argv=None) -> int` keeps its contract, with exit 2 newly reachable for missing configuration.

- [ ] **Step 1: Write the four failing tests**

Append to `tests/test_check_live_overlay_deploy_trigger.py`:

```python
# --- dormancy must be declared, not inferred (2026-08-04) --------------------


def test_a_missing_secret_is_inconclusive_while_the_deployment_is_declared():
    """rc 0 used to mean BOTH "verified, no drift" and "did not run". So
    deleting one Actions secret parked the guard on a permanent green whose
    message reads like the designed dormant state."""
    mod = _load()
    assert mod._DEPLOYMENT_IS_CONFIGURED is True
    import os

    saved = {k: os.environ.get(k) for k in ("RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID")}
    try:
        os.environ["RAILWAY_API_TOKEN"] = "t"
        os.environ["RAILWAY_PROJECT_ID"] = "p"
        os.environ["RAILWAY_ENVIRONMENT_ID"] = ""
        assert mod.main() == 2
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_the_inconclusive_message_names_the_missing_secret_and_denies_health(
    monkeypatch, capsys
):
    mod = _load()
    monkeypatch.setenv("RAILWAY_API_TOKEN", "t")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "")

    rc = mod.main()

    out, err = capsys.readouterr()
    assert rc == 2
    assert "RAILWAY_ENVIRONMENT_ID" in err
    assert "RAILWAY_API_TOKEN" not in err  # only what is actually missing
    assert "verified NOTHING" in err
    assert "no native Railway deploy trigger" not in out


def test_an_undeclared_deployment_still_skips_green(monkeypatch):
    """The dormant case stays legitimate — but only when the repo says so."""
    mod = _load()
    monkeypatch.setattr(mod, "_DEPLOYMENT_IS_CONFIGURED", False)
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "p")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "e")

    def _boom(*a, **k):
        raise AssertionError("must not reach the network while dormant")

    monkeypatch.setattr(mod, "_fetch_triggers", _boom)
    assert mod.main() == 0


def test_the_declaration_cannot_be_flipped_to_silence_the_guard():
    """Anti-arbitrariness coupling. The declaration is only honest while the
    deployment exists, so flipping it requires ALSO retiring the deploy
    workflow — which is a reviewable change, not a quiet one."""
    mod = _load()
    deploy_workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "deploy-live-overlay-daemon.yml"
    )
    assert deploy_workflow.exists(), (
        "the daemon's deploy workflow is gone — if the deployment was retired, "
        "flip _DEPLOYMENT_IS_CONFIGURED to False in the same PR and update this test"
    )
    assert mod._DEPLOYMENT_IS_CONFIGURED is True
```

- [ ] **Step 2: Run them and watch them fail**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-posix
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_check_live_overlay_deploy_trigger.py -q --no-header -k "declared or declaration or undeclared or missing_secret"
```

Expected: `AttributeError: module has no attribute '_DEPLOYMENT_IS_CONFIGURED'` on three of them; the fourth (`test_an_undeclared_deployment_still_skips_green`) fails on `monkeypatch.setattr` for the same reason.

- [ ] **Step 3: Add the declaration**

In `scripts/check_live_overlay_deploy_trigger.py`, directly below `_DEFAULT_SERVICE_ID` (line 73):

```python
# Does the deployment this guard watches exist? This is a DECLARATION, not a
# probe — the guard cannot ask "am I supposed to be configured?" of an API it
# needs the missing credential to reach.
#
# It exists because exit 0 meant two different things: "verified, no drift" and
# "not configured, did not run". A deleted Actions secret therefore produced a
# permanent green whose message reads exactly like the designed dormant state.
# With this, a missing input is exit 2 while the daemon is deployed, and the
# dormant state requires a reviewed repo change instead of a quiet one in the
# GitHub settings UI. `test_the_declaration_cannot_be_flipped_to_silence_the
# _guard` couples it to the deploy workflow's existence so it cannot be used
# as a mute button.
_DEPLOYMENT_IS_CONFIGURED = True
```

- [ ] **Step 4: Split the missing-input branch**

Replace lines 462-469 (the `if missing:` block) with:

```python
    if missing and _DEPLOYMENT_IS_CONFIGURED:
        print(
            f"ERROR: {', '.join(missing)} not set, but this repo declares the "
            "live_overlay_daemon deployment as configured "
            "(_DEPLOYMENT_IS_CONFIGURED). A deleted or mistyped secret is not a "
            "healthy state — the guard has verified NOTHING. Restore the secret, "
            "or retire the deployment and flip the declaration in a reviewed PR.",
            file=sys.stderr,
        )
        return 2
    if missing:
        print(
            f"SKIP: {', '.join(missing)} not set and the deployment is declared "
            "unconfigured — deploy-trigger drift guard did not run.",
        )
        return 0
```

Leave the explanatory comment above `missing = [` in place; it still describes why the list names only what is absent.

- [ ] **Step 5: Run the whole file's tests**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_check_live_overlay_deploy_trigger.py -q --no-header
```

Expected: PASS, 46 tests (42 before + 4).

One older test asserts the SKIP path with **all three** variables absent — that still returns 0 only if the declaration is False. If `test_missing_token_skips_without_failing` now fails with rc 2, that is correct behaviour, not a regression: update it to `monkeypatch.setattr(mod, "_DEPLOYMENT_IS_CONFIGURED", False)` and add a one-line docstring saying the dormant case is now declared rather than inferred.

- [ ] **Step 6: Counter-proof each new test**

```bash
cp scripts/check_live_overlay_deploy_trigger.py /tmp/t1.bak
# Revert the split: make a missing input green again.
/Users/spreuss/Documents/skipp-algo/.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("scripts/check_live_overlay_deploy_trigger.py")
t = p.read_text()
p.write_text(t.replace("    if missing and _DEPLOYMENT_IS_CONFIGURED:", "    if missing and False:"))
EOF
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_check_live_overlay_deploy_trigger.py -q --no-header -k "missing_secret or names_the_missing"
cp /tmp/t1.bak scripts/check_live_overlay_deploy_trigger.py
```

Expected: 2 failed. Then restore and confirm the full file is green again.

For the coupling test, counter-proof by flipping the constant to `False` in a scratch copy and confirming `test_the_declaration_cannot_be_flipped_to_silence_the_guard` fails.

- [ ] **Step 7: Ledger check + ruff + commit**

```bash
grep -n "urlopen(req" scripts/check_live_overlay_deploy_trigger.py
```

The constant is added at ~line 73, which is **above** the urlopen call at 131 — so the pin **will** move (by the number of lines added, ~13). Re-pin `pin_registry.toml` in this commit: change `"scripts/check_live_overlay_deploy_trigger.py" = [131]` to the number `grep` reports, and append to the existing dated comment chain, e.g. `-> [144] (2026-08-04): the _DEPLOYMENT_IS_CONFIGURED declaration sits above the call site`.

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check --fix . && \
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_urllib_urlopen_ledger.py tests/test_check_live_overlay_deploy_trigger.py -q --no-header
git branch --show-current && git add scripts/check_live_overlay_deploy_trigger.py \
  tests/test_check_live_overlay_deploy_trigger.py pin_registry.toml && \
git commit -m "fix(ops): a deleted secret is not a healthy state"
```

The commit body must carry: the two meanings rc 0 used to have, the coupling that stops the declaration being a mute button, and the counter-proof results.

---

### Task 2: The probe must not echo unaudited remote data

**Why:** `_classify` prints `json.dumps(data)[:400]` on success. One of the four probe queries is `deployments.meta`, a free-form object whose contents Railway decides. GitHub masks *registered* secrets; it cannot mask what it was never told about. A CI log is not where you discover what a third party put in a field.

**Files:**
- Modify: `scripts/check_live_overlay_deploy_trigger.py` (`_classify` at `:348-366`, plus new constants and `_summarize` above it)
- Test: `tests/test_check_live_overlay_deploy_trigger.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `_summarize(value: object, key: str = "", depth: int = 0) -> str` and `_PAYLOAD_FIELDS: frozenset[str]`. `_classify(body) -> tuple[str, str]` keeps its signature; only the `OK` detail string changes shape.

- [ ] **Step 1: Write the four failing tests**

Append to `tests/test_check_live_overlay_deploy_trigger.py`:

```python
# --- the probe must not echo unaudited remote data (2026-08-04) --------------


def test_the_ok_summary_prints_structure_not_unknown_values(guard):
    """`deployments.meta` is Railway-controlled and free-form. Structure and
    allowlisted leaves are useful; arbitrary values are someone else's data in
    our log."""
    body = {
        "data": {
            "deployments": {
                "edges": [
                    {
                        "node": {
                            "id": "d1446af4",
                            "status": "SUCCESS",
                            "meta": {
                                "branch": "main",
                                "commitAuthor": "unaudited-value-42",
                            },
                        }
                    }
                ]
            }
        }
    }
    status, detail = guard._classify(body)
    assert status == "OK"
    assert "unaudited-value-42" not in detail
    assert "commitAuthor=<str>" in detail
    # Allowlisted leaves and the shape must survive — a summary nobody can read
    # would just get replaced by the raw dump again.
    assert "branch=" in detail and "main" in detail
    assert "status=" in detail and "SUCCESS" in detail
    assert "id=" in detail


def test_the_summary_keeps_the_answers_the_probe_exists_for(guard):
    """These two payloads decided real questions on 2026-08-03: an empty edge
    list means no trigger, and source.repo revealed that a connected repo is not
    a trigger. Both must stay legible."""
    empty = {"data": {"deploymentTriggers": {"edges": []}}}
    assert "[0 items]" in guard._classify(empty)[1]

    source = {
        "data": {
            "serviceInstance": {
                "id": "89b0b518",
                "source": {"image": None, "repo": "skipp-dev/skipp-algo"},
            }
        }
    }
    detail = guard._classify(source)[1]
    assert "skipp-dev/skipp-algo" in detail
    assert "image=None" in detail


def test_the_summary_is_bounded_in_width_and_depth(guard):
    deep = {"data": {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}}
    assert "…" in guard._classify(deep)[1]

    wide = {"data": {"edges": [{"node": {"name": f"svc-{i}"}} for i in range(200)]}}
    detail = guard._classify(wide)[1]
    assert len(detail) <= 401  # 400 + the ellipsis
    assert "[200 items" in detail


def test_the_summary_survives_shapes_that_are_not_objects(guard):
    assert guard._classify({"data": None})[1] == "{}"
    assert "[3 items" in guard._classify({"data": {"x": [1, 2, 3]}})[1]
```

- [ ] **Step 2: Run them and watch them fail**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_check_live_overlay_deploy_trigger.py -q --no-header -k "summary"
```

Expected: 4 failed — the raw `json.dumps` output contains `unaudited-value-42` and has no `<str>` / `[0 items]` markers.

- [ ] **Step 3: Add the allowlist and the summariser**

Insert directly above `def _classify(` (line 348):

```python
# Leaf values printed verbatim. Everything else is reported by TYPE, never by
# value: one of the probe's four queries is `deployments.meta`, a free-form
# object whose contents Railway decides, and this prints into a CI log. GitHub
# masks registered secrets; it cannot mask what it was never told about.
#
# The allowlist is the set of fields that actually answered a question here:
# `repo`/`image` refuted the source-as-trigger equivalence, `edges` counts
# answered "is there a trigger", and id/name/status/branch/provider identify
# WHICH object answered.
_PAYLOAD_FIELDS = frozenset(
    {"id", "name", "repo", "image", "status", "branch", "provider", "createdAt"}
)
_PAYLOAD_MAX = 400
_PAYLOAD_MAX_DEPTH = 4


def _summarize(value: object, key: str = "", depth: int = 0) -> str:
    """Structure in full, allowlisted leaves verbatim, everything else by type."""
    if depth > _PAYLOAD_MAX_DEPTH:
        return "…"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(
                f"{k}={_summarize(v, k, depth + 1)}" for k, v in sorted(value.items())
            )
            + "}"
        )
    if isinstance(value, list):
        if not value:
            return "[0 items]"
        # One representative element: the shape repeats, the values do not.
        return f"[{len(value)} items: {_summarize(value[0], key, depth + 1)}]"
    if value is None or isinstance(value, bool):
        return str(value)
    if key in _PAYLOAD_FIELDS:
        return json.dumps(value)[:80]
    return f"<{type(value).__name__}>"
```

- [ ] **Step 4: Route the OK branch through it**

Replace lines 364-366 of `_classify`:

```python
    if not errors:
        summary = _summarize(body.get("data") or {})
        return "OK", summary[:_PAYLOAD_MAX] + ("…" if len(summary) > _PAYLOAD_MAX else "")
```

Add to `_classify`'s docstring, after the existing paragraphs:

```
    The OK detail is a SUMMARY, not the payload: see `_summarize`. A probe that
    prints whatever a third-party API returns is a log-exfiltration surface, and
    the probe's value was always the shape of the answer, not its contents.
```

- [ ] **Step 5: Run the file's tests and check the real payload shapes**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_check_live_overlay_deploy_trigger.py -q --no-header
```

Expected: PASS, 50 tests (46 after Task 1 + 4).

Then eyeball the summariser against the two payloads the probe really returned, to confirm a human can still read the answer:

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -c "
import importlib.util
spec = importlib.util.spec_from_file_location('g', 'scripts/check_live_overlay_deploy_trigger.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
print(g._classify({'data': {'deploymentTriggers': {'edges': []}}})[1])
print(g._classify({'data': {'serviceInstance': {'id': '89b0b518', 'source': {'image': None, 'repo': 'skipp-dev/skipp-algo'}}}})[1])
"
```

Expected output:

```
{deploymentTriggers={edges=[0 items]}}
{serviceInstance={id="89b0b518", source={image=None, repo="skipp-dev/skipp-algo"}}}
```

- [ ] **Step 6: Counter-proof**

```bash
cp scripts/check_live_overlay_deploy_trigger.py /tmp/t2.bak
/Users/spreuss/Documents/skipp-algo/.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("scripts/check_live_overlay_deploy_trigger.py")
t = p.read_text()
p.write_text(t.replace("        summary = _summarize(body.get(\"data\") or {})",
                       "        summary = json.dumps(body.get(\"data\") or {}, sort_keys=True)"))
EOF
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_check_live_overlay_deploy_trigger.py -q --no-header -k "summary"
cp /tmp/t2.bak scripts/check_live_overlay_deploy_trigger.py
```

Expected: at least 3 failed (the raw dump leaks `unaudited-value-42` and loses the `[0 items]` / `<str>` markers). Restore, re-run the full file, confirm green.

Second counter-proof — widen the allowlist so it stops filtering:

```bash
# temporarily add "commitAuthor" to _PAYLOAD_FIELDS and re-run -k summary
```

Expected: `test_the_ok_summary_prints_structure_not_unknown_values` fails. This proves the allowlist is doing the work, not the summariser's shape.

- [ ] **Step 7: Ledger check + ruff + commit**

`_summarize` is inserted at ~line 348, **below** the urlopen call at its Task-1 position — so the pin does **not** move. Verify anyway:

```bash
grep -n "urlopen(req" scripts/check_live_overlay_deploy_trigger.py
```

Compare against `pin_registry.toml`; re-pin only if it differs.

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check --fix . && \
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
git add scripts/check_live_overlay_deploy_trigger.py tests/test_check_live_overlay_deploy_trigger.py && \
git commit -m "fix(ops): summarise the probe payload instead of echoing it"
```

---

### Task 3: Ship both

**Files:** none — this task is the gate.

- [ ] **Step 1: Full local suite via the pre-push hook**

```bash
git branch --show-current   # must NOT be main
```

Push in the background (a foreground timeout orphans the hook):

```bash
PYTEST_ADDOPTS="-n 4" git push -u origin fix/guard-dormancy-and-probe-payload
```

`-n 4` is mandatory: `-n auto` OOMs at rc=137 on 16 GB.

- [ ] **Step 2: Verify the push actually landed**

```bash
git rev-parse HEAD && git ls-remote origin refs/heads/fix/guard-dormancy-and-probe-payload
```

The two SHAs must match. A push piped into `tail` has reported exit 0 on a rejected push before — compare the refs, do not trust the exit code.

- [ ] **Step 3: Open the PR, wait for `fast-gates`**

`fast-gates` is the only required check (ADR-0011). Poll until `completed`; `mergeStateStatus` reports `UNKNOWN` for a few seconds after the run finishes — re-read it before concluding anything.

- [ ] **Step 4: Merge, then prove it in production**

```bash
gh pr merge <N> -R skipp-dev/skipp-algo --squash
gh workflow run live-overlay-deploy-trigger-guard.yml -R skipp-dev/skipp-algo --ref main
```

Expected in the log: `OK: live_overlay_daemon has no native Railway deploy trigger (CI-only).` — unchanged, because all three secrets are configured and no drift exists. **If this run reports exit 2 naming a missing secret, that is not a bug in the change — it is the finding**: a secret really is absent, and the guard was silently green about it until now. Report it, do not "fix" it by relaxing the declaration.

- [ ] **Step 5: Confirm the probe path too**

```bash
gh workflow run live-overlay-deploy-trigger-guard.yml -R skipp-dev/skipp-algo --ref main -f probe_credentials=true
```

Read the four candidate lines. Each must still show `OK` with a readable summary (`{deploymentTriggers={edges=[0 items]}}` and friends), and no free-form `meta` value may appear.

---

## Self-Review

**Spec coverage.** Two findings were left open by the 2026-08-04 review: the rc-0 ambiguity (the reviewer flagged it as a spec decision, not an implementation bug) → Task 1; the probe echoing an unaudited remote blob (M5) → Task 2. Both have tasks. No other review finding remains — C1, I1, I2, I3, M1, M2, M3, M4 and M6 shipped in #4366/#4367.

**Placeholder scan.** No TBDs. Every code step carries the literal code; every test step carries the literal test; every command is runnable as written.

**Type consistency.** `_DEPLOYMENT_IS_CONFIGURED` is a plain `bool` module constant in Task 1, read by `main()` and monkeypatched by name in two tests — same spelling throughout. `_summarize(value, key, depth)` is called recursively with the same three positional parameters and from `_classify` with one, matching its defaults. `_PAYLOAD_MAX` is used once for slicing and once for the ellipsis test's bound (400 + 1).

**Known interaction.** Task 1 changes exit codes for the missing-input case, which one pre-existing test (`test_missing_token_skips_without_failing`) asserts. Step 5 of Task 1 names it explicitly and says how to update it — an engineer reading only Task 1 will not be surprised by it.
