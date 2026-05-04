# ADR-001: Prioritize ZAP Imóveis as the primary source

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 005

## Context

There are 4+ relevant platforms (QuintoAndar, ZAP/VivaReal, Loft,
ImovelWeb). Each has different anti-bot defenses and overlapping but
not identical coverage. We don't have time or reason to build
scrapers for all of them at once.

Initial recon showed:

- **ZAP** returns listings with structured data (neighborhood, street,
  m², bedrooms, bathrooms, parking, rent, condo fee, IPTU) accessible
  via DOM with Playwright. Predictable URL pattern:
  `/aluguel/apartamentos/sp+sao-paulo+<zone>+<neighborhood>/<filters>/`.
- **QuintoAndar** has Cloudflare + fingerprinting. Listings via
  JS/infinite scroll (not server-rendered). Internal GraphQL API with
  rotating auth headers. Direct fetch returns 403. Fetch via
  Playwright is probably possible but needs more care — see
  [ADR-005](005-quintoandar-risk.md).
- **Loft** and **ImovelWeb** have smaller coverage and partly
  aggregate listings from the others (especially ImovelWeb aggregates
  QuintoAndar).

## Decision

Build the **ZAP scraper first**, validate the pipeline end-to-end with
it, then add QuintoAndar as the second source. Loft and ImovelWeb come
later (or never, if ZAP + QA already cover enough).

Reasons:

1. ZAP has the best effort/return ratio for this use case (high
   coverage, moderate anti-bot).
2. Validating the architecture end-to-end with one source before
   generalizing avoids over-engineering — the scraper abstraction is
   only worth it once we have 2+ real implementations.
3. ImovelWeb partially aggregates QuintoAndar, so adding QuintoAndar
   gives more marginal value than ImovelWeb.

## Consequences

- **Positive:** fast pipeline validation; less code to maintain;
  focus.
- **Negative:** if ZAP introduces aggressive anti-bot mid-project, we
  lose our primary source while QA isn't ready yet. Mitigation: keep
  QA as explicit priority #2 in the roadmap.
- **Neutral:** module structure (`scrapers/zap/`, `scrapers/qa/`)
  anticipates multi-source from day one but with a minimal interface
  — refactor when the second scraper actually demands it.
