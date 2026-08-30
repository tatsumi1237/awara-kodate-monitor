from __future__ import annotations

import pytest

from awara_monitor import config
from scrapers.suumo import SuumoScraper

from .conftest import fixture_bytes


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.status_code = 200


class FakeSession:
    """URL に応じて対応するフィクスチャを返す。"""

    ROUTES = {
        "chukoikkodate": "suumo_chukoikkodate.html",
        "ikkodate": "suumo_ikkodate.html",
        "chintai": "suumo_chintai.html",
    }

    def __init__(self) -> None:
        self.requested: list[str] = []

    def get(self, url: str, **kw) -> FakeResponse:
        self.requested.append(url)
        for token, fname in self.ROUTES.items():
            if token in url:
                return FakeResponse(fixture_bytes(fname))
        raise AssertionError(f"想定外のURL: {url}")


class AllowGate:
    def allowed(self, url: str) -> bool:
        return True

    def require(self, url: str) -> None:
        return None


@pytest.fixture
def suumo(monkeypatch):
    monkeypatch.setattr(config, "MAX_LIST_PAGES", 1)
    return SuumoScraper(FakeSession(), AllowGate())


def test_suumo_parses_used_houses(suumo):
    items = suumo.fetch()
    sale = [x for x in items if x.deal_type == "sale"]
    assert len(sale) >= 10

    by_id = {x.site_property_id: x for x in sale}
    key = "chukoikkodate-nc20829911"
    assert key in by_id
    it = by_id[key]
    assert it.price == 13_990_000
    assert "番田" in it.address
    assert it.layout == "3LDK"
    assert it.land_area == 169.77
    assert it.building_area == 84.11
    assert it.built_year == 1990
    assert it.station_walk_minutes == 14  # 「あわら湯のまち」徒歩14分
    assert it.url.startswith("https://suumo.jp/chukoikkodate/")


def test_suumo_other_station_has_no_walk_minutes(suumo):
    items = suumo.fetch()
    by_id = {x.site_property_id: x for x in items}
    # 大溝２（芦原温泉駅）— 対象駅ではないので徒歩分数は付かない
    it = by_id.get("chukoikkodate-nc79107600")
    assert it is not None
    assert it.station_walk_minutes is None


def test_suumo_new_and_price_flags(suumo):
    items = suumo.fetch()
    assert any(x.site_new_flag for x in items)
    assert any(x.site_price_updated_flag for x in items)


def test_suumo_rent_filters_out_apartments(suumo):
    items = suumo.fetch()
    rent = [x for x in items if x.deal_type == "rent"]
    # あわら市の SUUMO 賃貸は現状すべて賃貸アパート/マンション → 戸建てゼロ
    assert rent == []
