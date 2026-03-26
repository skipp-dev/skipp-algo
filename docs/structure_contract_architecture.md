# Structure Contract Normalization Architecture

## Status

Accepted and active on main.

This document defines the integration architecture boundary for structure contract normalization.
It exists to prevent contract drift across source, service, provider matrix, and audit paths.

## Scope

Applies to:
- smc_integration/structure_contract.py
- smc_integration/sources/structure_artifact_json.py
- smc_integration/service.py
- smc_integration/provider_matrix.py
- smc_integration/structure_audit.py

## Problem Statement

Before centralization, structure contract interpretation was distributed across multiple consumers.
That created three risks:

1. Semantic drift between source, service, matrix, and audit.
2. Multiple legacy interpretation paths that could diverge over time.
3. Mixing canonical snapshot structure with meta and transparency data.

## Target Architecture

### Canonical Snapshot Boundary

snapshot.structure stays canonical and contains only:
- bos
- orderblocks
- fvg
- liquidity_sweeps

No auxiliary or diagnostics fields are allowed inside snapshot.structure.

### Additive Context Boundary

structure_context is additive delivery metadata and may include:
- structure_profile_used
- event_logic_version
- coverage
- counts
- warnings

This boundary keeps snapshot consumers stable while preserving transparency.

### Legacy Handling Policy

Legacy payload forms (including entries[]) are accepted only at ingress.
After ingress normalization, internal consumers operate on a single normalized representation.

## Central Internal Normal Form

The normalized internal contract contains:
- canonical_structure
- structure_context
- coverage
- counts
- structure_profile_used
- event_logic_version
- warnings
- optional auxiliary

The normalization source of truth is smc_integration/structure_contract.py.

## Module Responsibilities

### smc_integration/structure_contract.py

Single source of truth for:
- legacy and current payload normalization
- normalized contract representation
- capability and category summary derivation

### smc_integration/sources/structure_artifact_json.py

Ingress adapter for structure artifacts:
- resolves manifest and deterministic artifact files
- normalizes payloads via structure_contract module
- exposes normalized summary and canonical structure/context inputs

### smc_integration/service.py

Delivery orchestration:
- builds canonical snapshot from canonical structure plus meta
- attaches structure_context additively in bundle output

### smc_integration/provider_matrix.py

Provider capability/current mapping view derived from the normalized summary.
No independent contract semantics are implemented here.

### smc_integration/structure_audit.py

Audit and gap reporting view derived from the same normalized summary.
No parallel contract interpretation path is allowed.

## Guardrails

1. Do not place auxiliary or diagnostics payloads into snapshot.structure.
2. Do not add new legacy interpretation logic outside ingress adapters.
3. Do not implement a second contract semantic in service, matrix, or audit.
4. Do not add SMC detection heuristics in integration consumers.

## Backward Compatibility

1. Legacy entries[] ingestion remains supported at ingress.
2. Public snapshot structure remains unchanged.
3. structure_context remains additive and optional in bundle delivery.

## Change Control Notes

If the normalized representation changes, update these in lockstep:
- structure_contract normalization logic
- source adapter summary/input wiring
- provider matrix and audit consumers
- contract-focused integration tests
