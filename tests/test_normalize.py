from __future__ import annotations

import datetime

import pytest

from awara_monitor import normalize


@pytest.mark.parametrize(
    "text,deal,expected",
    [
        ("1,399万円", "sale", 13_990_000),
        ("770万円～800万円", "sale", 7_700_000),
        ("100万円", "sale", 1_000_000),
        ("2,980万円", "sale", 29_800_000),
        ("50万円", "sale", 500_000),
        ("6.7万円", "rent", 67_000),
        ("5万円", "rent", 50_000),
        ("4万5千円/月", "rent", 45_000),
        ("4万5000円", "rent", 45_000),
        ("55,000円", "rent", 55_000),
        ("5.5万円", "rent", 55_000),
        ("応相談", "sale", None),
        ("", "sale", None),
    ],
)
def test_parse_price_yen(text, deal, expected):
    assert normalize.parse_price_yen(text, deal) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("169.77m2（51.35坪）", 169.77),
        ("84.11㎡", 84.11),
        ("110平米", 110.0),
        ("m<sup>2</sup> なし", None),
    ],
)
def test_parse_area_m2(text, expected):
    assert normalize.parse_area_m2(text) == expected


def test_parse_built_year():
    today = datetime.date(2026, 8, 30)
    assert normalize.parse_built_year("1990年12月", today=today) == 1990
    assert normalize.parse_built_year("昭和53年", today=today) == 1978
    assert normalize.parse_built_year("平成10年3月", today=today) == 1998
    assert normalize.parse_built_year("令和2年", today=today) == 2020
    assert normalize.parse_built_year("築40年", today=today) == 1986
    assert normalize.parse_built_year("新築", today=today) == 2026
    assert normalize.parse_built_year("不明") is None


def test_extract_town():
    assert normalize.extract_town("福井県あわら市大溝三丁目1-2") == "大溝"
    assert normalize.extract_town("あわら市二面１") == "二面"
    assert normalize.extract_town("あわら市舟津") == "舟津"
    assert normalize.extract_town("福井県あわら市花乃杜一丁目") == "花乃杜"


def test_normalize_address_equivalence():
    a = normalize.normalize_address("福井県あわら市大溝３丁目１２－３")
    b = normalize.normalize_address("あわら市大溝三丁目12-3")
    assert a == b
    assert "大溝" in a


def test_parse_walk_minutes_target_station():
    lines = ["えちぜん鉄道三国線「あわら湯のまち」徒歩14分"]
    minutes, txt = normalize.parse_walk_minutes(lines, ("あわら湯のまち", "芦原湯のまち"))
    assert minutes == 14
    assert "あわら湯のまち" in txt


def test_parse_walk_minutes_ignores_other_station():
    lines = ["ハピラインふくい/芦原温泉駅 歩18分", "北陸新幹線/芦原温泉駅 歩10分"]
    minutes, _ = normalize.parse_walk_minutes(lines, ("あわら湯のまち", "芦原湯のまち"))
    assert minutes is None


def test_parse_walk_minutes_ignores_bus():
    lines = ["えちぜん鉄道三国線/あわら湯のまち駅 バス3分 (バス停)セントピアあわら 歩6分"]
    minutes, _ = normalize.parse_walk_minutes(lines, ("あわら湯のまち",))
    assert minutes is None


def test_parse_walk_minutes_meters():
    lines = ["あわら湯のまち駅まで約640m"]
    minutes, _ = normalize.parse_walk_minutes(lines, ("あわら湯のまち",), meters_per_minute=80)
    assert minutes == 8


def test_looks_excluded():
    assert normalize.looks_excluded("中古マンション", keywords=("マンション", "アパート")) == "マンション"
    assert normalize.looks_excluded("中古一戸建て", keywords=("マンション",)) is None


def test_has_banchi():
    assert normalize.has_banchi("福井県あわら市番田1-1-15") is True
    assert normalize.has_banchi("福井県あわら市二面") is False
    assert normalize.has_banchi("あわら市大溝三丁目12") is True
