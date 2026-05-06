"""Tests for `scrapers/qa/api.py` — request body builder + response
parser for QA's `house-listing-search` endpoint.

Fixture is a 3-hit slice of a real apigw response. When QA changes
the request or response shape, save a fresh capture and update these
expectations.
"""

import json
from pathlib import Path

from aptos_sp.config.filters import Filters
from aptos_sp.scrapers.qa.api import (
    DEFAULT_FIELDS,
    PAGE_SIZE,
    build_body,
    parse_response,
)

FIXTURES = Path(__file__).parent / "fixtures" / "qa"


def _payload() -> dict:
    return json.loads((FIXTURES / "search_pinheiros.json").read_text(encoding="utf-8"))


def _filters(**overrides) -> Filters:
    base: dict[str, object] = {
        "quartos_min": 1,
        "quartos_max": 3,
        "vagas_min": 1,
        "area_min_m2": 70,
        "area_min_m2_flex": 60,
        "mobiliado": True,
        "total_max": 11000,
        "tipo": "apartamento",
    }
    base.update(overrides)
    return Filters.model_validate(base)


# --- request body --------------------------------------------------------


def test_build_body_carries_required_keys():
    body = build_body("pinheiros-sao-paulo-sp-brasil", _filters())
    assert body["slug"] == "pinheiros-sao-paulo-sp-brasil"
    assert body["fields"] == DEFAULT_FIELDS
    assert body["sorting"] == {"criteria": "RELEVANCE", "order": "DESC"}
    assert body["context"] == {"isSSR": False}
    assert body["pagination"] == {"pageSize": PAGE_SIZE, "offset": 0}
    assert body["filters"]["businessContext"] == "RENT"
    assert body["filters"]["location"]["countryCode"] == "BR"


def test_build_body_pagination_offset():
    body = build_body("moema-sao-paulo-sp-brasil", _filters(), offset=100, page_size=25)
    assert body["pagination"] == {"pageSize": 25, "offset": 100}


def test_build_body_total_cost_filter_targets_total():
    """`total_max=11000` must hit `priceRange.range.max` with
    `costType=TOTAL_COST` so QA filters on rent + condo + IPTU,
    matching what the operator's `total_max` means."""
    body = build_body("pinheiros-sao-paulo-sp-brasil", _filters(total_max=11000))
    pr = body["filters"]["priceRange"]
    assert len(pr) == 1
    assert pr[0]["costType"] == "TOTAL_COST"
    assert pr[0]["range"]["max"] == 11000


def test_build_body_bedroom_range():
    body = build_body("p", _filters(quartos_min=1, quartos_max=3))
    bedrooms = body["filters"]["houseSpecs"]["bedrooms"]
    assert bedrooms == {"range": {"min": 1, "max": 3}}


def test_build_body_parking_min_only_set_when_positive():
    body = build_body("p", _filters(vagas_min=1))
    assert body["filters"]["houseSpecs"]["parkingSpace"] == {"range": {"min": 1}}

    body = build_body("p", _filters(vagas_min=0))
    assert body["filters"]["houseSpecs"]["parkingSpace"] == {"range": {}}


def test_build_body_uses_area_flex_floor():
    """Server-side area floor uses the *flex* value so we don't lose
    1-bedroom + escritório listings before the eligibility step gets
    a chance to apply the conditional rule."""
    body = build_body("p", _filters(area_min_m2=70, area_min_m2_flex=60))
    assert body["filters"]["houseSpecs"]["area"]["range"]["min"] == 60


def test_build_body_furnished_flag():
    body = build_body("p", _filters(mobiliado=True))
    assert body["filters"]["houseSpecs"]["isFurnished"] is True

    body = build_body("p", _filters(mobiliado=False))
    assert "isFurnished" not in body["filters"]["houseSpecs"]


def test_build_body_apartment_only():
    body = build_body("p", _filters())
    assert body["filters"]["houseSpecs"]["houseTypes"] == ["APARTMENT"]


