# ADR-005: Treat QuintoAndar as a secondary, risky source

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 001, 002

## Context

QuintoAndar has excellent coverage in the target neighborhoods, but:

- Aggressive Cloudflare Bot Management
- Listings via JS with infinite scroll (not server-rendered)
- Internal GraphQL API (`apigw.prod.quintoandar.com.br`) with
  rotating auth headers
- Direct fetch returns 403

History shows that QA tends to break scrapers from time to time.
Building and maintaining a robust scraper is expensive.

## Decision

QA becomes a secondary source (phase 2 of the roadmap), with explicit
limits:

1. **Maximum reuse of the ZAP scraper.** Same interface, only
   different implementation. If the common interface doesn't fit (e.g.
   pagination differs significantly), refactor the interface instead
   of hacking around it.
2. **Failure tolerance.** If the QA scraper fails 3 runs in a row, it
   auto-disables in the `runs` log and continues with ZAP only.
   Eduardo decides whether it's worth debugging.
3. **No investment in sophisticated anti-detection** (fingerprint
   rotation, residential proxies, captcha solvers) in v1. Persistent
   context + delays + realistic UA (see
   [ADR-002](002-playwright-sync.md)) is what we have. If that's not
   enough, drop QA.
4. **Detail page via direct URL** (not via "search → click" flow),
   leveraging the fact that URLs like
   `quintoandar.com.br/imovel/<id>/...` look more stable than
   listings.

## Consequences

- **Positive:** avoids a black hole of time spent on anti-bot; focus
  on what delivers value.
- **Negative:** we may miss QA-exclusive listings. Mitigation:
  ImovelWeb partially aggregates QA, so the real loss is smaller.
- **Neutral:** if QA later becomes a truly important source, open a
  new ADR and re-evaluate the investment (browser-use, Bright Data,
  etc.).
