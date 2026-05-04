"""ZAP Imóveis scraper.

Walks the `glue-api` listings endpoint for each neighborhood, returning
every listing found. Filtering against `filters.yaml` happens
downstream — the scraper's job is to surface what ZAP returns.

Network strategy (ADR-012): direct HTTPS via `curl_cffi` with Chrome
TLS-fingerprint impersonation. No browser. Cloudflare's edge inspects
the TLS handshake, so we send Chrome's exact wire fingerprint — which
is what passes their checks even when the operator's IP can't load the
HTML pages in a real browser.
"""

import random
import time

from aptos_sp.config.filters import FiltersConfig
from aptos_sp.scrapers.base import ListingDetail, ListingStub
from aptos_sp.scrapers.zap.api import (
    API_HEADERS,
    PAGE_SIZE,
    build_url,
    parse_response,
    total_count,
)
from aptos_sp.scrapers.zap.http import FetchBlocked, fetch_json
from aptos_sp.scrapers.zap.locations import location_for

# Defensive ceiling on pages per bairro.
MAX_PAGES = 200

# ZAP's API hard-caps pagination at `from < 1500` (50 pages × 30/page).
# Beyond that it returns `404 "Page is above acceptable limit"`. To
# scrape past 1500 hits per bairro we'd need to sub-divide queries by
# bedroom count or price range — deferred. Per ADR-007's
# false-negatives-over-false-positives stance, capping at 1500 means
# we miss the long tail; the operator's strict downstream filter
# (mobiliado, ≥70m², ≤R$11k) cuts most of those anyway.
ZAP_API_OFFSET_LIMIT = 1500

INTER_BAIRRO_DELAY_RANGE = (5.0, 12.0)
INTER_PAGE_DELAY_RANGE = (1.5, 4.0)


class ZapScraper:
    source = "zap"

    def list_listings(self, config: FiltersConfig) -> list[ListingStub]:
        results: list[ListingStub] = []
        for i, bairro in enumerate(config.bairros):
            if i > 0:
                time.sleep(random.uniform(*INTER_BAIRRO_DELAY_RANGE))
            results.extend(self._fetch_bairro(bairro, config))
        return results

    def _fetch_bairro(self, bairro: str, config: FiltersConfig) -> list[ListingStub]:
        location = location_for(bairro)
        out: list[ListingStub] = []
        last_page: int | None = None
        api_offset_cap = ZAP_API_OFFSET_LIMIT // PAGE_SIZE  # 50

        for page in range(1, min(MAX_PAGES, api_offset_cap) + 1):
            if page > 1:
                time.sleep(random.uniform(*INTER_PAGE_DELAY_RANGE))
            url = build_url(location, config.filters, page=page)
            try:
                payload = fetch_json(url, headers=API_HEADERS)
            except FetchBlocked as e:
                # Defensive: if ZAP changes the offset cap, surface it
                # via the run summary and stop paginating this bairro.
                if "above acceptable limit" in str(e):
                    break
                raise

            if last_page is None:
                count = total_count(payload)
                if count is not None:
                    pages_for_count = max(1, -(-count // PAGE_SIZE))
                    last_page = min(pages_for_count, api_offset_cap)
                    capped = " (API offset cap)" if pages_for_count > api_offset_cap else ""
                    print(
                        f"[zap/{bairro}] totalCount={count}, "
                        f"will paginate to page {last_page}{capped}",
                        flush=True,
                    )

            found = parse_response(payload, bairro=bairro)
            if not found:
                break
            out.extend(found)

            if last_page is not None and page >= last_page:
                break
            if len(found) < PAGE_SIZE:
                # Defensive: fewer than PAGE_SIZE items signals the
                # tail even if totalCount was off.
                break
        return out

    def fetch_detail(self, url: str) -> ListingDetail:
        # Detail-page enrichment is Plan 0002 (M2). M1 only needs
        # search-results data.
        raise NotImplementedError("Detail-page scraping arrives in Plan 0002.")
