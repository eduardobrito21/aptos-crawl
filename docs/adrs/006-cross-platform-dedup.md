# ADR-006: Cross-platform dedup via heuristic fingerprint

**Status:** Proposed
**Date:** 2026-05-04

## Context

The same apartment appears across multiple platforms with different
IDs, different photos, and sometimes slightly different prices.
Without dedup, Eduardo will see the same apartment 3–4 times in
Notion.

There is no unique key (zip code + street number isn't exposed
consistently; coordinates rarely come through).

## Decision

Implement a **heuristic fingerprint** with 3 levels:

1. **Strong match (auto-merge):** same (normalized street + area
   ± 1 m² + bedrooms + parking spots). High probability of being the
   same property.
2. **Weak match (flag for review):** same (street + neighborhood +
   area ± 5 m² + bedrooms), prices differing > 10%. Insert as a
   separate apartment but with `possible_dup_of` flag set.
3. **No match:** new entry.

Address normalization (`endereco_normalized` in
[`db/schema.sql`](../../db/schema.sql)):

- lowercase, strip accents
- remove prefixes (`rua`, `avenida`, `r.`, `av.`, `alameda`)
- remove the street number (varies between platforms; many omit it)
- exact match on the rest

Don't attempt cross-neighborhood matches (the same apartment isn't in
both Pinheiros and Itaim simultaneously).

**Not in v1:** photo-based dedup (perceptual hash). Add only if SC2
(precision ≥ 80%) isn't met with the textual fingerprint.

## Consequences

- **Positive:** simple, transparent, debuggable (just log the
  fingerprint).
- **Negative:** it will be wrong sometimes. False positives (incorrect
  merge) and false negatives (missed duplicate) are expected.
  Mitigation: `possible_dup_of` flag + `v_possible_dups` view in
  SQLite for manual review.
- **Status Proposed:** validate against real data before marking
  Accepted. If precision < 80%, add photo perceptual hashing.
