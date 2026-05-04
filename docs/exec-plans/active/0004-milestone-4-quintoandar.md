# Plan 0004 — Milestone 4: QuintoAndar scraper

**Status:** Not started
**Depends on:** Plan 0001 (Scraper interface), Plan 0002 (dedup)

## Goal

Add QuintoAndar as a secondary source per ADR-005, reusing the
`Scraper` interface where possible and tolerating failure gracefully.

## Out of scope

- Anti-detection arms race (per ADR-005 §3): no fingerprint rotation,
  no proxy pool, no captcha solver.
- Loft and ImovelWeb (future).

## Steps

1. Validate first: does ZAP coverage of the 6 neighborhoods make QA
   worth the effort? If ZAP covers ≥ 90%, consider abandoning. (Decide
   *before* writing code.)
2. Implement `aptos_sp/scrapers/qa/`:
   - Reuse `Scraper` base class.
   - Internal slug mapping (canonical neighborhood → QA slug like
     `pinheiros-sao-paulo-sp-brasil`).
   - Page-of-detail strategy: prefer direct
     `quintoandar.com.br/imovel/<id>/...` URLs over scraping the
     listing flow.
3. Implement auto-disable (ADR-005 §2):
   - Query last 3 `runs` rows where `source = 'quintoandar'`.
   - If all 3 have `status = 'failed'`, write a `status = 'disabled'`
     row at start of next run and exit early.
   - Operator clears by editing `runs` (or a CLI flag like
     `--reset-source-disable`).
4. Refactor `Scraper` interface only if QA exposes a structural mismatch
   that hacking around would be worse than refactoring (ADR-005 §1).

## Definition of done

- `uv run scrape` runs both ZAP and QA sources by default
  (`sources.quintoandar: true`).
- Disabling QA via `sources.quintoandar: false` skips it cleanly.
- After 3 forced failures, the next run is auto-disabled with a
  visible warning.
- At least 5 cross-platform duplicates are detected by Plan 0002's
  dedup pass.

## Open questions

- ImovelWeb agrega QA parcialmente (per ADR-005 Consequences). After
  M4, measure overlap between QA and ImovelWeb to decide if M4 was
  worth it. If overlap is high, that's an argument for skipping
  ImovelWeb entirely.

## Decision log

_Empty._
