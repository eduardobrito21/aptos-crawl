"""QuintoAndar scraper (ADR-001 source #2, ADR-005 risk profile).

Calls QA's `apigw.prod.quintoandar.com.br/v2/search/list` POST endpoint
with server-side filters mapped from `filters.yaml`. ElasticSearch-style
pagination via `offset` + `total.value`. Same `curl_cffi` chrome
impersonation as ZAP — the endpoint is anonymous when the TLS handshake
matches Chrome's wire fingerprint (ADR-012).

Per ADR-005 §3, no anti-detection arms race: polite pacing between
requests, no fingerprint rotation. Per ADR-005 §1, reuses the
`Scraper` interface unchanged.
"""

import random
import time

from aptos_sp.config.filters import Filters, FiltersConfig
from aptos_sp.scrapers.base import ListingDetail, ListingStub
from aptos_sp.scrapers.qa.api import API_URL, PAGE_SIZE, build_body, parse_response
from aptos_sp.scrapers.qa.http import QaFetchError, post_json
from aptos_sp.scrapers.qa.locations import slug_for

# Defensive ceiling on pages per bairro. With server-side filters
# applied, no bairro returns more than ~150 listings (Plan 0004 recon),
# so 10 pages × 50 = 500 is generous.
MAX_PAGES = 10

INTER_BAIRRO_DELAY_RANGE = (5.0, 12.0)
INTER_PAGE_DELAY_RANGE = (1.5, 4.0)


class QaScraper:
    source = "quintoandar"

    def list_listings(self, config: FiltersConfig) -> list[ListingStub]:
        results: list[ListingStub] = []
        for i, bairro in enumerate(config.bairros):
            if i > 0:
                time.sleep(random.uniform(*INTER_BAIRRO_DELAY_RANGE))
            results.extend(self._fetch_bairro(bairro, config.filters))
        return results

    def _fetch_bairro(self, bairro: str, filters: Filters) -> list[ListingStub]:
        slug = slug_for(bairro)
        out: list[ListingStub] = []
        seen_ids: set[str] = set()
        last_total: int | None = None

        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(random.uniform(*INTER_PAGE_DELAY_RANGE))
            offset = (page - 1) * PAGE_SIZE
            body = build_body(slug, filters, offset=offset, page_size=PAGE_SIZE)
            try:
                payload = post_json(API_URL, body)
            except QaFetchError:
                # Single-request failure: re-raise so the CLI's run-level
                # try/except records `failed` per ADR-005 §2. Auto-disable
                # kicks in after 3 consecutive run failures.
                raise

            stubs, total = parse_response(payload, bairro=bairro)
            if last_total is None and total is not None:
                last_total = total
                pages_for_count = max(1, -(-total // PAGE_SIZE))
                print(
                    f"[qa/{bairro}] total={total}, "
                    f"will paginate to page {min(pages_for_count, MAX_PAGES)}",
                    flush=True,
                )

            new_this_page = 0
            for stub in stubs:
                if stub.source_id in seen_ids:
                    continue
                seen_ids.add(stub.source_id)
                out.append(stub)
                new_this_page += 1

            # Stop conditions: empty page, returned fewer than the page
            # size (tail of results), or we've hit the known total.
            if not stubs:
                break
            if last_total is not None and len(seen_ids) >= last_total:
                break
            if len(stubs) < PAGE_SIZE:
                break

        return out

    def fetch_detail(self, url: str) -> ListingDetail:
        # Detail-page enrichment for QA is intentionally deferred —
        # the search-list API already returns enough structured data
        # for the cross-platform dedup signal Plan 0004 needs. If we
        # later want full broker prose, we'll add a per-listing fetch
        # mirroring ZAP's `cli/details.py`.
        raise NotImplementedError("QA detail-page scraping is deferred.")
