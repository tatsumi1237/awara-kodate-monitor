"""サイト別スクレイパー.

各サイトの取得処理は独立したモジュールにする。HTML 構造が変わったら
そのサイトのモジュールだけ修正すればよい。
"""
from __future__ import annotations

from awara_monitor.http_client import PoliteSession, RobotsGate

from .athome import AtHomeScraper
from .awara import AwaraScraper
from .base import (
    AccessBlockedError,
    BaseScraper,
    ScrapeError,
    ScraperDisabled,
)
from .homes import HomesScraper
from .suumo import SuumoScraper

SCRAPER_CLASSES: dict[str, type[BaseScraper]] = {
    "awara": AwaraScraper,
    "suumo": SuumoScraper,
    "athome": AtHomeScraper,
    "homes": HomesScraper,
}

__all__ = [
    "SCRAPER_CLASSES",
    "build_scrapers",
    "BaseScraper",
    "ScrapeError",
    "AccessBlockedError",
    "ScraperDisabled",
]


def build_scrapers(
    names: list[str], session: PoliteSession, gate: RobotsGate
) -> list[BaseScraper]:
    scrapers: list[BaseScraper] = []
    for name in names:
        cls = SCRAPER_CLASSES.get(name)
        if cls is None:
            raise KeyError(f"未知のスクレイパー: {name}")
        scrapers.append(cls(session, gate))
    return scrapers
