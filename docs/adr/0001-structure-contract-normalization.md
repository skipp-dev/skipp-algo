# ADR 0001: Centralized Structure Contract Normalization

## Status

Accepted.

## Date

2026-03-26

## Context

The structure contract semantics were previously interpreted in multiple integration consumers.
This created drift risk between source, service, provider matrix, and audit, and increased the
risk of mixing canonical snapshot structure with delivery transparency metadata.

## Decision

1. Structure contract normalization is centralized in one internal normalization layer.
2. snapshot.structure remains canonical-only and contains only:
   - bos
   - orderblocks
   - fvg
   - liquidity_sweeps
3. structure_context is the additive delivery/transparency layer for contract and metadata fields.
4. Legacy payload forms (including entries[]) are accepted only at ingress and normalized there.

## Rationale

1. Prevents distributed contract semantics and consumer divergence.
2. Keeps source, service, provider matrix, and audit on one normalized interpretation path.
3. Preserves snapshot contract stability for downstream consumers.
4. Preserves backward compatibility while constraining legacy handling to ingress.

## Consequences

1. Consumers must not implement a second contract semantic.
2. auxiliary and diagnostics payloads must not be placed into snapshot.structure.
3. New legacy fallback interpretations must only be implemented at ingress.
4. Detailed technical architecture remains in:
   - docs/structure_contract_architecture.md
   - docs/smc-snapshot-target-architecture.md

## Scope

Applies to integration-layer structure contract handling and delivery shaping.
No SMC detection heuristic changes are introduced by this decision.
