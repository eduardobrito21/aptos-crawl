# ADR-002: Playwright sync API with persistent context

**Status:** Accepted
**Date:** 2026-05-04
**Related:** 005

## Context

We need to visit hundreds of pages (listing pages + detail pages) on
sites with anti-bot defenses. Options:

- **httpx/requests** — fast but fails against Cloudflare and against
  pages that depend on JS.
- **Playwright async** — performant, but adds complexity (asyncio,
  pools, nested context managers).
- **Playwright sync** — linear code, easy to debug, performance is
  enough for 100–500 rate-limited requests.

## Decision

Use **Playwright's sync API** (Python:
`from playwright.sync_api import sync_playwright`) with **persistent
context** (browser profile persisted at
`~/.cache/aptos-sp/playwright-profile/`).

Configuration:

- Chromium with a realistic user-agent (current stable Chrome on
  macOS)
- Viewport 1440x900
- `locale='pt-BR'`, `timezone_id='America/Sao_Paulo'`
- Persistent storage between runs (cookies, localStorage) → fewer
  Cloudflare challenges
- Headless by default; `HEADED=1` env var for debugging
- Randomized 2–5s delays between navigations on the same origin
- Exponential backoff on 403/429

## Consequences

- **Positive:** simple code, fast to iterate; persistent context
  improves anti-bot success rate; debugging in headed mode is
  trivial.
- **Negative:** sequential → ~1 req/3s, so 100 listings = ~5 minutes.
  Fine for daily use; if it becomes a bottleneck, parallelize with
  2–3 browsers and rate-share.
- **Neutral:** persistent context holds state. If it gets "burned"
  (banned / challenged on every navigation), the operator deletes the
  profile:

  ```sh
  rm -rf ~/.cache/aptos-sp/playwright-profile/
  ```

  Playwright will recreate the profile on the next run.
