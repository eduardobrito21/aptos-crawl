# ADR-007: Qualitative criteria extraction via keyword matching

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 009

## Context

The most important criteria (gas-heated shower, acoustic glass, AC,
kitchen layout, suite + half-bath) aren't in structured fields —
they're in the listing's prose description and in non-standard
"features" lists.

Options:

- **Keyword/regex matching:** fast, deterministic, fails on
  paraphrases.
- **LLM extraction:** robust, but adds a dependency (API key,
  latency, cost) and variability.
- **Hybrid:** keyword first, LLM as fallback for null fields.

## Decision

**Keyword matching only, in v1.** Reasons:

1. Real-estate ads use conventional, repetitive vocabulary ("chuveiro
   a gás", "aquecimento a gás", "Rinnai" → all = gas-heated shower).
2. False negatives (the field stays null) are preferable to false
   positives. Eduardo confirms in Notion during the virtual tour.
3. Adding LLM extraction later is trivial if needed; removing it
   isn't (see [ADR-009](009-llm-enrichment.md)).

Implementation in `pipeline/extract.py`:

- Keyword list per criterion in
  [`config/keywords.yaml`](../../config/keywords.yaml)
- Case-insensitive match with accents normalized
- Tri-state result: `True` (positive keyword found), `False` (explicit
  negative keyword found, e.g. "chuveiro elétrico"), `None` (not
  mentioned)
- Notion shows a checked checkbox for `True`, empty for `False`/`None`
  — Eduardo distinguishes them during review

## Consequences

- **Positive:** zero external dependencies, deterministic, debuggable.
- **Negative:** will miss some mentions. Acceptable since SC2/SC3
  don't depend on this.
- **Neutral:** if null rate exceeds 50% on a criterion, open an ADR
  for LLM extraction on that specific field (already covered by
  [ADR-009](009-llm-enrichment.md)).
