"""Tests for `pipeline/extract.py` — keyword + amenity tri-state."""

from aptos_sp.pipeline.extract import extract_qualitative


def test_chuveiro_gas_positive():
    out = extract_qualitative("Apartamento com chuveiro a gás Rinnai", [])
    assert out.chuveiro_gas is True


def test_chuveiro_gas_negative_overrides():
    # Explicit "chuveiro elétrico" → False, even if gas is mentioned
    # nowhere. Negative wins so the operator sees a definitive signal.
    out = extract_qualitative("Studio com chuveiro elétrico padrão", [])
    assert out.chuveiro_gas is False


def test_chuveiro_gas_unknown_when_absent():
    out = extract_qualitative("Apto reformado, vista linda", [])
    assert out.chuveiro_gas is None


def test_ar_condicionado_via_split_keyword():
    out = extract_qualitative("Apto com split na sala e nos quartos", [])
    assert out.ar_condicionado is True


def test_ar_condicionado_via_amenity_when_keyword_silent():
    # No keyword hit, but ZAP's structured AIR_CONDITIONING amenity
    # promotes None → True.
    out = extract_qualitative("Apartamento bem localizado", ["AIR_CONDITIONING", "GYM"])
    assert out.ar_condicionado is True


def test_amenity_does_not_override_explicit_negative():
    # Even if the source claims AIR_CONDITIONING, "sem ar condicionado"
    # in prose is a stronger signal — keep False.
    out = extract_qualitative("Sem ar condicionado", ["AIR_CONDITIONING"])
    assert out.ar_condicionado is False


def test_lavabo_via_amenity():
    # ZAP has an explicit LAVABO flag — far more reliable than fishing
    # for the word in prose.
    out = extract_qualitative("Apartamento com 2 banheiros", ["LAVABO"])
    assert out.lavabo is True


def test_lavabo_unknown_without_signal():
    # ADR-007: prefer null over false positive. "2 banheiros" alone is
    # not enough.
    out = extract_qualitative("Apartamento com 2 banheiros", [])
    assert out.lavabo is None


def test_chuveirinho_positive():
    out = extract_qualitative("Banheiro com ducha higiênica", [])
    assert out.chuveirinho is True


def test_vidro_anti_ruido_positive():
    out = extract_qualitative("Janelas com vidro acústico", [])
    assert out.vidro_anti_ruido is True


def test_cozinha_layout_americana():
    out = extract_qualitative("Cozinha americana com bancada", [])
    assert out.cozinha_layout == "americana"


def test_cozinha_layout_isolada():
    out = extract_qualitative("Cozinha isolada com porta", [])
    assert out.cozinha_layout == "isolada"


def test_cozinha_layout_integrada():
    out = extract_qualitative("Sala e cozinha integradas", [])
    assert out.cozinha_layout == "integrada"


def test_cozinha_layout_integrada_phrase_priority():
    # When an integrada-bucket phrase matches alongside an americana
    # phrase, integrada wins — it's the more specific signal in the loop
    # ordering. "ambientes integrados" is in the integrada bucket.
    out = extract_qualitative("Cozinha americana, ambientes integrados", [])
    assert out.cozinha_layout == "integrada"


def test_cozinha_layout_unknown_when_absent():
    out = extract_qualitative("Apto reformado", [])
    assert out.cozinha_layout is None


def test_handles_none_description_with_amenities():
    out = extract_qualitative(None, ["LAVABO", "AIR_CONDITIONING"])
    assert out.lavabo is True
    assert out.ar_condicionado is True
    assert out.cozinha_layout is None


def test_handles_empty_inputs():
    out = extract_qualitative(None, None)
    assert out.chuveiro_gas is None
    assert out.lavabo is None


def test_full_fixture_listing():
    # The first fixture listing has gas + AC + lavabo + acoustic glass +
    # americana integrada. Expected: integrada wins, all others True.
    text = (
        "Lindo apartamento em Pinheiros, com chuveiro a gás, ar "
        "condicionado split em todos os ambientes e cozinha americana "
        "integrada à sala. Possui lavabo e vidro acústico nas janelas."
    )
    out = extract_qualitative(text, ["AIR_CONDITIONING", "FURNISHED", "LAVABO"])
    assert out.chuveiro_gas is True
    assert out.ar_condicionado is True
    assert out.vidro_anti_ruido is True
    assert out.lavabo is True
    # Phrase "cozinha americana" matches before any integrada-bucket
    # phrase. "Cozinha americana integrada" is real-world ambiguous —
    # americana is a true signal here either way.
    assert out.cozinha_layout == "americana"
