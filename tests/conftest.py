from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

from awara_monitor.database import Database  # noqa: E402


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def db() -> Database:
    d = Database(":memory:")
    d.init_schema()
    yield d
    d.close()


class FakeGeocoder:
    """住所 → 座標 を固定辞書で返すテスト用ジオコーダ。"""

    def __init__(self, table: dict[str, tuple[float, float]] | None = None) -> None:
        # 既定: あわら市中心部の座標をいくつか
        self.table = {
            "福井県あわら市二面": (36.2216, 136.2050),
            "福井県あわら市舟津": (36.2225, 136.2010),
            "福井県あわら市温泉": (36.2239, 136.1939),
            "福井県あわら市春宮": (36.2140, 136.2210),
            "福井県あわら市自由ケ丘": (36.2090, 136.2360),
            "福井県あわら市波松": (36.2760, 136.1450),
        }
        if table:
            self.table.update(table)
        self.calls: list[str] = []

    def geocode(self, address: str):
        self.calls.append(address)
        if not address:
            return None
        for key, val in self.table.items():
            if key in address or address in key:
                return val
        # 町名だけ抜き出して再照合
        from awara_monitor import normalize

        town = normalize.extract_town(address)
        for key, val in self.table.items():
            if town and town in key:
                return val
        return None


@pytest.fixture
def fake_geocoder() -> FakeGeocoder:
    return FakeGeocoder()
