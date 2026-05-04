"""Tests for `pipeline/normalize.py` — text + endereco + area-flex."""

import pytest

from aptos_sp.config.filters import Filters
from aptos_sp.pipeline.normalize import (
    area_min_with_flex,
    normalize_endereco,
    normalize_text,
)


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


# --- normalize_text ------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Pinheiros", "pinheiros"),
        ("São Paulo", "sao paulo"),
        ("Vila Olímpia", "vila olimpia"),
        ("ÁÉÍÓÚáéíóú", "aeiouaeiou"),
        ("ÇÃÕç", "caoc"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_text(raw, expected):
    assert normalize_text(raw) == expected


# --- normalize_endereco --------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Rua dos Pinheiros, 500, Pinheiros", "dos pinheiros pinheiros"),
        ("R. dos Pinheiros 500", "dos pinheiros"),
        ("Avenida Brigadeiro Faria Lima, 1234", "brigadeiro faria lima"),
        ("Av. Paulista 1000", "paulista"),
        ("Alameda Santos", "santos"),
        ("Travessa do Comércio", "do comercio"),
        ("Rua João Moura, 250 - Pinheiros", "joao moura pinheiros"),
        ("RUA AUGUSTA 1500", "augusta"),
    ],
)
def test_normalize_endereco_strips_prefix_and_numbers(raw, expected):
    assert normalize_endereco(raw) == expected


def test_normalize_endereco_handles_none_and_empty():
    assert normalize_endereco(None) is None
    assert normalize_endereco("") is None
    # Bare number — no useful content for matching.
    assert normalize_endereco("500") is None


def test_normalize_endereco_collapses_whitespace_and_punct():
    # Multiple spaces, punctuation, and a hidden number embedded in the
    # number token should all collapse cleanly.
    raw = "  Rua  dos  Pinheiros,, 500-A  -- Pinheiros  "
    assert normalize_endereco(raw) == "dos pinheiros pinheiros"


def test_normalize_endereco_drops_accents():
    # Same street written with and without diacritics should fingerprint
    # to the same value.
    assert normalize_endereco("Rua João Moura, 250") == normalize_endereco("Rua Joao Moura 250")


# --- area_min_with_flex --------------------------------------------------


def test_area_min_with_flex_returns_default_for_2br():
    f = _filters()
    assert area_min_with_flex(f, quartos=2, descricao="Lindo apto") == 70


def test_area_min_with_flex_relaxes_for_1br_with_office():
    f = _filters()
    desc = "1 quarto + escritório, vista para o parque"
    assert area_min_with_flex(f, quartos=1, descricao=desc) == 60


def test_area_min_with_flex_relaxes_on_home_office_phrase():
    f = _filters()
    assert area_min_with_flex(f, quartos=1, descricao="Apto com home office separado") == 60


def test_area_min_with_flex_does_not_relax_without_office_hint():
    f = _filters()
    assert area_min_with_flex(f, quartos=1, descricao="Apto reformado, vista linda") == 70


def test_area_min_with_flex_does_not_relax_for_2br_with_office():
    # The flex rule is specifically "1 quarto + escritório". A 2-bedroom
    # with office text doesn't qualify.
    f = _filters()
    assert area_min_with_flex(f, quartos=2, descricao="2 quartos com home office") == 70


def test_area_min_with_flex_handles_none_quartos_or_descricao():
    f = _filters()
    assert area_min_with_flex(f, quartos=None, descricao="home office") == 70
    assert area_min_with_flex(f, quartos=1, descricao=None) == 70
