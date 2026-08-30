"""重複物件（複数サイト掲載 / 同一物件）の判定.

完全一致でなくても、住所・価格・間取り・面積・築年の一致度でスコアリングする。
- score >= MERGE_THRESHOLD  : 同一物件として統合
- score >= CANDIDATE_THRESHOLD : 別物件として扱うが「重複候補」を記録
- それ未満                   : 別物件
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

MERGE_THRESHOLD = 0.75
CANDIDATE_THRESHOLD = 0.5


@dataclass
class Signature:
    deal_type: str
    address_norm: str
    town: str
    price: Optional[int]
    layout: str
    land_area: Optional[float]
    building_area: Optional[float]
    built_year: Optional[int]

    @classmethod
    def from_row(cls, row) -> "Signature":
        return cls(
            deal_type=row["deal_type"] or "",
            address_norm=row["address_norm"] or "",
            town=row["town"] or "",
            price=row["current_price"],
            layout=row["layout"] or "",
            land_area=row["land_area"],
            building_area=row["building_area"],
            built_year=row["built_year"],
        )


def _close(a: Optional[float], b: Optional[float], rel: float) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= rel


def score(a: Signature, b: Signature) -> tuple[float, list[str]]:
    """2つの signature の同一度スコアと根拠。"""
    if a.deal_type != b.deal_type:
        return 0.0, ["取引種別が異なる"]

    s = 0.0
    reasons: list[str] = []

    if a.address_norm and b.address_norm and a.address_norm == b.address_norm:
        s += 0.55
        reasons.append("正規化住所が一致")
    elif a.town and b.town and a.town == b.town:
        s += 0.15
        reasons.append("町名が一致")
    elif a.address_norm and b.address_norm and (
        a.address_norm.startswith(b.address_norm) or b.address_norm.startswith(a.address_norm)
    ):
        s += 0.30
        reasons.append("住所が前方一致")

    if a.price and b.price:
        if a.price == b.price:
            s += 0.22
            reasons.append("価格が完全一致")
        elif _close(a.price, b.price, 0.03):
            s += 0.15
            reasons.append("価格がほぼ一致(±3%)")

    if a.layout and b.layout and a.layout == b.layout:
        s += 0.12
        reasons.append("間取りが一致")

    if _close(a.land_area, b.land_area, 0.03):
        s += 0.12
        reasons.append("土地面積が一致")

    if _close(a.building_area, b.building_area, 0.03):
        s += 0.12
        reasons.append("建物面積が一致")

    if a.built_year and b.built_year and a.built_year == b.built_year:
        s += 0.10
        reasons.append("築年が一致")

    return round(s, 3), reasons


@dataclass
class MatchResult:
    internal_id: Optional[int]
    score: float
    reasons: list[str]

    @property
    def is_merge(self) -> bool:
        return self.internal_id is not None and self.score >= MERGE_THRESHOLD

    @property
    def is_candidate(self) -> bool:
        return self.internal_id is not None and self.score >= CANDIDATE_THRESHOLD


def find_match(sig: Signature, existing_rows) -> MatchResult:
    """既存 property 群から最良マッチを探す。"""
    best = MatchResult(None, 0.0, [])
    for row in existing_rows:
        other = Signature.from_row(row)
        sc, reasons = score(sig, other)
        if sc > best.score:
            best = MatchResult(row["internal_id"], sc, reasons)
    return best
