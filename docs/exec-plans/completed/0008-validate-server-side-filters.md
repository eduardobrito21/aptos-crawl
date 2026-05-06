# Plan 0008 — Validate server-side filters via local-filter parity

**Status:** Complete (2026-05-05)

## Goal

Prove (or disprove) that ZAP's and QA's server-side filter parameters
produce the same result set as applying our own filter logic to an
unfiltered fetch. Operator suspicion: some of the filter mappings
silently misbehave, and the safest long-term posture is to fetch with
the *minimum* server-side filter (just bairro + apartment) and apply
`filters.yaml` locally where we can audit it.

This plan is a **validation harness + a migration path**. After the
audit lands we either keep the server-side filters (if they're
faithful), or rip them out (if they're not) — in both cases with
evidence.

## Out of scope

- Detail-page enrichment (`cli/details.py` keeps working as-is).
- Cross-platform dedup logic (Plan 0002, already shipped).
- A new ADR for the local-filter layer — defer until the audit
  result tells us what shape that ADR should take.
- Workarounds for offset caps in unfiltered fetches that need
  query-slicing — note them as an open question; address only if
  validation actually requires running unfiltered at scale.

## Steps

1. **Unify the filter logic in one place.** Create
   `aptos_sp/pipeline/local_filter.py::passes_filters(stub, filters)`
   covering `quartos_min/max`, `vagas_min`, `area_min_m2`
   (with `area_min_m2_flex` honored by description),
   `total_max`, and `mobiliado` (treat `mobiliado=true` as
   "any furnished signal" — see step 3 for the exact predicate).
   `cli/enrich._is_eligible` collapses into this.
2. **Add a `raw=True` mode to both scrapers.** Behind the same
   `Scraper` interface:
   - `scrapers/zap/api.py`: when `raw=True`, the URL keeps
     `business=RENTAL` + apartment unit-types + bairro location, drops
     `bedrooms`, `parkingSpaces`, `usableAreasMin`,
     `rentalTotalPriceMax`, `rentTotalPrice`, `amenities=FURNISHED`.
   - `scrapers/qa/api.py`: when `raw=True`, the body's
     `filters.houseSpecs` keeps only `houseTypes=["APARTMENT"]` and
     `filters.priceRange = []`. `bedrooms` / `parkingSpace` /
     `area` / `isFurnished` all become unconstrained.
3. **Resolve the `mobiliado` semantic mismatch.** ZAP exposes
   `amenities=FURNISHED`; QA exposes `isFurnished=true` *and* a
   `furnitures` checklist. The local predicate must match both:
   accept a listing as mobiliado iff
   `"FURNISHED" in stub.amenities` OR
   `stub.amenities ∩ {ARMARIOS_NA_COZINHA, CAMA_DE_CASAL,
   CAMA_DE_SOLTEIRO, MESAS_E_CADEIRAS_DE_JANTAR, SOFA, ...} ≠ ∅`.
   Picking the exact set is part of the validation work.
4. **Add `aptos_sp/cli/validate_filters.py`.** Per source: run two
   passes — server-filtered (current behavior) and raw + local-filter
   — and emit a diff:
   - `A` = set of `(source, source_id)` from raw + local-filter
   - `B` = set of `(source, source_id)` from server-filtered
   - Print `|A|`, `|B|`, `|A ∩ B|`, `|A \ B|`, `|B \ A|`.
   - For up to 5 rows in each asymmetric difference, dump
     `area_m2 / quartos / vagas / total / amenities / descricao[:200]`
     so the operator can eyeball whether the server or the local
     predicate is wrong.
   - Restrict to ONE bairro by default (`--bairro Pinheiros`) to keep
     wall-clock + offset-cap risk low.
4b. **Combinatorial-axis mode.** A single all-on / all-off run
    conflates dimensions: when ZAP's `B \ A` is large, we can't tell
    whether `mobiliado`, `area`, `bedrooms`, or `parking` is the
    misbehaving filter. Add a per-axis mode that holds the
    *definitional* filters constant (apartment + RENTAL + bairro)
    plus a generous baseline for everything else, and toggles only
    one or two suspect axes per comparison. Suspect axes:
    `bedrooms`, `parking`, `area`, `mobiliado`, `total`.
    - The CLI does **one raw fetch per source per run** and reuses
      the result for every axis combination — saves N–1 raw fetches.
    - For each axis combination, build a "tested filter" that has
      the operator's value for those axes and a permissive baseline
      everywhere else. Run `A = raw + local(tested_filter)` against
      `B = server(tested_filter)` and print the diff per combo.
    - `--axes a,b` runs one combination. `--combinatorial` runs
      every single axis plus every 2-axis pair. Both default to one
      bairro, since combinatorial mode multiplies the server-fetch
      count.
    - This is the recurring tool the operator runs whenever
      `filters.yaml` changes or before believing the eligibility
      counts.
5. **Document the audit result in this plan's decision log.** For
   each source × each filter dimension, record: faithful, off-by-one,
   wrong unit, or silently rejecting valid rows.
6. **Decide migration based on result.** If a filter is faithful —
   keep server-side use. If it's not — drop the server param, rely
   on local. Either way the local filter stays as the canonical
   eligibility predicate.

## Definition of done

- `uv run validate-filters --source zap --bairro Pinheiros` runs
  end-to-end and prints a non-empty A vs B comparison.
- Same for `--source quintoandar`.
- Every server-side filter currently in
  `scrapers/{zap,qa}/api.py::build_url`/`build_body` is classified in
  the decision log as **faithful** or **suspect**; suspect ones are
  removed in a follow-up commit (or kept with a comment explaining why
  the discrepancy is acceptable).
- `pipeline/local_filter.py::passes_filters` is the single source of
  truth used by `cli/enrich._is_eligible` and the validation harness;
  no duplicate predicate logic.
- 0 new typecheck or lint errors; tests for `passes_filters` cover
  the area-flex conditional, `mobiliado` via amenities, and the
  edge cases (`vagas_min=0`, missing fields).

## Open questions

- **Offset caps under unfiltered fetches.** ZAP's `glue-api` rejects
  `from ≥ 1500` (50 pages × 30); QA's apigw rejects `offset > 1000`
  per slug. Unfiltered Pinheiros has ~1518 unique target hits on QA
  alone — close to the cap. If validation reveals we need to run
  unfiltered at scale, we'll need a slicing strategy (price band,
  bedroom count) to avoid the cap. For the audit itself, restricting
  to one bairro keeps us under both caps.
