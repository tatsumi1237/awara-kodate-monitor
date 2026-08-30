"""新着判定・価格変更判定・重複統合の統合テスト（モックデータ使用）。"""
from __future__ import annotations

import copy

from awara_monitor import pipeline
from awara_monitor.models import ScrapedListing


def L(**kw) -> ScrapedListing:
    base = dict(source="suumo", site_property_id="x", url="http://ex/x",
                deal_type="sale", price=1_000_000)
    base.update(kw)
    return ScrapedListing(**base)


# -- モックデータ -----------------------------------------------------------
def run1_data():
    A = L(source="suumo", site_property_id="nc1", url="http://suumo/nc1",
          price=1_800_000, title="二面の中古住宅", address="福井県あわら市二面1-2-3",
          town="二面", layout="5DK", land_area=250.0, building_area=110.0,
          built_year=1978, station_walk_minutes=12,
          station_walk_text="あわら湯のまち駅 徒歩12分")
    B = L(source="suumo", site_property_id="nc2", url="http://suumo/nc2",
          price=30_000_000, title="春宮の新築", address="福井県あわら市春宮3-1-1",
          town="春宮", layout="4LDK")
    C = L(source="awara", site_property_id="2501-1-2", url="http://awara/2501-1-2.pdf",
          price=900_000, title="空き家バンク 2501-1-2（舟津）",
          property_type_raw="一戸建て(空き家バンク)", address="福井県あわら市舟津",
          town="舟津", layout="4DK")
    D = L(source="suumo", site_property_id="nc3", url="http://suumo/nc3",
          price=900_000, title="舟津の中古住宅", address="福井県あわら市舟津",
          town="舟津", layout="4DK")
    return {"awara": [C], "suumo": [A, B, D]}


def run2_data(base):
    d = copy.deepcopy(base)
    # A 値下げ
    for x in d["suumo"]:
        if x.site_property_id == "nc1":
            x.price = 1_500_000
    # D は掲載終了（削除）
    d["suumo"] = [x for x in d["suumo"] if x.site_property_id != "nc3"]
    # E 新着
    E = L(source="awara", site_property_id="2601-9", url="http://awara/2601-9.pdf",
          price=2_000_000, title="空き家バンク 2601-9（温泉）",
          property_type_raw="一戸建て(空き家バンク)", address="福井県あわら市温泉1-1",
          town="温泉", layout="6DK")
    d["awara"].append(E)
    return d


def _record(db, result):
    """runner 相当: 送信済みとして通知を記録する。"""
    for ev in result.new_properties:
        db.record_notification("new", str(ev.internal_id))
    for ev in result.price_changes:
        db.record_notification("price_change", f"{ev.internal_id}:{ev.old_price}->{ev.new_price}")


# -- テスト -----------------------------------------------------------
def test_run1_detects_new_and_merges_duplicate(db, fake_geocoder):
    data = run1_data()
    result = pipeline.run(db, data, {"awara", "suumo"}, fake_geocoder)

    # A（二面）と C（舟津）が新着。B は価格超過で通知対象外。D は C と統合。
    ids = {ev.listing.site_property_id for ev in result.new_properties}
    assert ids == {"nc1", "2501-1-2"}
    assert result.dedup_merges == 1
    assert len(result.price_changes) == 0

    # C の property に awara と suumo の2サイトが紐づく
    stats = db.stats()
    assert stats["properties_active"] == 3  # A, B, C（D は C に統合）
    assert stats["listings_active"] == 4    # A, B, C, D


def test_no_duplicate_notification_on_rerun(db, fake_geocoder):
    data = run1_data()
    r1 = pipeline.run(db, data, {"awara", "suumo"}, fake_geocoder)
    _record(db, r1)
    r2 = pipeline.run(db, run1_data(), {"awara", "suumo"}, fake_geocoder)
    assert len(r2.new_properties) == 0
    assert len(r2.price_changes) == 0


def test_run2_price_drop_and_new_and_delist(db, fake_geocoder):
    r1 = pipeline.run(db, run1_data(), {"awara", "suumo"}, fake_geocoder)
    _record(db, r1)

    r2 = pipeline.run(db, run2_data(run1_data()), {"awara", "suumo"}, fake_geocoder)

    # 価格変更（A: 180万 → 150万 の値下げ）
    assert len(r2.price_changes) == 1
    pc = r2.price_changes[0]
    assert pc.direction == "down"
    assert (pc.old_price, pc.new_price) == (1_800_000, 1_500_000)

    # 新着（E: 温泉）
    new_ids = {ev.listing.site_property_id for ev in r2.new_properties}
    assert new_ids == {"2601-9"}

    # D は掲載終了。ただし C の property は awara 掲載が残るので active のまま
    hist = db.conn.execute("SELECT * FROM listings WHERE site_property_id='nc3'").fetchone()
    assert hist["status"] == "delisted"
    c_prop = db.conn.execute(
        "SELECT p.status FROM properties p JOIN listings l ON l.internal_id=p.internal_id "
        "WHERE l.site_property_id='2501-1-2'"
    ).fetchone()
    assert c_prop["status"] == "active"

    # 価格履歴が残っている
    ph = db.conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    assert ph == 1


def test_delist_skipped_for_failed_source(db, fake_geocoder):
    pipeline.run(db, run1_data(), {"awara", "suumo"}, fake_geocoder)
    # suumo が失敗した実行: suumo の掲載を delisted にしてはいけない
    pipeline.run(db, {"awara": run1_data()["awara"]}, {"awara"}, fake_geocoder)
    a = db.conn.execute("SELECT status FROM listings WHERE site_property_id='nc1'").fetchone()
    assert a["status"] == "active"
