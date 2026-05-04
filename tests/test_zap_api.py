"""Tests for ZAP `glue-api` URL building + JSON parsing.

No live HTTP in tests — fixtures are committed under
`tests/fixtures/zap/`. When ZAP changes the JSON shape, save a fresh
capture and update these expectations.
"""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from aptos_sp.config.filters import Filters
from aptos_sp.scrapers.zap.api import (
    INCLUDE_FIELDS,
    PAGE_SIZE,
    build_url,
    parse_response,
    total_count,
)
from aptos_sp.scrapers.zap.locations import (
    UnknownNeighborhood,
    location_for,
)

FIXTURES = Path(__file__).parent / "fixtures" / "zap"


def _payload() -> dict:
    return json.loads((FIXTURES / "api_pinheiros.json").read_text(encoding="utf-8"))


def _filters(**overrides) -> Filters:
    """Default filters mirror the operator's `filters.example.yaml`."""
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


# --- URL building --------------------------------------------------------


def test_build_url_includes_required_params():
    location = location_for("Moema")
    url = build_url(location, _filters(), page=1)
    qs = parse_qs(urlparse(url).query)
    assert qs["business"] == ["RENTAL"]
    assert qs["addressNeighborhood"] == ["Moema"]
    assert qs["addressZone"] == ["Zona Sul"]
    assert qs["addressLocationId"] == ["BR>Sao Paulo>NULL>Sao Paulo>Zona Sul>Moema"]
    assert qs["page"] == ["1"]
    assert qs["size"] == [str(PAGE_SIZE)]
    assert qs["from"] == ["0"]
    assert qs["includeFields"] == [INCLUDE_FIELDS]
    assert qs["amenities"] == ["FURNISHED"]


def test_build_url_pagination_offset():
    location = location_for("Moema")
    url = build_url(location, _filters(), page=3)
    qs = parse_qs(urlparse(url).query)
    assert qs["page"] == ["3"]
    assert qs["from"] == [str(2 * PAGE_SIZE)]


def test_build_url_omits_furnished_when_disabled():
    location = location_for("Moema")
    url = build_url(location, _filters(mobiliado=False), page=1)
    qs = parse_qs(urlparse(url).query)
    assert "amenities" not in qs


def test_build_url_includes_apartment_filter():
    """Without these server-side filters the API returns all property
    types and pagination behaves oddly. See ADR-011 / API capture."""
    location = location_for("Moema")
    url = build_url(location, _filters(), page=1)
    qs = parse_qs(urlparse(url).query)
    assert qs["unitTypes"] == ["APARTMENT"]
    assert qs["unitTypesV3"] == ["APARTMENT"]
    assert qs["unitSubTypes"] == ["UnitSubType_NONE,DUPLEX,TRIPLEX"]
    assert qs["usageTypes"] == ["RESIDENTIAL"]


def test_build_url_applies_bedroom_range():
    """quartos_min=1, quartos_max=3 → bedrooms=1,2,3."""
    location = location_for("Moema")
    url = build_url(location, _filters(quartos_min=1, quartos_max=3), page=1)
    qs = parse_qs(urlparse(url).query)
    assert qs["bedrooms"] == ["1,2,3"]


def test_build_url_applies_parking_min():
    """vagas_min=1 → parkingSpaces=1,2,3,4 (≥1)."""
    location = location_for("Moema")
    url = build_url(location, _filters(vagas_min=1), page=1)
    qs = parse_qs(urlparse(url).query)
    assert qs["parkingSpaces"] == ["1,2,3,4"]


def test_build_url_applies_total_price_cap():
    """total_max=11000 → rentalTotalPriceMax=11000 + rentTotalPrice=true."""
    location = location_for("Moema")
    url = build_url(location, _filters(total_max=11000), page=1)
    qs = parse_qs(urlparse(url).query)
    assert qs["rentalTotalPriceMax"] == ["11000"]
    assert qs["rentTotalPrice"] == ["true"]


