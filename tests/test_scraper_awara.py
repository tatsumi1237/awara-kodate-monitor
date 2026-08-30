from __future__ import annotations

import pytest

from awara_monitor import config
from scrapers.awara import AwaraScraper

from .conftest import fixture_bytes


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.status_code = 200


class FakeSession:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get(self, url: str, **kw) -> FakeResponse:
        self.requested.append(url)
        if url.lower().endswith(".pdf"):
            raise AssertionError("テストでは PDF を取得しない想定")
        return FakeResponse(fixture_bytes("awara_bank.html"))


class AllowGate:
    def allowed(self, url: str) -> bool:
        return True

    def require(self, url: str) -> None:
        return None


@pytest.fixture
def awara(monkeypatch):
    # PDF 補完を無効化（一覧テーブルのパースだけ検証）
    monkeypatch.setattr(config, "MAX_DETAIL_FETCHES_PER_SITE", 0)
    return AwaraScraper(FakeSession(), AllowGate())


def test_awara_parses_table(awara):
    items = awara.fetch()
    assert len(items) >= 30

    by_code = {x.site_property_id: x for x in items}

    # 舟津・売買・90万円・5DK（コード 2501-1-2）
    assert "2501-1-2" in by_code
    funatsu = by_code["2501-1-2"]
    assert funatsu.deal_type == "sale"
    assert funatsu.price == 900_000
    assert funatsu.town == "舟津"
    assert funatsu.layout == "5DK"
    assert funatsu.address == "福井県あわら市舟津"

    # 河間・賃貸・4万5千円/月（コード 2409-1）
    assert "2409-1" in by_code
    kawama = by_code["2409-1"]
    assert kawama.deal_type == "rent"
    assert kawama.price == 45_000


def test_awara_all_have_codes_and_prices(awara):
    items = awara.fetch()
    assert all(x.site_property_id for x in items)
    # 価格は解析できているものが大半
    priced = [x for x in items if x.price is not None]
    assert len(priced) >= len(items) - 3


def test_awara_source_name(awara):
    items = awara.fetch()
    assert {x.source for x in items} == {"awara"}
