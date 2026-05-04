"""Tests for `QaScraper.list_listings` canonicalization + cross-bairro
dedup. Network is monkey-patched: `post_json` returns canned payloads
so the test runs against the orchestration logic, not the live API.

The bug this guards against: QA's slug filter is fuzzy — a
`vila-olimpia-...` query also returns Itaim Bibi, Cidade Monções,
etc. Without canonicalization, the scraper attributed all returns to
the queried bairro, then `(source, source_id)` dedup misattributed
listings to whichever bairro was queried first. Bairros queried
later looked depleted (Plan 0004 first run: Moema got only 6 of 127).
"""

from typing import Any
from unittest.mock import patch

from aptos_sp.config.filters import Enrichment, Filters, FiltersConfig, RateLimit, Sources
from aptos_sp.scrapers.qa import scraper as qa_scraper_mod
from aptos_sp.scrapers.qa.scraper import QaScraper, normalize_bairro


def _config(*bairros: str) -> FiltersConfig:
    return FiltersConfig(
        bairros=list(bairros) or ["Pinheiros", "Itaim Bibi"],
        filters=Filters(
            quartos_min=1,
            quartos_max=3,
            vagas_min=1,
            area_min_m2=70,
            area_min_m2_flex=60,
            mobiliado=True,
            total_max=11000,
            tipo="apartamento",
        ),
        rate_limit=RateLimit(
            delay_min_s=0,
            delay_max_s=0,
            max_concurrent_origins=1,
            backoff_multiplier=2,
            backoff_max_s=60,
        ),
        sources=Sources(zap=False, quintoandar=True),
        enrichment=Enrichment(),
    )


def _hit(id_: str, neighbourhood: str, area: int = 80) -> dict[str, Any]:
    return {
        "_id": id_,
        "_source": {
            "id": id_,
            "neighbourhood": neighbourhood,
            "regionName": neighbourhood,
            "address": "Rua Test",
            "area": area,
            "bedrooms": 2,
            "bathrooms": 2,
            "parkingSpaces": 1,
            "rent": 5000,
            "totalCost": 7000,
            "iptuPlusCondominium": 2000,
        },
    }


def _payload(*hits: dict[str, Any]) -> dict[str, Any]:
    return {"hits": {"total": {"value": len(hits)}, "hits": list(hits)}}


def test_normalize_bairro_strips_accents_and_case():
    assert normalize_bairro("Vila Olímpia") == normalize_bairro("vila olimpia")
    assert normalize_bairro("Itaim Bibi") == "itaim bibi"


def test_list_listings_drops_non_target_bairros(monkeypatch):
    """`vila-olimpia` slug query returns adjacent neighborhoods too;
    only the target ones survive canonicalization."""
    config = _config("Vila Olímpia")

    # First page: mix of Vila Olímpia + adjacent. Empty page after.
    page1 = _payload(
        _hit("100", "Vila Olímpia"),
        _hit("101", "Itaim Bibi"),  # adjacent — drop
        _hit("102", "Cidade Monções"),  # adjacent — drop
        _hit("103", "Vila Olimpia"),  # accent variant — keep, canonicalize
    )
    page2 = _payload()  # empty → tail

    calls: list[dict[str, Any]] = []

    def fake_post(url, body):
        calls.append(body)
        return page1 if body["pagination"]["offset"] == 0 else page2

    monkeypatch.setattr(qa_scraper_mod, "post_json", fake_post)
    monkeypatch.setattr(qa_scraper_mod.time, "sleep", lambda *_: None)
    # Force PAGE_SIZE=4 so the `len < PAGE_SIZE` tail rule fires after page 1.
    monkeypatch.setattr(qa_scraper_mod, "PAGE_SIZE", 4)

    stubs = QaScraper().list_listings(config)
    assert {s.source_id for s in stubs} == {"100", "103"}
    assert all(s.bairro == "Vila Olímpia" for s in stubs)


def test_list_listings_dedupes_across_bairros(monkeypatch):
    """A listing returned by both Pinheiros and Itaim Bibi slug queries
    survives once, attributed to its canonical neighbourhood."""
    config = _config("Pinheiros", "Itaim Bibi")

    # Pinheiros query returns listing 200 (Pinheiros) + 201 (Itaim Bibi
    # — leaked from the fuzzy radius).
    pinheiros_page = _payload(
        _hit("200", "Pinheiros"),
        _hit("201", "Itaim Bibi"),
    )
    # Itaim Bibi query returns listing 201 again + a new one.
    itaim_page = _payload(
        _hit("201", "Itaim Bibi"),
        _hit("202", "Itaim Bibi"),
    )
    empty = _payload()

    def fake_post(url, body):
        slug = body["slug"]
        offset = body["pagination"]["offset"]
        if offset > 0:
            return empty
        return pinheiros_page if "pinheiros" in slug else itaim_page

    monkeypatch.setattr(qa_scraper_mod, "post_json", fake_post)
    monkeypatch.setattr(qa_scraper_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(qa_scraper_mod, "PAGE_SIZE", 2)

    stubs = QaScraper().list_listings(config)
    by_id = {s.source_id: s for s in stubs}
    assert set(by_id) == {"200", "201", "202"}
    assert by_id["200"].bairro == "Pinheiros"
    # 201 was first seen via the Pinheiros query — but it canonicalizes
    # to Itaim Bibi based on its API `neighbourhood` value.
    assert by_id["201"].bairro == "Itaim Bibi"
    assert by_id["202"].bairro == "Itaim Bibi"


def test_list_listings_paginates_until_partial_page(monkeypatch):
    """Stops on the natural tail (returned < PAGE_SIZE), not on the
    over-counting `total` field."""
    config = _config("Pinheiros")

    page1 = _payload(*(_hit(str(i), "Pinheiros") for i in range(50)))
    page2 = _payload(*(_hit(str(50 + i), "Pinheiros") for i in range(32)))  # partial → stop
    empty = _payload()

    def fake_post(url, body):
        offset = body["pagination"]["offset"]
        if offset == 0:
            return page1
        if offset == 50:
            return page2
        return empty

    with (
        patch.object(qa_scraper_mod, "post_json", fake_post),
        patch.object(qa_scraper_mod.time, "sleep", lambda *_: None),
    ):
        stubs = QaScraper().list_listings(config)

    assert len(stubs) == 82
