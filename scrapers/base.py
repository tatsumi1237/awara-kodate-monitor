"""スクレイパーの基底クラス.

各サイトの取得処理は個別モジュール(awara.py / suumo.py / ...)に分離する。
サイトの HTML 構造が変わっても、そのサイトのモジュールだけ直せば済むようにする。
"""
from __future__ import annotations

import logging

from awara_monitor.http_client import (  # re-export
    AccessBlockedError,
    PoliteSession,
    RobotsGate,
    ScrapeError,
    ScraperDisabled,
)
from awara_monitor.models import ScrapedListing

__all__ = [
    "BaseScraper",
    "ScrapeError",
    "AccessBlockedError",
    "ScraperDisabled",
    "ScrapedListing",
]


class BaseScraper:
    #: 監視元の識別子（DB の source カラムと一致させる）
    name: str = "base"
    #: 表示名
    label: str = "base"
    #: False の場合、fetch() は ScraperDisabled を送出すべき
    enabled: bool = True

    def __init__(self, session: PoliteSession, gate: RobotsGate) -> None:
        self.session = session
        self.gate = gate
        self.log = logging.getLogger(f"scraper.{self.name}")

    def fetch(self) -> list[ScrapedListing]:
        raise NotImplementedError
