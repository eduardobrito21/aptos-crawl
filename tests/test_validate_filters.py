"""Tests for the axis-builder used by `validate-filters` (Plan 0008)."""

from aptos_sp.cli.validate_filters import AXES, filters_for_axes
from aptos_sp.config.filters import Filters


def _operator() -> Filters:
    return Filters.model_validate(
        {
            "quartos_min": 1,
            "quartos_max": 3,
            "vagas_min": 1,
            "area_min_m2": 70,
            "area_min_m2_flex": 60,
            "mobiliado": True,
            "total_max": 11000,
            "tipo": "apartamento",
        }
    )


def test_no_axes_returns_fully_permissive():
    f = filters_for_axes(_operator(), [])
    assert f.quartos_min == 1 and f.quartos_max == 4
    assert f.vagas_min == 0
    assert f.area_min_m2 == 1.0 and f.area_min_m2_flex == 1.0
    assert f.mobiliado is False
    assert f.total_max == 9_999_999.0


def test_single_axis_isolates_that_dimension():
    f = filters_for_axes(_operator(), ["mobiliado"])
    # mobiliado picks up the operator value
    assert f.mobiliado is True
    # other axes stay permissive
    assert f.quartos_max == 4
    assert f.vagas_min == 0
    assert f.area_min_m2 == 1.0
    assert f.total_max == 9_999_999.0


def test_pair_axes_isolates_both():
    f = filters_for_axes(_operator(), ["area", "total"])
    assert f.area_min_m2 == 70
    assert f.area_min_m2_flex == 60
    assert f.total_max == 11000
    # everything else permissive
    assert f.mobiliado is False
    assert f.vagas_min == 0


def test_all_axes_matches_operator():
    f = filters_for_axes(_operator(), AXES)
    op = _operator()
    for field in (
        "quartos_min",
        "quartos_max",
        "vagas_min",
        "area_min_m2",
        "area_min_m2_flex",
        "mobiliado",
        "total_max",
    ):
        assert getattr(f, field) == getattr(op, field)