- **Sort drift between runs.** ZAP and QA both default to
  `RELEVANCE` / similar fuzzy ordering, and may surface different
  results for back-to-back queries. The validation harness should
  fetch `A` and `B` close together and treat tiny set differences
  (≤ 1% of the union) as noise. Anything above that is a real
  discrepancy.
- **Should we keep `business=RENTAL` and `houseTypes=APARTMENT` as
  server filters even in "raw" mode?** Yes — they're definitional
  (we don't want sales or houses), and dropping them inflates the
  raw set with categorically wrong listings. The audit is for the
  filters that mirror `filters.yaml`, not for these.

## Decision log

- **2026-05-05 — Combinatorial findings table** (Pinheiros, after
  three audit rounds and two parser/scraper fixes). Verified by
  targeted probes that walk many pages with each filter on:

  | source | filter | classification |
  |---|---|---|
  | zap | `bedrooms=1,2,3` | strict |
  | zap | `parkingSpaces=1,2,3,4` | strict (probed 900 listings, 0 leakage) |
  | zap | `usableAreasMin=70` | strict (probed deep pages, 0 leakage) |
  | zap | `rentalTotalPriceMax + rentTotalPrice` | strict |
  | zap | `amenities=FURNISHED` | **loose** — 17.8% leakage at depth (107/600 returned listings have no `FURNISHED` in their structured amenities array) |
  | qa  | `bedrooms.range` | substantially faithful (~94% agreement) |
  | qa  | `parkingSpace.range` | substantially faithful (~94%) |
  | qa  | `area.range.min` | strict to *flex* floor (60); local applies strict 70 — documented design |
  | qa  | `isFurnished` | substantially faithful (~92%) |
  | qa  | `priceRange (TOTAL_COST)` | substantially faithful (~93%) |

- **2026-05-05 — Action: drop ZAP's server-side
  `amenities=FURNISHED`.** It's the only confirmed-loose filter on
  either source. We rely on `pipeline.local_filter.is_mobiliado` (which
  trusts ZAP's `is_furnished` parser flag) — and that flag IS faithful
  to the API's structured amenities array, just not to whatever fuzzy
  signal ZAP's filter ALSO reads. Build URL no longer sends
  `amenities=FURNISHED` regardless of `filters.mobiliado`.

- **2026-05-05 — Drop QA furniture-amenity fallback in
  `is_mobiliado`.** First audit run showed 53 "A \\ B" pairs on QA:
  listings the local predicate accepted that the server (correctly)
  rejected. Inspection: every one had `is_furnished=False` per QA's
  API, but the predicate was treating QA furniture-taxonomy codes
  (`ARMARIOS_NA_COZINHA`, `CAMA_DE_CASAL`, `SOFA`, …) as evidence of
  mobiliado. Built-in wardrobes appear in *unfurnished* listings too,
  so the fallback was noise. New predicate: `stub.is_furnished is
  True` only — trust the source's explicit flag and reject `None`
  per ADR-007's false-negative-preferred stance. After tightening,
  QA `A \\ B = 0` (perfect agreement on the mobiliado axis).
- **2026-05-05 — `validate-filters` flags raw-fetch cap risk.**
  ZAP's `glue-api` rejects `from ≥ 1500`; QA's apigw rejects
  `offset > 1000`. When the unfiltered raw fetch nears that cap,
  `B \\ A` is contaminated with listings A could never enumerate,
  not real filter discrepancies. The CLI now prints a `⚠` when raw
  returns ≥ 90% of the per-source cap so the operator reads the
  diff with that caveat in mind.
- **2026-05-05 — Pinheiros audit findings.** Single-bairro run
  (`uv run validate-filters --bairro Pinheiros`) on a fresh DB:

  | source | raw  | passed_local | server_returned | A ∩ B | A \\ B | B \\ A |
  |--------|------|--------------|-----------------|-------|--------|--------|
  | zap    | 599  | 34 → 31 dedup | 215             | 28    | 3      | 187    |
  | qa     | 483  | 23           | 41              | 23    | **0**  | 18     |

  **QA mobiliado filter is faithful.** `A \\ B = 0` after the
  predicate tightening — every listing the local filter accepted
  was also accepted by the server.

  **QA area filter uses the flex floor (60) where local wants 70.**
  `B \\ A` includes several `area = 60-68m²` listings that the
  server returned but local rejected. Root cause known: `build_body`
  passes `filters.area_min_m2_flex` to the server (intentional, so
  1q+escritório listings aren't pre-filtered out) — local filter
  re-applies the strict `area_min_m2` for everyone else. Documented
  as expected behavior; not a bug.

  **ZAP `amenities=FURNISHED` server filter is loose.** The audit
  found 187 `B \\ A` rows on ZAP. Most are raw-fetch misses (cap),
  but a non-trivial subset are listings whose structured amenities
  array does NOT contain `FURNISHED` yet ZAP's server filter
  returned them anyway (descricao mentions "MOBILIADO" — server
  appears to fall back to text). Conclusion: ZAP's `FURNISHED` flag
  in `includeFields` is not the same signal the server filter uses.
  Either we (a) drop the server-side `amenities=FURNISHED` and
  filter locally on prose + `is_furnished` flag, or (b) accept
  that ZAP's `mobiliado` filter is fuzzy and trust it.

  **ZAP raw fetch is incomplete** — `totalCount=4329`, we walked
  599. Either backend pagination terminates early on relevance-tail
  pages or there's a hidden cap below 1500. Need to investigate
  before doing a full unfiltered audit at scale.

- **2026-05-05 — Parser fixes uncovered by the audit.** Two ZAP
  parser bugs surfaced when comparing local-filter rejections
  against server-accepted listings:
  1. `pricingInfos[0]` was taken blindly. Dual-listed properties
     (RENTAL + SALE) caused us to read the SALE price as the rent.
     Surfaced as `total = R$1.3M/mo` rejections in B \\ A. Fixed:
     `_pick_rental_pricing(...)` picks the entry with
     `businessType == "RENTAL"` first.
  2. `iptu_monthly = yearly_iptu / 12` ignored
     `iptuPeriod`. When the API encodes a monthly IPTU as
     `yearlyIptu = N` with `iptuPeriod = "MONTHLY"`, dividing by 12
     under-reported total cost by ~12×. Fixed: `_iptu_monthly_from`
     reads `iptu` directly when period is `MONTHLY`.

- **2026-05-05 — ZAP scraper early-exit fix.** The "tail = first
  page returning <PAGE_SIZE" rule killed pagination at ~360
  listings when 1400+ were available — ZAP serves transient short
  pages mid-stream. Replaced with a 3-consecutive-short-pages stop;
  empty page is still a hard stop.

- **2026-05-05 — ZAP raw-mode pagination unlock.** ZAP's
  `glue-api` caps the unfiltered result set at ~380 by relevance
  ranking; adding ANY parking-spaces filter (even the permissive
  `0,1,2,3,4`) unlocks deeper pagination (~1500). The audit's `raw`
  mode now sends `parkingSpaces=0,1,2,3,4` so it can enumerate the
  real universe (a no-op on result selection — every listing has
  parkingSpaces in 0..4).

- **2026-05-05 — Audit-method limitation worth recording.** ZAP's
  pagination depth varies per server filter, so per-axis
  combinatorial counts can't be directly compared across combos.
  The all-on combo is the only one bounded the same way as the raw
  fetch and is the most reliable signal. Targeted single-filter
  probes (walking many pages with one filter on) confirm what the
  audit suggests. Both passes are documented in this plan; the
  one-axis-at-a-time numbers should be read as "directionally
  informative" rather than literal precision/recall.

- **2026-05-05 — Recurring-audit posture.** The harness is the
  intended check-in tool, not a one-shot. Re-run
  `uv run validate-filters --bairro Pinheiros --combinatorial`
  before believing eligibility counts after any of:
  - `filters.yaml` change
  - any `scrapers/*/api.py::build_url` / `build_body` change
  - any change to `pipeline.local_filter.passes_filters`
  - quarterly, to catch silent server-side filter drift

- **2026-05-05 — Round-by-round all-on combo evolution
  (Pinheiros).** Documents the audit's effectiveness as a
  feedback loop:

  | round | A | B | A∩B | A\\B | B\\A | what changed |
  |---|---|---|---|---|---|---|
  | 1 | 28  | 215 | 28 | —  | 187 | initial harness |
  | 2 | 22  | 213 | 20 | 2  | 193 | ZAP parser fixes (RENTAL-pricing pick + iptuPeriod) |
  | 3 | 74  | 215 | 66 | 8  | 149 | scraper short-page fix + ZAP raw-mode pagination unlock |
  | 4 | 63  | 821 | 59 | 4  | 762 | dropped server `amenities=FURNISHED` (loose) |

  Round 4's B exploded because we no longer pre-filter mobiliado
  server-side. The 762 B\\A entries are all `mobiliado: no furnished
  signal` — correct local rejections of unfurnished listings. A∩B=59
  means local catches ~94% of true positives the audit can confirm
  ZAP exposes; the residual A\\B=4 are listings ZAP's server filter
  combo rejects despite local accepting them — worth a follow-up
  spot-check but small enough to not block.

- **2026-05-05 — `area` axis on ZAP shows large `B \\ A` even at
  round 4 — instrumentation, not a filter bug.** Each ZAP server
  filter that's "filter present" (`usableAreasMin=70`,
  `bedrooms=...`, etc.) unlocks deeper pagination than raw mode can
  reach. So `B = server-with-area-filter` enumerates a strictly
  larger pool than `A = raw + local`, and `B \\ A` mostly reflects
  that gap. Per-axis `B \\ A` counts on ZAP are not literal — only
  the all-on combo (whose B is bounded the same way as raw) gives a
  clean comparison.

- **2026-05-05 — Round-4 ZAP residual `A \\ B = 4` investigated;
  ranking jitter, not a bug.** Pulled the four listing IDs flagged
  as "local accepts, server rejects" and fetched their detail
  pages directly. All four are real, currently-available 2q
  Pinheiros rentals with `FURNISHED` in their detail-page
  itemProps and totals at or just under R$11k. Re-querying the
  all-on server filter minutes later returned 2 of the 3 inspected
  IDs (the third stayed deep in ranking). Conclusion: ZAP's
  all-on server filter is faithful within the result-window it
  surfaces, but its relevance ranking churns between requests, and
  listings near the ranking tail flicker in and out of the audit's
  B set. No code change needed; the audit's "tail-rank flicker"
  noise floor is ~1-2% of B for the all-on combo on Pinheiros.
