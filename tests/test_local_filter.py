"""Tests for `pipeline.local_filter` — the canonical
"does this listing match `filters.yaml`?" predicate."""

from aptos_sp.config.filters import Filters
from aptos_sp.pipeline.local_filter import is_mobiliado, passes_filters, why_rejected
from aptos_sp.scrapers.base import ListingStub


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


def _stub(**overrides) -> ListingStub:
    base: dict[str, object] = {
        "source": "zap",
        "source_id": "1",
        "url": "https://example.com/1",
        "bairro": "Pinheiros",
        "quartos": 2,
        "vagas": 1,
        "area_m2": 80.0,
        "total": 8000.0,
        "amenities": ["FURNISHED"],
        "is_furnished": True,
    }
    base.update(overrides)
    return ListingStub(**base)  # type: ignore[arg-type]


# --- happy path ---------------------------------------------------------


def test_passes_when_all_dimensions_match():
    assert passes_filters(_stub(), _filters()) is True
    assert why_rejected(_stub(), _filters()) is None


# --- quartos ------------------------------------------------------------


def test_rejects_quartos_above_max():
    f = _filters(quartos_max=3)
    assert passes_filters(_stub(quartos=4), f) is False
    reason = why_rejected(_stub(quartos=4), f)
    assert reason and reason.field == "quartos"


def test_rejects_quartos_below_min():
    f = _filters(quartos_min=1)
    assert passes_filters(_stub(quartos=0), f) is False


def test_rejects_missing_quartos():
    reason = why_rejected(_stub(quartos=None), _filters())
    assert reason and reason.field == "quartos"


# --- vagas --------------------------------------------------------------


def test_rejects_below_vagas_min():
    reason = why_rejected(_stub(vagas=0), _filters(vagas_min=1))
    assert reason and reason.field == "vagas"


def test_vagas_min_zero_is_no_constraint():
    """When `vagas_min=0`, even missing-vagas listings pass that
    dimension — the operator opted out of the constraint."""
    assert passes_filters(_stub(vagas=None), _filters(vagas_min=0)) is True
    assert passes_filters(_stub(vagas=0), _filters(vagas_min=0)) is True


def test_rejects_missing_vagas_when_min_positive():
    reason = why_rejected(_stub(vagas=None), _filters(vagas_min=1))
    assert reason and reason.field == "vagas"


# --- area + flex --------------------------------------------------------


def test_rejects_area_below_strict_floor():
    reason = why_rejected(_stub(area_m2=65, quartos=2), _filters())
    assert reason and reason.field == "area_m2"


def test_accepts_area_in_flex_range_for_1q_with_office():
    """1-bedroom + escritório triggers `area_min_m2_flex` (60)."""
    stub = _stub(quartos=1, area_m2=65, descricao="1 quarto + escritório, vista linda")
    assert passes_filters(stub, _filters()) is True


def test_rejects_area_in_flex_range_without_office_signal():
    stub = _stub(quartos=1, area_m2=65, descricao="1 quarto reformado")
    assert passes_filters(stub, _filters()) is False


def test_rejects_missing_area():
    reason = why_rejected(_stub(area_m2=None), _filters())
    assert reason and reason.field == "area_m2"


# --- total --------------------------------------------------------------


def test_rejects_total_above_ceiling():
    reason = why_rejected(_stub(total=12000), _filters(total_max=11000))
    assert reason and reason.field == "total"


def test_rejects_missing_total():
    reason = why_rejected(_stub(total=None), _filters())
    assert reason and reason.field == "total"


# --- mobiliado ----------------------------------------------------------


def test_mobiliado_true_only_via_explicit_flag():
    """Plan 0008 audit found QA furniture amenities are noisy
    (built-in wardrobes appear in unfurnished listings). The
    predicate trusts only the source's explicit furnished flag,
    which the parsers populate from ZAP's `FURNISHED` amenity and
    QA's `isFurnished` bool."""
    assert is_mobiliado(_stub(is_furnished=True)) is True
    assert is_mobiliado(_stub(is_furnished=False)) is False
    # `None` is "unknown"; per ADR-007 we reject rather than guess.
    assert is_mobiliado(_stub(is_furnished=None)) is False


def test_mobiliado_false_even_with_furniture_amenity():
    """Furniture in the amenities list does NOT imply mobiliado —
    the audit found unfurnished listings with built-in wardrobes."""
    stub = _stub(
        is_furnished=False,
        amenities=["CAMA_DE_CASAL", "MESAS_E_CADEIRAS_DE_JANTAR", "SOFA"],
    )
    assert is_mobiliado(stub) is False


def test_passes_filters_rejects_when_mobiliado_required_but_unfurnished():
    f = _filters(mobiliado=True)
    stub = _stub(is_furnished=False)
    reason = why_rejected(stub, f)
    assert reason and reason.field == "mobiliado"


def test_passes_filters_ignores_mobiliado_when_filter_disabled():
    """`mobiliado=false` in filters → the predicate skips the check
    entirely; even an unfurnished listing passes."""
    f = _filters(mobiliado=False)
    stub = _stub(is_furnished=False)
    assert passes_filters(stub, f) is True
