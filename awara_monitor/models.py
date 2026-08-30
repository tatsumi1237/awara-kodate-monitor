"""データモデル."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Optional


def now_iso() -> str:
    """ローカルタイムゾーン付きの ISO8601 文字列（秒精度）。"""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def today_str() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y/%m/%d")


@dataclass
class ScrapedListing:
    """1サイトから取得した1掲載分の生データ。"""

    source: str  # 'awara' | 'suumo'
    site_property_id: str  # サイト内で安定した ID
    url: str
    deal_type: str  # 'sale' | 'rent'
    price: Optional[int] = None  # 円（賃貸は月額）
    title: str = ""
    property_type_raw: str = ""
    address: str = ""
    town: str = ""
    layout: str = ""
    land_area: Optional[float] = None  # m^2
    building_area: Optional[float] = None  # m^2
    built_year: Optional[int] = None  # 西暦
    station_line: str = ""
    station_walk_text: str = ""
    station_walk_minutes: Optional[int] = None  # 対象駅までの徒歩分（判明時のみ）
    site_new_flag: bool = False
    site_price_updated_flag: bool = False
    extra: dict = field(default_factory=dict)

    def key(self) -> str:
        return f"{self.source}:{self.site_property_id}"

    def to_json_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        return d


@dataclass
class DistanceResult:
    """住所/駅表記から算出した「あわら湯のまち駅」までの距離判定。"""

    distance_m: Optional[int]
    walk_minutes: Optional[int]
    method: str  # page_walk | page_meters | geocode | geocode_town | town_list | unknown
    confidence: str  # ok | uncertain | out
    note: str = ""

    METHOD_LABELS = {
        "page_walk": "物件ページの徒歩分数",
        "page_meters": "物件ページの距離表記",
        "geocode": "住所ジオコーディング（直線距離補正）",
        "geocode_town": "町名ジオコーディング（直線距離補正）",
        "town_list": "駅至近の町名リスト",
        "unknown": "判定不可",
    }

    @property
    def is_target(self) -> bool:
        return self.confidence in ("ok", "uncertain")

    @property
    def needs_review(self) -> bool:
        return self.confidence == "uncertain"

    def display(self) -> str:
        """Discord 表示用の1行テキスト。"""
        from . import config

        if self.confidence == "out":
            return f"{config.STATION_NAME}：対象エリア外"
        if self.method == "page_walk" and self.walk_minutes is not None:
            base = f"{config.STATION_NAME}：徒歩{self.walk_minutes}分"
        elif self.distance_m is not None:
            base = f"{config.STATION_NAME}：約{self.distance_m}m"
            if self.walk_minutes:
                base += f"（徒歩約{self.walk_minutes}分）"
        else:
            base = f"{config.STATION_NAME}：距離未算出"
        if self.needs_review:
            base += "  ⚠️ 距離判定：要確認"
        return base
