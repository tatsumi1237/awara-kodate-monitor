"""「あわら湯のまち駅」までの距離判定."""
from __future__ import annotations

import logging
import math
from typing import Optional

from . import config, normalize
from .models import DistanceResult, ScrapedListing

log = logging.getLogger(__name__)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の大円距離（メートル）。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def evaluate(listing: ScrapedListing, geocoder) -> DistanceResult:
    """物件の距離判定を返す。

    優先順:
      1. 物件ページに「あわら湯のまち駅 徒歩N分」等がある → それを使う
      2. 住所をジオコーディング → 直線距離 × 補正係数 で徒歩距離を近似
      3. 駅至近の町名リストに一致 → 「要確認」
      4. あわら市内だが住所不明 → 「要確認」
      5. それ以外 → 対象エリア外
    """
    mpm = config.WALK_METERS_PER_MINUTE

    # 1. ページ記載の徒歩分数
    if listing.station_walk_minutes is not None:
        minutes = listing.station_walk_minutes
        dist_m = minutes * mpm
        conf = "ok" if minutes <= config.MAX_WALK_MINUTES else "out"
        return DistanceResult(
            distance_m=dist_m,
            walk_minutes=minutes,
            method="page_walk",
            confidence=conf,
            note=listing.station_walk_text or "物件ページの徒歩分数",
        )

    # 2. ジオコーディング
    query = listing.address or (f"福井県あわら市{listing.town}" if listing.town else "")
    latlon = geocoder.geocode(query) if query else None
    if latlon:
        straight = haversine_m(latlon[0], latlon[1], config.STATION_LAT, config.STATION_LON)
        walk_m = straight * config.DETOUR_FACTOR
        minutes = max(1, round(walk_m / mpm))
        town_only = not normalize.has_banchi(listing.address)
        if walk_m <= config.TARGET_DISTANCE_M:
            conf = "uncertain" if town_only else "ok"
        elif walk_m <= config.UNCERTAIN_DISTANCE_M:
            conf = "uncertain"
        else:
            conf = "out"
        return DistanceResult(
            distance_m=int(round(walk_m)),
            walk_minutes=minutes,
            method="geocode_town" if town_only else "geocode",
            confidence=conf,
            note="住所から推定（直線距離×%.1f）" % config.DETOUR_FACTOR,
        )

    # 3. 駅至近の町名
    town = listing.town or normalize.extract_town(listing.address)
    if town and any(t in town for t in config.NEAR_STATION_TOWNS):
        return DistanceResult(
            distance_m=None,
            walk_minutes=None,
            method="town_list",
            confidence="uncertain",
            note=f"駅至近の町名（{town}）／距離未算出",
        )

    # 4. あわら市内だが不明
    blob = f"{listing.address} {listing.town}"
    if "あわら" in blob or town:
        return DistanceResult(
            distance_m=None,
            walk_minutes=None,
            method="unknown",
            confidence="uncertain",
            note="住所から距離を判定できませんでした",
        )

    # 5. 対象外
    return DistanceResult(
        distance_m=None,
        walk_minutes=None,
        method="unknown",
        confidence="out",
        note="対象エリア外",
    )
