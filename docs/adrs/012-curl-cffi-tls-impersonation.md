# ADR-012: ZAP API access via `curl_cffi` Chrome TLS impersonation

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 002, 005, 011

## Context

ADR-011 routed ZAP listings through the internal `glue-api` JSON
endpoint, called from inside a Playwright-driven Chrome via
`page.goto`. In live testing the operator's IP/network triggered a
hard Cloudflare block on the ZAP host — no challenge UI, just an
immediate 403 wall on every request from the headed browser, before
any API traffic even started.

A hard CF block isn't a bug we can fix in our code: it's CF's edge
deciding the requesting client looks like a bot regardless of cookies,
because the block kicks in at the **TLS handshake** layer (JA3 / JA4
fingerprints, HTTP/2 frame ordering, ALPN), well before any HTTP
header or JS runtime quirk. Playwright Chromium and even system Chrome
launched by Playwright present a TLS fingerprint that differs subtly
from a stock Chrome process. CF distinguishes them.

`curl_cffi` (Python wrapper around curl-impersonate) sends Chrome's
exact wire fingerprint — same JA3, same TLS extensions, same HTTP/2
SETTINGS frames — at the network layer. CF can't tell it apart from a
real Chrome request.

## Decision

The ZAP scraper's listings path uses `curl_cffi` directly to call
`glue-api.zapimoveis.com.br`, with `impersonate="chrome124"`.

The Playwright session is **removed** from the ZAP listings path. It
remains in the project (`scrapers/playwright_session.py`) for future
detail-page scraping (Plan 0002) where rendered JS may genuinely be
required, but the M1 search-results path no longer needs it.

Mechanics:

1. Build the glue-api URL from the location table
   (`scrapers/zap/locations.py`).
2. `curl_cffi.requests.get(url, headers={"X-Domain": …},
   impersonate="chrome124", timeout=30)`.
3. Parse the JSON response. No CORS, no challenge UI, no warmup.

Cookies: not strictly required for glue-api when the TLS fingerprint
matches Chrome's. If CF later tightens and demands `cf_clearance`, the
fallback is to extract it from the operator's real Chrome via a
cookies-file dump and pass it to `curl_cffi.requests.get(cookies=…)`.
Defer until needed.

## Consequences

- **Positive:** simpler call path (no browser, no warmup, no per-page
  CF challenge surface); resilient to operator's IP being on CF's
  bot-IP lists for headed browsers; faster (no DOM render); fewer
  flaky failure modes; produces identical typed `ListingStub`s.
- **Positive:** removes a class of operator pain — no more
  `HEADED=1 uv run scrape` to seed cookies, no more `rm -rf` the
  persistent profile when it gets "burned."
- **Negative:** depends on `curl_cffi` keeping its impersonation
  fingerprints current with Chrome's stable channel. Historically the
  upstream has tracked Chrome closely. If CF updates and outpaces
  curl-impersonate, the response is to bump the `impersonate=` value
  to a newer Chrome version when curl_cffi releases it.
- **Negative:** `curl_cffi` ships native binaries (compiled curl-impersonate).
  Slower cold install, larger venv. Acceptable for a single-operator
  workstation; would matter in CI.
- **Neutral:** ADR-011's API-shape decisions (URL builder,
  `X-Domain` header, JSON parsing, location metadata) are unchanged.
  Only the transport layer was swapped.
- **Neutral:** ADR-002's persistent-context strategy still applies for
  any future scraper that genuinely needs JS rendering. ADR-002's
  "delete the profile when burned" guidance now only applies to those.
