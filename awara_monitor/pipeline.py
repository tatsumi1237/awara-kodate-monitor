"""1回の監視実行の中心ロジック.

- スクレイプ結果を正規化して SQLite に反映
- 新着物件の判定（サイトの「新着」表示ではなく、DB との差分で判定）
- 価格変更の判定（値下げ・値上げ・条件価格跨ぎ）
- 重複物件の統合
- 条件フィルタ（種別・価格・距離）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from . import config, dedup, distance, normalize
from .database import Database
from .models import DistanceResult, ScrapedListing

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 実行結果（通知はこのイベントを元に main が送る）
# --------------------------------------------------------------------------
@dataclass
class NewPropertyEvent:
    internal_id: int
    listing: ScrapedListing
    dist: DistanceResult
    sites: list[str]
    urls: list[str]
    merged_from_other_site: bool = False
    is_relist: bool = False

    def dedup_key(self) -> str:
        if self.is_relist:
            return f"relist:{self.internal_id}:{self.listing.price}"
        return str(self.internal_id)


@dataclass
class PriceChangeEvent:
    internal_id: int
    listing: ScrapedListing
    dist: DistanceResult
    old_price: int
    new_price: int
    sites: list[str]
    urls: list[str]

    @property
    def direction(self) -> str:
        return "down" if self.new_price < self.old_price else "up"


@dataclass
class RunResult:
    new_properties: list[NewPropertyEvent] = field(default_factory=list)
    price_changes: list[PriceChangeEvent] = field(default_factory=list)
    delisted_internal_ids: list[int] = field(default_factory=list)
    processed: int = 0
    skipped_excluded: int = 0
    skipped_out_of_area: int = 0
    dedup_merges: int = 0
    dedup_candidates: int = 0

    def summary(self) -> dict:
        return {
            "new_properties": len(self.new_properties),
            "price_changes": len(self.price_changes),
            "delisted": len(self.delisted_internal_ids),
            "processed": self.processed,
            "skipped_excluded": self.skipped_excluded,
            "skipped_out_of_area": self.skipped_out_of_area,
            "dedup_merges": self.dedup_merges,
            "dedup_candidates": self.dedup_candidates,
        }


# --------------------------------------------------------------------------
def _price_limit(deal_type: str) -> int:
    return config.SALE_MAX_PRICE if deal_type == "sale" else config.RENT_MAX_PRICE


def _passes_notify(listing: ScrapedListing, dist: DistanceResult) -> bool:
    """通知対象か（種別は呼び出し前にフィルタ済みの前提）。"""
    if listing.price is None:
        return False
    if listing.price > _price_limit(listing.deal_type):
        return False
    return dist.is_target


def _signature_dict(listing: ScrapedListing, dist: DistanceResult) -> dict:
    return {
        "deal_type": listing.deal_type,
        "property_type": "一戸建て",
        "address": listing.address,
        "address_norm": normalize.normalize_address(listing.address),
        "town": listing.town or normalize.extract_town(listing.address),
        "layout": listing.layout,
        "land_area": listing.land_area,
        "building_area": listing.building_area,
        "built_year": listing.built_year,
        "station_name": config.STATION_NAME,
        "station_distance_m": dist.distance_m,
        "station_walk_minutes": dist.walk_minutes,
        "distance_method": dist.method,
        "distance_confidence": dist.confidence,
        "distance_note": dist.note,
        "current_price": listing.price,
    }


def _merge_missing_fields(prop_row, listing: ScrapedListing, dist: DistanceResult) -> dict:
    """既存 property に無い属性だけを埋める差分辞書を返す。"""
    updates: dict = {}
    mapping = {
        "address": listing.address,
        "town": listing.town or normalize.extract_town(listing.address),
        "layout": listing.layout,
        "land_area": listing.land_area,
        "building_area": listing.building_area,
        "built_year": listing.built_year,
    }
    for col, val in mapping.items():
        if val not in (None, "") and not prop_row[col]:
            updates[col] = val
    if not prop_row["address_norm"] and listing.address:
        updates["address_norm"] = normalize.normalize_address(listing.address)

    # 距離判定は「より確度の高い方法」に更新
    rank = {"page_walk": 4, "page_meters": 4, "geocode": 3, "geocode_town": 2,
            "town_list": 1, "unknown": 0}
    if rank.get(dist.method, 0) > rank.get(prop_row["distance_method"] or "", 0):
        updates["station_distance_m"] = dist.distance_m
        updates["station_walk_minutes"] = dist.walk_minutes
        updates["distance_method"] = dist.method
        updates["distance_confidence"] = dist.confidence
        updates["distance_note"] = dist.note
    return updates


def _sites_and_urls(db: Database, internal_id: int) -> tuple[list[str], list[str]]:
    rows = db.listings_for_property(internal_id)
    active = [r for r in rows if r["status"] == "active"] or rows
    seen: set[str] = set()
    sites: list[str] = []
    urls: list[str] = []
    for r in active:
        if r["source"] not in seen:
            seen.add(r["source"])
            sites.append(r["source"])
        if r["url"] and r["url"] not in urls:
            urls.append(r["url"])
    return sites, urls


# --------------------------------------------------------------------------
def run(
    db: Database,
    scraped_by_source: dict[str, list[ScrapedListing]],
    ok_sources: set[str],
    geocoder,
) -> RunResult:
    result = RunResult()
    seen_keys: set[str] = set()

    for source, listings in scraped_by_source.items():
        for listing in listings:
            seen_keys.add(listing.key())
            try:
                _process_one(db, listing, geocoder, result)
            except Exception:  # 1物件の失敗で全体を止めない
                log.exception("物件処理でエラー: %s", listing.key())

    # 掲載終了の検出（今回取得に成功したサイトのみ対象）
    affected = db.mark_missing_listings_delisted(ok_sources, seen_keys)
    for internal_id in set(affected):
        status = db.refresh_property_status(internal_id)
        if status == "delisted":
            result.delisted_internal_ids.append(internal_id)

    return result


def _process_one(db: Database, listing: ScrapedListing, geocoder, result: RunResult) -> None:
    # --- 種別フィルタ（一戸建て以外を除外）---
    # タイトルは宣伝文なので判定に使わない（誤除外を避ける）。
    hit = normalize.looks_excluded(
        listing.property_type_raw,
        listing.layout,
        listing.extra.get("note", ""),
        keywords=config.EXCLUDE_KEYWORDS,
    )
    if hit:
        result.skipped_excluded += 1
        log.info("除外(%s): %s / %s", hit, listing.key(), listing.title[:40])
        return

    result.processed += 1
    dist = distance.evaluate(listing, geocoder)
    if dist.confidence == "out":
        result.skipped_out_of_area += 1

    raw_json = json.dumps(listing.to_json_dict(), ensure_ascii=False, default=str)
    existing = db.find_listing(listing.source, listing.site_property_id)

    if existing is not None:
        _handle_existing(db, listing, dist, existing, raw_json, result)
    else:
        _handle_new_listing(db, listing, dist, raw_json, result)


def _handle_existing(db, listing, dist, existing, raw_json, result: RunResult) -> None:
    internal_id = existing["internal_id"]
    old_price = existing["price"]
    was_delisted = existing["status"] == "delisted"

    # 価格変更判定
    if (
        listing.price is not None
        and old_price is not None
        and listing.price != old_price
    ):
        db.insert_price_history(
            internal_id=internal_id,
            listing_id=existing["listing_id"],
            source=listing.source,
            old_price=old_price,
            new_price=listing.price,
        )
        db.set_property_price(internal_id, old_price, listing.price)
        if _passes_notify(listing, dist):
            key = f"{internal_id}:{old_price}->{listing.price}"
            if not db.was_notified("price_change", key):
                sites, urls = _sites_and_urls(db, internal_id)
                result.price_changes.append(
                    PriceChangeEvent(
                        internal_id=internal_id,
                        listing=listing,
                        dist=dist,
                        old_price=old_price,
                        new_price=listing.price,
                        sites=sites,
                        urls=urls,
                    )
                )

    db.update_listing_seen(existing["listing_id"], listing.price, raw_json)

    prop = db.get_property(internal_id)
    if prop is not None:
        updates = _merge_missing_fields(prop, listing, dist)
        updates["last_seen_at"] = _now()
        if listing.price is not None and prop["current_price"] is None:
            updates["current_price"] = listing.price
        db.update_property(internal_id, updates)

    # 一度掲載終了 → 再掲載された場合は「新着」として扱い直す
    if was_delisted:
        db.refresh_property_status(internal_id)
        if _passes_notify(listing, dist):
            key = f"relist:{internal_id}:{listing.price}"
            if not db.was_notified("new", key):
                sites, urls = _sites_and_urls(db, internal_id)
                result.new_properties.append(
                    NewPropertyEvent(internal_id, listing, dist, sites, urls, is_relist=True)
                )


def _handle_new_listing(db, listing, dist, raw_json, result: RunResult) -> None:
    sig = dedup.Signature(
        deal_type=listing.deal_type,
        address_norm=normalize.normalize_address(listing.address),
        town=listing.town or normalize.extract_town(listing.address),
        price=listing.price,
        layout=listing.layout,
        land_area=listing.land_area,
        building_area=listing.building_area,
        built_year=listing.built_year,
    )
    match = dedup.find_match(sig, db.active_properties())

    if match.is_merge:
        internal_id = match.internal_id
        db.insert_listing(
            internal_id=internal_id,
            source=listing.source,
            site_property_id=listing.site_property_id,
            url=listing.url,
            deal_type=listing.deal_type,
            price=listing.price,
            raw_json=raw_json,
        )
        result.dedup_merges += 1
        log.info(
            "統合: %s → property#%s (score=%.2f: %s)",
            listing.key(), internal_id, match.score, " / ".join(match.reasons),
        )
        prop = db.get_property(internal_id)
        updates = _merge_missing_fields(prop, listing, dist)
        sites, urls = _sites_and_urls(db, internal_id)
        updates["sites"] = json.dumps(sites, ensure_ascii=False)
        updates["urls"] = json.dumps(urls, ensure_ascii=False)
        updates["last_seen_at"] = _now()
        dinfo = _load_json(prop["dedup_info"]) or {}
        dinfo.setdefault("merged", []).append(
            {"key": listing.key(), "score": match.score, "reasons": match.reasons}
        )
        updates["dedup_info"] = json.dumps(dinfo, ensure_ascii=False)
        db.update_property(internal_id, updates)

        # 別サイトの掲載価格が既存より安く、条件を満たすなら価格変更として通知
        if (
            listing.price is not None
            and prop["current_price"] is not None
            and listing.price < prop["current_price"]
            and _passes_notify(listing, dist)
        ):
            key = f"{internal_id}:{prop['current_price']}->{listing.price}"
            if not db.was_notified("price_change", key):
                db.insert_price_history(
                    internal_id=internal_id, listing_id=None, source=listing.source,
                    old_price=prop["current_price"], new_price=listing.price,
                )
                db.set_property_price(internal_id, prop["current_price"], listing.price)
                result.price_changes.append(
                    PriceChangeEvent(
                        internal_id, listing, dist,
                        prop["current_price"], listing.price, sites, urls,
                    )
                )
        return

    # 新しい property を作る
    data = _signature_dict(listing, dist)
    data["sites"] = json.dumps([listing.source], ensure_ascii=False)
    data["urls"] = json.dumps([listing.url], ensure_ascii=False)
    data["previous_price"] = None
    data["current_price"] = listing.price
    if match.is_candidate:
        data["dedup_info"] = json.dumps(
            {"candidate_of": match.internal_id, "score": match.score, "reasons": match.reasons},
            ensure_ascii=False,
        )
    internal_id = db.insert_property(data)
    db.insert_listing(
        internal_id=internal_id,
        source=listing.source,
        site_property_id=listing.site_property_id,
        url=listing.url,
        deal_type=listing.deal_type,
        price=listing.price,
        raw_json=raw_json,
    )

    if match.is_candidate:
        db.insert_dedup_candidate(
            internal_id, match.internal_id, match.score, " / ".join(match.reasons)
        )
        result.dedup_candidates += 1
        log.info(
            "重複候補: %s ≈ property#%s (score=%.2f)",
            listing.key(), match.internal_id, match.score,
        )

    if _passes_notify(listing, dist):
        key = str(internal_id)
        if not db.was_notified("new", key):
            result.new_properties.append(
                NewPropertyEvent(
                    internal_id=internal_id,
                    listing=listing,
                    dist=dist,
                    sites=[listing.source],
                    urls=[listing.url],
                )
            )
    else:
        log.info(
            "DB登録のみ（通知対象外）: %s price=%s conf=%s",
            listing.key(), listing.price, dist.confidence,
        )


def _now() -> str:
    from .models import now_iso

    return now_iso()


def _load_json(text: Optional[str]):
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None
