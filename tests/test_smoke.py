"""import / 基本動作のスモークテスト。"""
from __future__ import annotations

import importlib

import pytest

MODULES = [
    "awara_monitor",
    "awara_monitor.config",
    "awara_monitor.models",
    "awara_monitor.normalize",
    "awara_monitor.http_client",
    "awara_monitor.geocode",
    "awara_monitor.distance",
    "awara_monitor.database",
    "awara_monitor.dedup",
    "awara_monitor.pipeline",
    "awara_monitor.notify",
    "awara_monitor.runner",
    "scrapers",
    "scrapers.base",
    "scrapers.awara",
    "scrapers.suumo",
    "scrapers.athome",
    "scrapers.homes",
]


@pytest.mark.parametrize("name", MODULES)
def test_import(name):
    importlib.import_module(name)


def test_db_schema_creates(db):
    stats = db.stats()
    assert stats["properties_total"] == 0


def test_disabled_scrapers_raise():
    from scrapers.athome import AtHomeScraper
    from scrapers.homes import HomesScraper
    from scrapers.base import ScraperDisabled

    for cls in (AtHomeScraper, HomesScraper):
        with pytest.raises(ScraperDisabled):
            cls(None, None).fetch()


def test_build_scrapers_default():
    from awara_monitor import config
    from scrapers import build_scrapers

    scrapers = build_scrapers(list(config.ENABLED_SOURCES), None, None)
    assert [s.name for s in scrapers] == ["awara", "suumo"]
