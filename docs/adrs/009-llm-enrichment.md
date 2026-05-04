# ADR-009: LLM as a complementary enrichment layer

**Status:** Proposed
**Date:** 2026-05-04
**Related:** 007, 010

## Context

[ADR-007](007-qualitative-extraction.md) establishes keyword matching
as the primary method for extracting qualitative criteria. It's fast,
deterministic, dependency-free — but has clear limits:

1. **Non-literal paraphrases.** "Aquecimento via central" is probably
   gas heating, but doesn't match the keywords. "Banheiro com ducha
   auxiliar" might be a bidet shower, but the term varies.
2. **Contextual criteria.** "Suite + half-bath" has no fixed keyword
   — it's inferred from the combination (1 bedroom + 2 bathrooms +
   description).
3. **New criteria.** Eduardo may want to add criteria later
   ("varanda gourmet", "tree-lined street", "recently renovated")
   without writing rules for each one.
4. **Non-binary qualitative signals.** "Light" isn't yes/no — it's
   "great/good/medium/poor". Description text has nuance that
   keywords don't capture.

Brazilian real-estate ads have conventions but also a lot of
stylistic variation. LLM extraction handles this kind of problem
well.

## Decision

Add an **LLM-backed enrichment layer** that **complements** (does
not replace) keyword matching:

1. **Keyword matching first** ([ADR-007](007-qualitative-extraction.md))
   fills what it can with high confidence.
2. **LLM extraction runs on null fields** or on fields where we want
   nuance beyond a boolean.
3. **LLM results have flag `extracted_by = 'llm'`** in SQLite (column
   in [`db/schema.sql`](../../db/schema.sql)) — auditable; Eduardo can
   spot-check.

Stance and guardrails:

- **Model:** Claude Haiku via API (low cost, acceptable latency).
  Sonnet only if Haiku consistently misses.
- **Off by default in v1.** `enrichment.llm: false` in
  `filters.yaml`. Enable when keyword matching is mature.
- **LLM never overwrites a field already filled by keyword** —
  keyword is cheaper and more reliable when it matches.
- **Cost guardrail:** daily cap (`LLM_DAILY_BUDGET_USD`, default
  1.00).

Concrete implementation (Pydantic schema, prompt structure, cache
key, pipeline pseudo-code) lives in
[exec-plans/active/0007-llm-enrichment.md](../exec-plans/active/0007-llm-enrichment.md)
and activates when the toggle flips.

## Consequences

- **Positive:**
  - Fills fields that keyword misses (paraphrases, context, nuance).
  - Adding a new criterion becomes a prompt change, not a code
    change.
  - `extracted_by` flag gives auditability.
- **Negative:**
  - External dependency (API key, network, cost).
  - Variability — the same HTML can yield slightly different results
    across runs. Mitigation: temperature=0, schema validation, cache.
  - Cost grows if scale grows. Estimate: ~100 listings × ~2k tokens ×
    Haiku = a few cents per run, acceptable.

## Acceptance criteria (Proposed → Accepted)

Validate against 10–20 real listings before marking Accepted:

- LLM fills ≥ 70% of the nulls keyword left, with `confidence: high`.
- Eduardo agrees with ≥ 80% of extractions in manual review.
- Average cost per run < $0.10.
