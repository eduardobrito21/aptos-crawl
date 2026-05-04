# Plan 0002 — Milestone 2: detail-page enrichment + cross-platform dedup

**Status:** Not started
**Depends on:** Plan 0001 (need ZAP data flowing into `aptos.db`)

## Goal

For each listing, visit the detail page and extract qualitative criteria
via keyword matching (ADR-007). Add a heuristic dedup pass (ADR-006)
that flags suspected duplicates without auto-merging incorrectly.

## Out of scope

- LLM extraction (Inactive plan 0007)
- Photo perceptual-hash dedup (only if SC2 < 80%, per ADR-006)
- Notion export (M3)

## Steps

1. Implement `aptos_sp/pipeline/extract.py`:
   - Load `keywords.yaml`, normalize text (lowercase + strip accents).
   - Tri-state matcher per criterion: positive list → True, negative
     list → False, neither → None.
   - Special handler for `cozinha_layout` (sub-keyed shape, not
     positive/negative — see code comment in `keywords.yaml`).
2. Implement `aptos_sp/pipeline/normalize.py`:
   - `normalize_endereco(s)` — lowercase, strip accents, drop street
     prefixes and numbers.
   - `area_min_with_flex(filters, listing)` — applies the
     `area_min_m2_flex` rule (the conditional that lives in code, not
     YAML).
3. Implement `aptos_sp/pipeline/dedup.py`:
   - Fingerprint builder per ADR-006 (rua_normalizada + area + quartos
     + vagas).
   - 3-tier classifier: strong → set `possible_dup_of` to canonical
     row; weak → flag; none → leave alone.
   - View `v_possible_dups` already in `db/schema.sql`; verify it
     surfaces the cases.
4. Implement `aptos_sp/cli/enrich.py`:
   - For each apto with `raw_html_hash` changed since last enrich, fetch
     detail page, run extract, update row.
   - Idempotent: skip rows already enriched at the current hash.
5. Update `runs` log per source category (`enrich`).

## Definition of done

- After `uv run enrich`, every newly-scraped row has its qualitative
  columns populated (or explicitly NULL with reason logged).
- At least one cross-platform dup case is correctly flagged when ZAP +
  QA data exists (validated manually after M4, but dedup code can ship
  before).
- Unit tests cover normalization edge cases (acentos, prefixos, ruas com
  número escondido).

## Open questions

- Does `extract.py` need a per-criterion confidence score even without
  LLM? (Default: no; tri-state is enough for v1.)

## Decision log

_Empty._
