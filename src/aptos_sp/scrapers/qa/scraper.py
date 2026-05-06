"""QuintoAndar scraper (ADR-001 source #2, ADR-005 risk profile).

Calls QA's `apigw.prod.quintoandar.com.br/v2/search/list` POST endpoint
with server-side filters mapped from `filters.yaml`. ElasticSearch-style
pagination via `offset` + `total.value`. Same `curl_cffi` chrome
impersonation as ZAP — the endpoint is anonymous when the TLS handshake
matches Chrome's wire fingerprint (ADR-012).

The slug filter is fuzzy-radius: a `vila-olimpia-...` query returns
listings in Vila Olímpia *and* adjacent neighborhoods (Itaim, Cidade
Monções, …). We canonicalize each listing's bairro from the API's
`neighbourhood` field against `config.bairros`, drop non-target
listings, and dedupe by `source_id` across all bairro queries.

Per ADR-005 §3, no anti-detection arms race: polite pacing between
requests, no fingerprint rotation. Per ADR-005 §1, reuses the
`Scraper` interface unchanged.
"""

import random
import time
import unicodedata

from aptos_sp.config.filters import Filters, FiltersConfig
from aptos_sp.scrapers.base import ListingDetail, ListingStub
from aptos_sp.scrapers.qa.api import API_URL, PAGE_SIZE, build_body, parse_response
from aptos_sp.scrapers.qa.http import QaFetchError, post_json
from aptos_sp.scrapers.qa.locations import slug_for

# Defensive ceiling on pages per bairro. QA's apigw rejects
# `offset > 1000`, so 20 pages × 50/page = 1000 is the natural
# ceiling. With server-side filters we typically land well under
# (Plan 0004 saw ~150-190 per slug query); the cap matters mostly in
# `raw=True` mode (Plan 0008) where unfiltered slug queries can run
# into the four-digit range.
MAX_PAGES = 20

INTER_BAIRRO_DELAY_RANGE = (5.0, 12.0)
INTER_PAGE_DELAY_RANGE = (1.5, 4.0)


class QaScraper:
    source = "quintoandar"

    def __init__(self, *, raw: bool = False) -> None:
        # `raw=True` drops every `filters.yaml`-mirroring server-side
        # parameter from the request body, keeping only the
        # definitional constraints (apartment-only, RENT). Used by the
        # Plan 0008 audit.
        self.raw = raw

    def list_listings(self, config: FiltersConfig) -> list[ListingStub]:
        targets = list(config.bairros)
        target_norm = {normalize_bairro(t): t for t in targets}
        seen_ids: set[str] = set()
        results: list[ListingStub] = []
        for i, bairro in enumerate(targets):
            if i > 0:
                time.sleep(random.uniform(*INTER_BAIRRO_DELAY_RANGE))
            for stub in self._fetch_bairro(bairro, config.filters):
                if stub.source_id in seen_ids:
                    # Same listing already attributed via an adjacent
                    # bairro's slug query — keep the first attribution.
                    continue
                canonical = target_norm.get(normalize_bairro(stub.bairro))
                if canonical is None:
                    # API placed this listing in a non-target bairro;
                    # the slug query was fuzzy and bled into adjacent
                    # neighborhoods. Drop it.
                    continue
                stub.bairro = canonical
                seen_ids.add(stub.source_id)
                results.append(stub)
        return results

    def _fetch_bairro(self, bairro: str, filters: Filters) -> list[ListingStub]:
        slug = slug_for(bairro)
        out: list[ListingStub] = []
        last_total: int | None = None

        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                time.sleep(random.uniform(*INTER_PAGE_DELAY_RANGE))
            offset = (page - 1) * PAGE_SIZE
            body = build_body(slug, filters, offset=offset, page_size=PAGE_SIZE, raw=self.raw)
            try:
                payload = post_json(API_URL, body)
            except QaFetchError:
                # Single-request failure: re-raise so the CLI's run-level
                # try/except records `failed` per ADR-005 §2. Auto-disable
                # kicks in after 3 consecutive run failures.
                raise

            stubs, total = parse_response(payload)
            if last_total is None and total is not None:
                last_total = total
                pages_for_count = max(1, -(-total // PAGE_SIZE))
                print(
                    f"[qa/{bairro}] reported_total={total}, "
                    f"will paginate up to page {min(pages_for_count, MAX_PAGES)} "
                    "(reported_total over-counts; real tail decides stop)",
                    flush=True,
                )

            out.extend(stubs)

            # Stop on the natural tail. The reported `total` over-counts
            # (covers the slug's fuzzy-radius region, not just the
            # bairro), so we don't trust it as a stop condition.
            if not stubs or len(stubs) < PAGE_SIZE:
                break

        return out

    def fetch_detail(self, url: str) -> ListingDetail:
        # Detail-page enrichment for QA is intentionally deferred —
        # the search-list API already returns enough structured data
        # for the cross-platform dedup signal Plan 0004 needs. If we
        # later want full broker prose, we'll add a per-listing fetch
        # mirroring ZAP's `cli/details.py`.
        raise NotImplementedError("QA detail-page scraping is deferred.")


def normalize_bairro(name: str) -> str:
    """Lowercase + strip accents for case/diacritic-insensitive bairro
    matching. QA returns "Vila Olímpia" sometimes, "Vila Olimpia"
    other times; both should canonicalize the same."""
    decomposed = unicodedata.normalize("NFKD", name)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return no_accents.strip().lower()