def test_build_body_raw_mode_drops_filter_params():
    """`raw=True` keeps only the definitional constraints (apartment,
    RENT) and zeroes everything that mirrors `filters.yaml`. Plan
    0008's audit knob."""
    body = build_body("p", _filters(), raw=True)
    house_specs = body["filters"]["houseSpecs"]
    assert house_specs["houseTypes"] == ["APARTMENT"]
    assert body["filters"]["businessContext"] == "RENT"
    assert body["filters"]["priceRange"] == []
    # Constraints from filters.yaml are stripped.
    assert house_specs["area"]["range"] == {}
    assert house_specs["bedrooms"]["range"] == {}
    assert house_specs["parkingSpace"]["range"] == {}
    assert "isFurnished" not in house_specs


# --- response parsing ----------------------------------------------------


def test_parse_response_returns_three_stubs():
    stubs, total = parse_response(_payload())
    assert len(stubs) == 3
    assert total == 99
    assert {s.source for s in stubs} == {"quintoandar"}
    # Bairro now comes from the API's `neighbourhood` field; the
    # scraper canonicalizes against `config.bairros` afterward.
    assert all(s.bairro == "Pinheiros" for s in stubs)


def test_parse_response_url_points_at_canonical_detail():
    stubs, _ = parse_response(_payload())
    for stub in stubs:
        assert stub.url == f"https://www.quintoandar.com.br/imovel/{stub.source_id}/"


def test_parse_response_extracts_structured_fields():
    stubs, _ = parse_response(_payload())
    by_id = {stub.source_id: stub for stub in stubs}
    sample = by_id["893327546"]
    # Captured-fixture values; if QA changes them, refresh the fixture.
    assert sample.area_m2 == 106
    assert sample.quartos == 3
    assert sample.suites == 1
    assert sample.banheiros == 2
    assert sample.vagas == 1
    assert sample.aluguel == 7200
    assert sample.total == 10109
    assert sample.condominio == 2631
    assert sample.iptu is None  # QA bundles condo + IPTU
    assert sample.endereco == "Rua Oscar Freire, Pinheiros, São Paulo"


def test_parse_response_carries_amenities_and_description():
    stubs, _ = parse_response(_payload())
    by_id = {stub.source_id: stub for stub in stubs}
    sample = by_id["893327546"]
    assert "AR_CONDICIONADO" in sample.amenities
    assert "PERTO_DE_METRO_OU_TREM" in sample.amenities
    assert sample.descricao is not None


def test_parse_response_handles_missing_hits():
    assert parse_response({}) == ([], None)
    assert parse_response({"hits": {}}) == ([], None)


def test_parse_response_extracts_total_int_form():
    """Some endpoints return `total` as a bare int rather than the
    `{"value": N}` ES shape — handle both."""
    payload = {"hits": {"total": 42, "hits": []}}
    _, total = parse_response(payload)
    assert total == 42


def test_parse_response_skips_hits_without_id_or_neighbourhood():
    """Defensive: a hit with no `_source.id` or no `neighbourhood`
    shouldn't crash the parser or produce a malformed stub. Without
    `neighbourhood` or `regionName` we can't tag the bairro at all,
    so the parser drops the listing."""
    payload = {
        "hits": {
            "total": {"value": 3},
            "hits": [
                {"_id": "x", "_source": {}},
                {"_id": "y", "_source": {"id": "1"}},  # no bairro
                {"_id": "z", "_source": {"id": "2", "neighbourhood": "Pinheiros"}},
            ],
        }
    }
    stubs, _ = parse_response(payload)
    assert len(stubs) == 1
    assert stubs[0].source_id == "2"
    assert stubs[0].bairro == "Pinheiros"


def test_parse_response_falls_back_to_regionName():
    """When the API only sets `regionName` (not `neighbourhood`),
    use that — the scraper still canonicalizes against config."""
    payload = {
        "hits": {
            "total": {"value": 1},
            "hits": [
                {"_id": "a", "_source": {"id": "5", "regionName": "Itaim Bibi"}},
            ],
        }
    }
    stubs, _ = parse_response(payload)
    assert len(stubs) == 1
    assert stubs[0].bairro == "Itaim Bibi"
