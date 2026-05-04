"""Cross-platform dedup via heuristic fingerprint (ADR-006).

Operates on `aptos` rows after normalization has populated
`endereco_normalized`. Builds a 4-tuple fingerprint
(rua_norm, area_bucket, quartos, vagas) and compares listings within
the same bairro:

- **Strong match** — all four fields equal within tolerances
  (area ± 1m²): set the newer row's `possible_dup_of` to the older
  row's id. Per ADR-006 this still flags rather than auto-merges; the
  decision UI is `v_possible_dups`.
- **Weak match** — same street + neighborhood + bedrooms, area within
  ± 5m², but prices differ by > 10%. Same flag, different reason.
- **None** — leave alone.

Cross-bairro matches are skipped (the same apartment can't be in two
neighborhoods at once — ADR-006).
"""

import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

DupReason = Literal["strong", "weak"]

STRONG_AREA_TOL = 1.0
WEAK_AREA_TOL = 5.0
WEAK_PRICE_DIFF_PCT = 0.10

# First standalone number in a raw endereco — typically the street
# number. Used as a tie-breaker so two different buildings on the same
# street don't collapse into one fingerprint.
_STREET_NUMBER_RE = re.compile(r"\b(\d{1,5})\b")


@dataclass
class DedupStats:
    n_scanned: int = 0
    n_strong: int = 0
    n_weak: int = 0
    n_cleared: int = 0


@dataclass(frozen=True)
class _Row:
    id: int
    bairro: str | None
    endereco: str | None
    endereco_normalized: str | None
    area_m2: float | None
    quartos: int | None
    vagas: int | None
    total: float | None
    possible_dup_of: int | None

    @property
    def street_number(self) -> str | None:
        if not self.endereco:
            return None
        match = _STREET_NUMBER_RE.search(self.endereco)
        return match.group(1) if match else None


def find_and_flag_dups(conn: sqlite3.Connection) -> DedupStats:
    """Walk `aptos` once, set `possible_dup_of` where a strong/weak
    match exists. Idempotent: clears stale flags whose target row no
    longer matches before re-applying.
    """
    rows = _load_rows(conn)
    stats = DedupStats(n_scanned=len(rows))

    # Group by bairro; within a bairro, sort by id so the *older* row
    # (lower id) is the canonical anchor. Newer rows point back.
    by_bairro: dict[str, list[_Row]] = {}
    for row in rows:
        if not row.bairro:
            continue
        by_bairro.setdefault(row.bairro, []).append(row)

    new_flags: dict[int, int] = {}
    reasons: dict[int, DupReason] = {}
    for bairro_rows in by_bairro.values():
        bairro_rows.sort(key=lambda r: r.id)
        for i, candidate in enumerate(bairro_rows):
            if not candidate.endereco_normalized:
                continue
            for anchor in bairro_rows[:i]:
                if anchor.id in new_flags and new_flags[anchor.id] == candidate.id:
                    continue
                reason = _classify(anchor, candidate)
                if reason is not None:
                    new_flags[candidate.id] = anchor.id
                    reasons[candidate.id] = reason
                    break

    by_id = {r.id: r for r in rows}

    # Clear stale flags that no longer hold.
    for row in rows:
        if row.possible_dup_of is not None and new_flags.get(row.id) != row.possible_dup_of:
            conn.execute("UPDATE aptos SET possible_dup_of = NULL WHERE id = ?", (row.id,))
            stats.n_cleared += 1

    # Apply new flags, but only count the ones whose value changed —
    # rerunning with no schema/data change should report zero churn.
    for dup_id, anchor_id in new_flags.items():
        if by_id[dup_id].possible_dup_of == anchor_id:
            continue
        conn.execute(
            "UPDATE aptos SET possible_dup_of = ? WHERE id = ?",
            (anchor_id, dup_id),
        )
        if reasons[dup_id] == "strong":
            stats.n_strong += 1
        else:
            stats.n_weak += 1
    conn.commit()
    return stats


def _classify(anchor: _Row, candidate: _Row) -> DupReason | None:
    """Return 'strong' / 'weak' / None for one (anchor, candidate)."""
    if anchor.endereco_normalized != candidate.endereco_normalized:
        return None
    if candidate.quartos is None or anchor.quartos != candidate.quartos:
        return None
    if anchor.area_m2 is None or candidate.area_m2 is None:
        return None
    # Street-number guard: ADR-006 strips the number from the
    # fingerprint to handle cross-platform formatting differences, but
    # within a single source two different buildings on the same street
    # then collapse. When both raw addresses expose a number, require
    # them to match. When at least one side hides the number, fall back
    # to the address fingerprint (the cross-platform case ADR-006
    # designed for).
    a_num, b_num = anchor.street_number, candidate.street_number
    if a_num is not None and b_num is not None and a_num != b_num:
        return None

    area_diff = abs(anchor.area_m2 - candidate.area_m2)
    if area_diff <= STRONG_AREA_TOL and anchor.vagas == candidate.vagas:
        return "strong"

    if area_diff <= WEAK_AREA_TOL and _price_differs(anchor.total, candidate.total):
        return "weak"

    return None


def _price_differs(a: float | None, b: float | None) -> bool:
    """True when both prices are known and differ by more than the
    weak-match threshold. Unknown prices = no weak signal; leave
    alone."""
    if a is None or b is None or a == 0:
        return False
    return abs(a - b) / a > WEAK_PRICE_DIFF_PCT


def _load_rows(conn: sqlite3.Connection) -> list[_Row]:
    cur = conn.execute(
        """
        SELECT
            a.id, a.bairro, a.endereco, a.endereco_normalized, a.area_m2,
            a.quartos, a.vagas, a.possible_dup_of,
            (
                SELECT total FROM precos_historico
                WHERE apto_id = a.id
                ORDER BY snapshot_date DESC LIMIT 1
            ) AS total
        FROM aptos a
        """
    )
    return [
        _Row(
            id=row["id"],
            bairro=row["bairro"],
            endereco=row["endereco"],
            endereco_normalized=row["endereco_normalized"],
            area_m2=row["area_m2"],
            quartos=row["quartos"],
            vagas=row["vagas"],
            total=row["total"],
            possible_dup_of=row["possible_dup_of"],
        )
        for row in cur
    ]
