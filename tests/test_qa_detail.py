"""Tests for `scrapers/qa/detail.py` — parses QA's `__NEXT_DATA__`
SSR payload to populate `DetailFields`.

The fixture is a trimmed real `__NEXT_DATA__` capture wrapped in a
script tag. When QA changes the JSON shape, save a fresh capture and
update these expectations.
"""

import json
from datetime import date
from pathlib import Path

from aptos_sp.scrapers.qa.detail import parse_detail

FIXTURES = Path(__file__).parent / "fixtures" / "qa"


def _html() -> str:
    return (FIXTURES / "detail_893327546.html").read_text(encoding="utf-8")


def test_parse_detail_extracts_long_description():
    detail = parse_detail(_html())
    assert detail.description is not None
    # The fixture's `longDescription` starts with this phrase.
    assert detail.description.startswith("Este apartamento")
    # Long-form description, not the 1-line shortRentDescription.
    assert len(detail.description) > 100


def test_parse_detail_extracts_display_id():
    detail = parse_detail(_html())
    # QA's public-facing listing code; mirrors the role of ZAP's
    # `Código do anunciante`.
    assert detail.anunciante_code == "627546"


def test_parse_detail_extracts_criado_em():
    detail = parse_detail(_html())
    # Captured fixture's `lastPublishedDate` was 2025-11-21T17:36:46Z.
    assert detail.criado_em == date(2025, 11, 21)


def test_parse_detail_extracts_endereco_with_state():
    detail = parse_detail(_html())
    # Format: "<street>, <neighborhood>, <city> - <SP>"
    assert detail.endereco == "Rua Oscar Freire, Pinheiros, São Paulo - SP"


def test_parse_detail_extracts_lat_lng():
    detail = parse_detail(_html())
    assert detail.address_lat == -23.5589574
    assert detail.address_lng == -46.6731856


def test_parse_detail_splits_condo_and_iptu():
    """QA's search-list bundles `condoPrice + iptu` into one number;
    the detail page exposes them separately. The parser pulls them
    apart so `condominio` and `iptu` columns are accurate."""
    detail = parse_detail(_html())
    assert detail.condominio == 2031.0
    assert detail.iptu == 600.0


def test_parse_detail_renders_floor_range():
    """`rangeFloor: {min: 4, max: 7}` becomes "4° a 7° andar" so it
    drops straight into `aptos.andar TEXT` round-tripping unchanged."""
    detail = parse_detail(_html())
    assert detail.andar == "4° a 7° andar"


def test_parse_detail_renders_floor_range_collapses_when_equal():
    """When min == max, render as a single floor."""
    payload = {
        "props": {
            "pageProps": {
                "initialState": {
                    "house": {"houseInfo": {"id": 1, "rangeFloor": {"min": 5, "max": 5}}}
                }
            }
        }
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    detail = parse_detail(html)
    assert detail.andar == "5° andar"


def test_parse_detail_extracts_pets_subway_and_fees():
    detail = parse_detail(_html())
    assert detail.accepts_pets is False  # captured fixture had `acceptsPets: False`
    assert detail.near_subway is True
    assert detail.tenant_service_fee == 186.0
    assert detail.home_protection_fee == 92.0


def test_parse_detail_construction_year_when_missing():
    """Real fixture has `constructionYear: null` — should round-trip
    to None, not crash."""
    detail = parse_detail(_html())
    assert detail.construction_year is None


def test_parse_detail_falls_back_to_short_description():
    """When `longDescription` is empty, fall back to the
    `shortRentDescription` so listings without a rich block still
    persist something."""
    payload = {
        "props": {
            "pageProps": {
                "initialState": {
                    "house": {
                        "houseInfo": {
                            "id": 1,
                            "generatedDescription": {
                                "longDescription": "",
                                "shortRentDescription": "Apartamento curtinho.",
                            },
                        }
                    }
                }
            }
        }
    }
    html = (
        f'<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload, ensure_ascii=False)}</script>"
    )
    detail = parse_detail(html)
    assert detail.description == "Apartamento curtinho."


def test_parse_detail_handles_missing_next_data():
    detail = parse_detail("<html><body>no next data</body></html>")
    assert detail.description is None
    assert detail.anunciante_code is None
    assert detail.criado_em is None
    assert detail.endereco is None
    assert detail.address_lat is None
    assert detail.address_lng is None


def test_parse_detail_handles_malformed_json():
    detail = parse_detail('<script id="__NEXT_DATA__" type="application/json">{not valid}</script>')
    assert detail.description is None


def test_parse_detail_falls_back_displayId_to_internal_id():
    """If `displayId` is missing, use the internal `id` as the
    code rather than dropping it."""
    payload = {"props": {"pageProps": {"initialState": {"house": {"houseInfo": {"id": 42}}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    detail = parse_detail(html)
    assert detail.anunciante_code == "42"


def test_parse_detail_invalid_date_returns_none():
    payload = {
        "props": {
            "pageProps": {
                "initialState": {
                    "house": {
                        "houseInfo": {
                            "id": 1,
                            "lastPublishedDate": "not-a-date",
                        }
                    }
                }
            }
        }
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    detail = parse_detail(html)
    assert detail.criado_em is None
