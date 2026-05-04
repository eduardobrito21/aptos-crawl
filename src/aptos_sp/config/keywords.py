"""Pydantic schema + loader for `config/keywords.yaml`.

`cozinha_layout` is special-cased: instead of `positive`/`negative` lists,
its value is a dict keyed by output value (`isolada` | `americana` |
`integrada`) → list of keyword strings. This is intentional — see
ADR-007 and the comment in `keywords.yaml`.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from aptos_sp.config import CONFIG_DIR

CozinhaLayoutValue = Literal["isolada", "americana", "integrada"]


class BinaryKeyword(BaseModel):
    """Tri-state result: positive match → True, negative match → False,
    neither → NULL (caller resolves NULL)."""

    positive: list[str] = Field(default_factory=list)
    negative: list[str] = Field(default_factory=list)


class CozinhaLayout(BaseModel):
    isolada: list[str] = Field(default_factory=list)
    americana: list[str] = Field(default_factory=list)
    integrada: list[str] = Field(default_factory=list)


class KeywordsConfig(BaseModel):
    chuveiro_gas: BinaryKeyword
    chuveirinho: BinaryKeyword
    ar_condicionado: BinaryKeyword
    vidro_anti_ruido: BinaryKeyword
    cozinha_layout: CozinhaLayout
    lavabo: BinaryKeyword


def load(path: Path | None = None) -> KeywordsConfig:
    target = path or (CONFIG_DIR / "keywords.yaml")
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return KeywordsConfig.model_validate(raw)
