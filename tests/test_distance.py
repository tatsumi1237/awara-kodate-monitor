from __future__ import annotations

from awara_monitor import distance
from awara_monitor.models import ScrapedListing


class NullGeocoder:
    def geocode(self, address):
        return None


def _listing(**kw) -> ScrapedListing:
    base = dict(
        source="suumo",
        site_property_id="x",
        url="http://example.com",
        deal_type="sale",
        price=1_000_000,
    )
    base.update(kw)
    return ScrapedListing(**base)


def test_haversine_zero():
    assert distance.haversine_m(36.0, 136.0, 36.0, 136.0) == 0


def test_page_walk_within_limit(fake_geocoder):
    r = distance.evaluate(_listing(station_walk_minutes=14, station_walk_text="あわら湯のまち 徒歩14分"), fake_geocoder)
    assert r.method == "page_walk"
    assert r.confidence == "ok"
    assert r.walk_minutes == 14


def test_page_walk_over_limit(fake_geocoder):
    r = distance.evaluate(_listing(station_walk_minutes=22), fake_geocoder)
    assert r.confidence == "out"


def test_geocode_full_address_ok(fake_geocoder):
    r = distance.evaluate(_listing(address="福井県あわら市温泉1-2-3", town="温泉"), fake_geocoder)
    assert r.method == "geocode"
    assert r.confidence == "ok"
    assert r.distance_m is not None and r.distance_m < 1200


def test_geocode_town_only_is_uncertain(fake_geocoder):
    r = distance.evaluate(_listing(address="福井県あわら市二面", town="二面"), fake_geocoder)
    assert r.method == "geocode_town"
    assert r.confidence == "uncertain"


def test_geocode_far_town_is_out(fake_geocoder):
    r = distance.evaluate(_listing(address="福井県あわら市波松", town="波松"), fake_geocoder)
    assert r.confidence == "out"


def test_town_list_fallback_uncertain():
    r = distance.evaluate(_listing(address="", town="舟津"), NullGeocoder())
    assert r.method == "town_list"
    assert r.confidence == "uncertain"
    assert r.needs_review


def test_unknown_in_awara_is_uncertain():
    r = distance.evaluate(_listing(address="あわら市どこか不明", town="不明町"), NullGeocoder())
    assert r.confidence == "uncertain"


def test_display_contains_review_flag(fake_geocoder):
    r = distance.evaluate(_listing(address="福井県あわら市二面", town="二面"), fake_geocoder)
    assert "要確認" in r.display()
