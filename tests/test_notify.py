from __future__ import annotations

from awara_monitor import distance
from awara_monitor.models import ScrapedListing
from awara_monitor.notify import DiscordNotifier, man
from awara_monitor.pipeline import NewPropertyEvent, PriceChangeEvent


class FakeGeo:
    def geocode(self, address):
        return None


def _listing(**kw) -> ScrapedListing:
    base = dict(source="suumo", site_property_id="nc1", url="https://suumo.jp/x/",
                deal_type="sale", price=1_800_000, layout="5DK",
                address="福井県あわら市二面1-2-3", town="二面",
                land_area=250.0, building_area=110.0, built_year=1978,
                station_walk_minutes=11, station_walk_text="あわら湯のまち駅 徒歩11分")
    base.update(kw)
    return ScrapedListing(**base)


def test_man_formatting():
    assert man(1_800_000) == "180万円"
    assert man(1_990_000) == "199万円"
    assert man(500_000) == "50万円"
    assert man(1_785_000) == "178.5万円"
    assert man(None) == "価格応相談"


def test_new_property_payload_dry_run():
    n = DiscordNotifier(webhook_url="", dry_run=True)
    lst = _listing()
    dist = distance.evaluate(lst, FakeGeo())
    ev = NewPropertyEvent(1, lst, dist, ["suumo", "awara"], ["https://suumo.jp/x/", "https://a/y"])
    n.send_new_property(ev)
    desc = n.sent[0]["embeds"][0]["description"]
    assert n.sent[0]["embeds"][0]["title"] == "🚨 新着物件"
    assert "【売買】" in desc
    assert "価格：180万円" in desc
    assert "5DK" in desc
    assert "土地：250㎡" in desc
    assert "建物：110㎡" in desc
    assert "築：1978年" in desc
    assert "徒歩11分" in desc
    assert "SUUMO" in desc and "あわら市空き家バンク" in desc
    assert "https://suumo.jp/x/" in desc


def test_price_band_highlight_color():
    n = DiscordNotifier(webhook_url="", dry_run=True)
    for price, expect in [(900_000, "100万円以下"), (1_400_000, "150万円以下"),
                          (1_900_000, "200万円以下"), (2_400_000, "250万円以下")]:
        lst = _listing(price=price)
        dist = distance.evaluate(lst, FakeGeo())
        n.send_new_property(NewPropertyEvent(1, lst, dist, ["suumo"], ["u"]))
        assert expect in n.sent[-1]["embeds"][0]["description"]


def test_price_change_payload_shows_markdown_down():
    n = DiscordNotifier(webhook_url="", dry_run=True)
    lst = _listing(price=2_500_000)
    dist = distance.evaluate(lst, FakeGeo())
    ev = PriceChangeEvent(1, lst, dist, old_price=3_000_000, new_price=2_500_000,
                          sites=["suumo"], urls=["https://suumo.jp/x/"])
    n.send_price_change(ev)
    desc = n.sent[0]["embeds"][0]["description"]
    assert n.sent[0]["embeds"][0]["title"] == "💰 価格変更"
    assert "旧価格：300万円" in desc
    assert "新価格：250万円" in desc
    assert "値下げ" in desc
    assert "🎯" in desc  # 3,000,000 は上限超 → 2,500,000 で条件価格以下に


def test_price_change_rent():
    n = DiscordNotifier(webhook_url="", dry_run=True)
    lst = _listing(deal_type="rent", price=50_000, layout="3DK")
    dist = distance.evaluate(lst, FakeGeo())
    ev = PriceChangeEvent(1, lst, dist, old_price=55_000, new_price=50_000,
                          sites=["suumo"], urls=["u"])
    n.send_price_change(ev)
    desc = n.sent[0]["embeds"][0]["description"]
    assert "【賃貸】" in desc
    assert "55,000円" in desc and "50,000円" in desc


def test_error_payload():
    n = DiscordNotifier(webhook_url="", dry_run=True)
    n.send_error("suumo", "HTTP 403")
    desc = n.sent[0]["embeds"][0]["description"]
    assert "SUUMO" in desc
    assert "403" in desc
