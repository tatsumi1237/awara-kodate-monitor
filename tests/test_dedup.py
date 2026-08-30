from __future__ import annotations

from awara_monitor import dedup


def sig(**kw) -> dedup.Signature:
    base = dict(
        deal_type="sale",
        address_norm="あわら市二面1-2-3",
        town="二面",
        price=1_800_000,
        layout="5DK",
        land_area=250.0,
        building_area=110.0,
        built_year=1978,
    )
    base.update(kw)
    return dedup.Signature(**base)


def test_identical_is_merge():
    s, reasons = dedup.score(sig(), sig())
    assert s >= dedup.MERGE_THRESHOLD
    assert "正規化住所が一致" in reasons


def test_same_house_slightly_different_still_merges():
    a = sig()
    b = sig(price=1_780_000, building_area=109.5, layout="5DK")  # 別サイトで微妙に違う
    s, _ = dedup.score(a, b)
    assert s >= dedup.MERGE_THRESHOLD


def test_different_deal_type_never_matches():
    s, _ = dedup.score(sig(), sig(deal_type="rent"))
    assert s == 0.0


def test_similar_but_low_confidence_is_candidate_only():
    a = sig(address_norm="あわら市二面", town="二面")
    b = sig(address_norm="あわら市二面", town="二面", price=1_850_000,
            land_area=None, building_area=None, built_year=None, layout="")
    s, _ = dedup.score(a, b)
    assert dedup.CANDIDATE_THRESHOLD <= s < dedup.MERGE_THRESHOLD


def test_different_houses_do_not_match():
    a = sig()
    b = sig(address_norm="あわら市春宮3-1-1", town="春宮", price=2_400_000,
            layout="3LDK", land_area=120.0, building_area=95.0, built_year=2001)
    s, _ = dedup.score(a, b)
    assert s < dedup.CANDIDATE_THRESHOLD
