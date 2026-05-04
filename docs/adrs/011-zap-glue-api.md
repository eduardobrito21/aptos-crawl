# ADR-011: ZAP scraper uses the `glue-api` JSON endpoint, not HTML

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 002, 005

## Context

The original M1 plan (Plan 0001) had the ZAP scraper visit search-results
HTML pages and pull listings from the embedded `__NEXT_DATA__` script tag.

In live testing, this hit a wall at Cloudflare. With a fresh persistent
context the first neighborhood (Pinheiros) cleared the JS challenge and
returned data; the very next URL (Itaim Bibi) was challenged again,
hard-403'd through every backoff, even with all of:

- system Chrome via `channel="chrome"` (closer fingerprint than
  bundled Chromium)
- `--disable-blink-features=AutomationControlled` + an init script
  patching `navigator.webdriver`, plugins, languages
- 15–30 s randomized gaps between neighborhoods
- a warm persistent profile that had just cleared CF on the previous
  page

The frontend itself doesn't render listings from the HTML — it makes an
authenticated XHR to `https://glue-api.zapimoveis.com.br/v4/listings`
with a long query string (city/zone/neighborhood, page, an
`includeFields` projection of which response fields to return) and gets
JSON back. That endpoint is the real source.

## Decision

The ZAP scraper calls `glue-api.zapimoveis.com.br/v4/listings` directly
instead of parsing search-results HTML.

Mechanics:

1. Open a Playwright session with the persistent profile (unchanged
   from ADR-002).
2. Navigate to `https://www.zapimoveis.com.br/` once. Operator solves
   any interactive Cloudflare challenge in headed mode; the persistent
   context then carries the proof cookies.
3. For each bairro, build a glue-api URL with the location metadata
   (zone, `addressLocationId`, lat/lng) hard-coded in
   `scrapers/zap/locations.py`.
4. Issue the request via `page.evaluate(async ({url, headers}) => fetch(url, {headers, credentials: 'include'}))`
   so the call originates from `www.zapimoveis.com.br` with the page's
   cookies, TLS fingerprint, and same-origin context — exactly as the
   real frontend does it.

Headers we send: `Accept: application/json`, `X-Domain:
www.zapimoveis.com.br` (without `X-Domain` the backend returns
VivaReal data; same backend, two brands), `Origin` and `Referer`
pointing at the public site.

The HTML parser (`scrapers/zap/parse.py`) and the slug map
(`scrapers/zap/slugs.py`) are removed. `locations.py` (richer metadata)
replaces the slug map.

## Consequences

- **Positive:** typed JSON instead of regex'd `__NEXT_DATA__`; one
  Cloudflare clear suffices for the whole run; supports server-side
  filtering (`amenities=FURNISHED` maps directly to
  `filters.mobiliado`); pagination via `page`/`size`/`from` is explicit.
- **Negative:** undocumented internal API. ZAP can change the query
  shape, the `includeFields` syntax, or the `addressLocationId` format
  unilaterally. When (not if) they do, `scrapers/zap/api.py` and
  `scrapers/zap/locations.py` are the two files to edit. ADR-005's
  auto-disable mechanism gives us a safety net here.
- **Negative:** per-bairro metadata (`location_id`, lat/lng, zone) has
  to be captured from the live site once per neighborhood — manual
  bookkeeping if Eduardo expands the search area later. Mitigation:
  `UnknownNeighborhood` raises a clear, actionable error pointing at
  the table.
- **Neutral:** still uses Playwright + persistent context (ADR-002
  unchanged). The browser is now used as a credentialed HTTP client,
  not as an HTML renderer. If ZAP ever drops Cloudflare or moves to a
  bearer-token API we could swap in `httpx` directly.