def test_build_url_applies_area_min():
    """area_min_m2=70 → usableAreasMin=70."""
    location = location_for("Moema")
    url = build_url(location, _filters(area_min_m2=70), page=1)
    qs = parse_qs(urlparse(url).query)
    assert qs["usableAreasMin"] == ["70"]


def test_total_count_extracted():
    payload = _payload()
    assert total_count(payload) == 3


def test_total_count_missing_returns_none():
    assert total_count({}) is None
    assert total_count({"search": {}}) is None


# --- Parsing -------------------------------------------------------------


def test_parse_response_extracts_every_listing():
    listings = parse_response(_payload(), bairro="Pinheiros")
    assert len(listings) == 3
    assert {stub.source for stub in listings} == {"zap"}
    assert {stub.bairro for stub in listings} == {"Pinheiros"}


def test_parse_response_structured_fields():
    by_id = {stub.source_id: stub for stub in parse_response(_payload(), bairro="Pinheiros")}
    full = by_id["2510042000-30"]
    assert full.url == (
        "https://www.zapimoveis.com.br/imovel/"
        "aluguel-apartamento-2-quartos-pinheiros-id-2510042000-30/"
    )
    assert full.area_m2 == 78
    assert full.quartos == 2
    assert full.suites == 1
    assert full.banheiros == 2
    assert full.vagas == 1
    assert full.aluguel == 7800
    assert full.condominio == 1200
    # IPTU is yearly in the API; we store the monthly equivalent.
    assert full.iptu == pytest.approx(300.0)
    assert full.total == pytest.approx(7800 + 1200 + 300)
    assert full.endereco == "Rua dos Pinheiros, 500, Pinheiros, São Paulo"


def test_parse_response_partial_pricing():
    by_id = {stub.source_id: stub for stub in parse_response(_payload(), bairro="Pinheiros")}
    no_iptu = by_id["2511099000-15"]
    assert no_iptu.iptu is None
    assert no_iptu.total == pytest.approx(5500 + 950)


def test_parse_response_extracts_description_and_amenities():
    by_id = {stub.source_id: stub for stub in parse_response(_payload(), bairro="Pinheiros")}
    full = by_id["2510042000-30"]
    assert full.descricao is not None
    assert "chuveiro a gás" in full.descricao
    assert full.amenities == ["AIR_CONDITIONING", "FURNISHED", "LAVABO", "GYM"]
    sparse = by_id["missing-prices"]
    assert sparse.descricao is None
    assert sparse.amenities == []


def test_parse_response_handles_missing_fields_gracefully():
    by_id = {stub.source_id: stub for stub in parse_response(_payload(), bairro="Pinheiros")}
    sparse = by_id["missing-prices"]
    assert sparse.area_m2 is None
    assert sparse.quartos is None
    assert sparse.aluguel is None
    assert sparse.total is None


def test_parse_response_returns_empty_when_listings_missing():
    assert parse_response({}, bairro="Pinheiros") == []
    assert parse_response({"search": {"result": {}}}, bairro="Pinheiros") == []


def test_parse_response_preserves_absolute_urls():
    by_id = {stub.source_id: stub for stub in parse_response(_payload(), bairro="Pinheiros")}
    assert by_id["2511099000-15"].url == (
        "https://www.zapimoveis.com.br/imovel/"
        "aluguel-apartamento-1-quarto-pinheiros-id-2511099000-15/"
    )


# --- Locations -----------------------------------------------------------


def test_location_for_known_neighborhoods():
    assert location_for("Pinheiros")["zone"] == "Zona Oeste"
    assert location_for("Moema")["location_id"] == ("BR>Sao Paulo>NULL>Sao Paulo>Zona Sul>Moema")


def test_location_for_unknown_raises_with_actionable_message():
    with pytest.raises(UnknownNeighborhood, match="LOCATIONS"):
        location_for("Higienópolis")
