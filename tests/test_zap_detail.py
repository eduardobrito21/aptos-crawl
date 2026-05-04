"""Tests for `scrapers/zap/detail.py` — parses the rendered detail page.

The fixture is the `<section data-testid="description-container">` slice
of a real ZAP detail-page response, captured live. When ZAP changes the
detail-page DOM, save a fresh capture and update these expectations.
"""

from datetime import date
from pathlib import Path

from aptos_sp.scrapers.zap.detail import parse_detail

FIXTURES = Path(__file__).parent / "fixtures" / "zap"


def _html() -> str:
    return (FIXTURES / "detail_2881606995.html").read_text(encoding="utf-8")


def test_parse_detail_extracts_description():
    detail = parse_detail(_html())
    assert detail.description is not None
    assert detail.description.startswith("Apartamento no bairro Vila Nova Conceição.")
    # The description has multiple paragraphs separated by <br>; we
    # collapse them to newlines, so the cleaned text is multi-line.
    assert "\n" in detail.description
    # Spot-check a downstream criterion that the keyword matcher will
    # need to fire on (lavabo).
    assert "lavabo" in detail.description.lower()


def test_parse_detail_extracts_anunciante_code():
    detail = parse_detail(_html())
    assert detail.anunciante_code == "AP000701"


def test_parse_detail_extracts_criado_em():
    detail = parse_detail(_html())
    # Captured from a real listing dated "18 de abril de 2026".
    assert detail.criado_em == date(2026, 4, 18)


def test_parse_detail_extracts_endereco():
    detail = parse_detail(_html())
    assert detail.endereco == ("Rua Marcos Lopes, 272 - Vila Nova Conceição, São Paulo - SP")


def test_parse_detail_extracts_lat_lng():
    detail = parse_detail(_html())
    # Captured from a real listing's embedded Maps iframe.
    assert detail.address_lat == -23.597589
    assert detail.address_lng == -46.671628


def test_parse_detail_handles_empty_html():
    detail = parse_detail("")
    assert detail.description is None
    assert detail.anunciante_code is None
    assert detail.criado_em is None
    assert detail.endereco is None
    assert detail.address_lat is None
    assert detail.address_lng is None


def test_parse_detail_handles_partial_html_per_field():
    """A layout change to one block shouldn't nuke the other fields."""
    html_only_code = "<p>Código do anunciante: <!-- -->XYZ123<!-- --> | Código no Zap: 999</p>"
    detail = parse_detail(html_only_code)
    assert detail.anunciante_code == "XYZ123"
    assert detail.description is None
    assert detail.criado_em is None
    assert detail.endereco is None
    assert detail.address_lat is None


def test_parse_detail_iframe_with_escaped_ampersand():
    """ZAP renders `&` as `&amp;` in iframe srcs — the parser must
    decode before splitting query params, otherwise q= would be
    swallowed by the previous param."""
    html = (
        '<iframe data-testid="map-iframe" '
        'src="https://www.google.com/maps/embed/v1/place?key=ABC&amp;q=-23.5,-46.6"></iframe>'
    )
    detail = parse_detail(html)
    assert detail.address_lat == -23.5
    assert detail.address_lng == -46.6


def test_parse_detail_iframe_missing_q_param_returns_none():
    html = (
        '<iframe data-testid="map-iframe" '
        'src="https://www.google.com/maps/embed/v1/place?key=ABC"></iframe>'
    )
    detail = parse_detail(html)
    assert detail.address_lat is None
    assert detail.address_lng is None


def test_parse_detail_invalid_month_returns_none():
    """A typo'd month name shouldn't crash — None is the right tristate
    when we can't parse the date."""
    html = (
        '<span data-testid="listing-created-date">'
        "Anúncio criado em 18 de qualquer de 2026, atualizado há 1 hora."
        "</span>"
    )
    detail = parse_detail(html)
    assert detail.criado_em is None


def test_parse_detail_strips_html_inside_description():
    """Tags inside the description (<strong>, etc.) should be removed,
    not preserved in the cleaned text."""
    html = (
        '<p data-testid="description-content">'
        "Apto com <strong>lavabo</strong> e<br>cozinha americana.</p>"
    )
    detail = parse_detail(html)
    assert detail.description == "Apto com lavabo e\ncozinha americana."
