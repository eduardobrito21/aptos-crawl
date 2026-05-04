# Plan 0007 — LLM enrichment activation

**Status:** Inactive
**Trigger:** ADR-009 acceptance criteria met (LLM fills ≥ 70% of
keyword-nulls with `confidence: high` and Eduardo agrees with ≥ 80% in
a 10–20 anúncio manual review). Flip `enrichment.llm: true` in
`config/filters.yaml`.
**Depends on:** Plans 0001 + 0002 (need keyword extraction running
first so we know where the nulls are).
**Decision:** [docs/adrs/009-llm-enrichment.md](../../adrs/009-llm-enrichment.md)

## Goal

Add a Claude-Haiku-backed LLM extraction layer that complements (does
not replace) keyword matching. Fills nulls with confidence + evidence
so Eduardo can audit.

## Out of scope

- LLM as primary extractor (ADR-009 §Decision: keyword wins where it
  matches).
- Vision-based extraction from photos (ADR-009 OQ2 — defer to v2).
- Subjective scoring (luminosidade, ruído percebido) as binary fields
  (ADR-009 OQ1 — try, but mark `confidence: low`).

## Steps

1. **Pydantic schema** in `aptos_sp/pipeline/llm_schema.py`:
   - Tri-state booleans for binary criteria.
   - Enum / string for layout, qualidade de luminosidade, tipo de rua.
   - `confidence: 'high' | 'medium' | 'low'` per field.
   - `evidence: str` per field (anúncio excerpt that justifies the
     extraction).
2. **Prompt** as a Python constant in `aptos_sp/pipeline/llm_enrich.py`:
   - Single multi-field request (one Anthropic API call per anúncio,
     not N calls).
   - Temperature = 0.
   - System prompt enforces JSON-only output matching the schema.
3. **Pipeline integration:**
   - After `pipeline/extract.py` runs (Plan 0002), gather rows with
     null fields where keyword failed.
   - Call LLM, validate response with the pydantic schema.
   - Merge: LLM never overwrites a non-null keyword result.
   - Mark `extracted_by` column: `'keyword'`, `'llm'`, or `'mixed'`.
4. **Cache** by `(source_id, raw_html_hash)` — re-extract only if HTML
   changed.
5. **Cost tracking:**
   - Log per-call cost in `runs.llm_cost_usd`.
   - Respect `LLM_DAILY_BUDGET_USD` cap; short-circuit with warning.
6. **Audit view:**
   - `v_llm_extractions` showing rows with `extracted_by IN ('llm', 'mixed')`
     so Eduardo can spot-check.

## Definition of done

- With `enrichment.llm: true`, ≥ 70% of previously-null fields are
  filled with `confidence: high`.
- Cost per run < $0.10 on a normal batch (~100 aptos).
- Manual spot-check on 20 anúncios shows ≥ 80% agreement.
- ADR-009 status flipped from `Proposed` to `Accepted`.

## Open questions

- See ADR-009 OQs.

## Decision log

_Empty. Plan is Inactive until trigger fires._
