"""SUUMO スクレイパー.

対象 URL（いずれも robots.txt で許可されているパス。2026-08 時点で確認）:
  - 中古一戸建て : https://suumo.jp/chukoikkodate/fukui/sc_awara/
  - 新築一戸建て : https://suumo.jp/ikkodate/fukui/sc_awara/
  - 賃貸         : https://suumo.jp/chintai/fukui/sc_awara/ （一戸建て/テラスハウスのみ採用）

利用規約(https://suumo.jp/edit/kiyaku/)にクローラー禁止の明示条項はないが、
「サイト運営を妨げる行為」の禁止に配慮し、1日1回・待機付き・最小ページのみ取得する。
RSS 配信ページ(/jj/bukken/ichiran/JJ012FC001/...)は robots.txt で Disallow のため使わない。
"""
from __future__ import annotations

import re
import urllib.parse

from bs4 import BeautifulSoup

from awara_monitor import config, normalize
from awara_monitor.models import ScrapedListing

from .base import AccessBlockedError, BaseScraper, ScrapeError

BASE = "https://suumo.jp"
SALE_URLS = [
    "https://suumo.jp/chukoikkodate/fukui/sc_awara/",
    "https://suumo.jp/ikkodate/fukui/sc_awara/",
]
RENT_URL = "https://suumo.jp/chintai/fukui/sc_awara/"

RENT_HOUSE_LABELS = ("一戸建て", "テラスハウス", "タウンハウス", "戸建")

_NC_RE = re.compile(r"/nc_(\d+)/")
_JNC_RE = re.compile(r"/(jnc_\d+)/")


class SuumoScraper(BaseScraper):
    name = "suumo"
    label = "SUUMO"

    def fetch(self) -> list[ScrapedListing]:
        listings: list[ScrapedListing] = []
        errors: list[str] = []

        for url in SALE_URLS:
            try:
                listings.extend(self._fetch_sale(url))
            except AccessBlockedError:
                raise
            except ScrapeError as exc:
                errors.append(f"{url}: {exc}")
                self.log.warning("売買一覧の取得に失敗: %s", exc)

        try:
            listings.extend(self._fetch_rent(RENT_URL))
        except AccessBlockedError:
            raise
        except ScrapeError as exc:
            errors.append(f"{RENT_URL}: {exc}")
            self.log.warning("賃貸一覧の取得に失敗: %s", exc)

        if not listings and errors:
            raise ScrapeError("; ".join(errors))
        return listings

    # -- 売買（中古 / 新築 一戸建て）------------------------------------------
    def _fetch_sale(self, first_url: str) -> list[ScrapedListing]:
        out: list[ScrapedListing] = []
        url = first_url
        for _ in range(config.MAX_LIST_PAGES):
            self.gate.require(url)
            soup = BeautifulSoup(self.session.get(url).content, "html.parser")
            units = soup.select("#js-bukkenList .property_unit")
            for unit in units:
                item = self._parse_sale_unit(unit, first_url)
                if item:
                    out.append(item)
            nxt = self._next_page(soup, url)
            if not nxt:
                break
            url = nxt
        return out

    def _parse_sale_unit(self, unit, list_url: str) -> ScrapedListing | None:
        a = unit.select_one(".property_unit-title a") or unit.select_one("h2 a")
        if not a or not a.get("href"):
            return None
        href = a["href"]
        # 一戸建ての一覧に混ざる「建築条件付土地」等（/tochi/ へのリンク）は除外
        if "/chukoikkodate/" not in href and "/ikkodate/" not in href:
            return None
        m = _NC_RE.search(href)
        if not m:
            return None
        prop_id = m.group(1)
        title = a.get_text(strip=True)
        detail_url = urllib.parse.urljoin(BASE, href.split("?")[0])

        # 物件種別ラベル（「建築条件付土地」「中古一戸建て」等）
        pcts = " ".join(
            s.get_text(strip=True)
            for s in unit.select(".property_unit-header .property_unit-pcts .ui-pct, .property_unit-header .property_unit-pcts li")
        )

        fields: dict[str, str] = {}
        for dl in unit.select(".property_unit-info dl, .dottable dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            if not dt or not dd:
                continue
            key = dt.get_text(strip=True)
            fields[key] = dd.get_text("\n", strip=True)

        price_text = fields.get("販売価格") or fields.get("価格") or ""
        address = fields.get("所在地", "")
        station_text = fields.get("沿線・駅", "") or fields.get("交通", "")

        labels = " ".join(s.get_text(strip=True) for s in unit.select(".ui-label"))

        walk_min, walk_txt = normalize.parse_walk_minutes(
            station_text.split("\n"), config.STATION_ALIASES, config.WALK_METERS_PER_MINUTE
        )

        kind = "chukoikkodate" if "chukoikkodate" in list_url else "ikkodate"
        return ScrapedListing(
            source=self.name,
            site_property_id=f"{kind}-nc{prop_id}",
            url=detail_url,
            deal_type="sale",
            price=normalize.parse_price_yen(price_text, "sale"),
            title=title,
            property_type_raw=(
                ("中古一戸建て" if kind == "chukoikkodate" else "新築一戸建て")
                + (f" {pcts}" if pcts else "")
            ),
            address=address,
            town=normalize.extract_town(address),
            layout=normalize.parse_layout(fields.get("間取り", "")),
            land_area=normalize.parse_area_m2(fields.get("土地面積", "")),
            building_area=normalize.parse_area_m2(fields.get("建物面積", "")),
            built_year=normalize.parse_built_year(fields.get("築年月", "") or fields.get("完成時期（築年月）", "")),
            station_line=station_text.split("\n")[0] if station_text else "",
            station_walk_text=walk_txt or station_text.replace("\n", " ")[:120],
            station_walk_minutes=walk_min,
            site_new_flag="新着" in labels,
            site_price_updated_flag="価格更新" in labels,
            extra={"raw_fields": fields, "labels": labels},
        )

    # -- 賃貸（一戸建て / テラスハウスのみ）-----------------------------------
    def _fetch_rent(self, first_url: str) -> list[ScrapedListing]:
        out: list[ScrapedListing] = []
        url = first_url
        for _ in range(config.MAX_LIST_PAGES):
            self.gate.require(url)
            soup = BeautifulSoup(self.session.get(url).content, "html.parser")
            for building in soup.select(".l-cassetteitem .cassetteitem, .cassetteitem"):
                out.extend(self._parse_rent_building(building))
            nxt = self._next_page(soup, url)
            if not nxt:
                break
            url = nxt
        return out

    def _parse_rent_building(self, building) -> list[ScrapedListing]:
        label_el = building.select_one(".cassetteitem_content-label")
        btype = label_el.get_text(strip=True) if label_el else ""
        if not any(k in btype for k in RENT_HOUSE_LABELS):
            return []

        title_el = building.select_one(".cassetteitem_content-title")
        title = title_el.get_text(strip=True) if title_el else ""
        addr_el = building.select_one(".cassetteitem_detail-col1")
        address = addr_el.get_text(strip=True) if addr_el else ""
        station_lines = [
            e.get_text(strip=True)
            for e in building.select(".cassetteitem_detail-col2 .cassetteitem_detail-text")
            if e.get_text(strip=True)
        ]
        col3 = building.select_one(".cassetteitem_detail-col3")
        built_year = normalize.parse_built_year(col3.get_text(" ", strip=True) if col3 else "")

        walk_min, walk_txt = normalize.parse_walk_minutes(
            station_lines, config.STATION_ALIASES, config.WALK_METERS_PER_MINUTE
        )
        town = normalize.extract_town(address)

        results: list[ScrapedListing] = []
        for row in building.select("table.cassetteitem_other tr"):
            link = row.select_one("a.js-cassette_link_href")
            if not link or not link.get("href"):
                continue
            m = _JNC_RE.search(link["href"])
            if not m:
                continue
            jnc = m.group(1)
            rent_el = row.select_one(".cassetteitem_price--rent")
            madori_el = row.select_one(".cassetteitem_madori")
            menseki_el = row.select_one(".cassetteitem_menseki")
            price = normalize.parse_price_yen(
                rent_el.get_text(strip=True) if rent_el else "", "rent"
            )
            is_new = bool(row.select_one(".cassetteitem_other-checkbox--newarrival"))
            results.append(
                ScrapedListing(
                    source=self.name,
                    site_property_id=f"chintai-{jnc}",
                    url=urllib.parse.urljoin(BASE, link["href"].split("?")[0]),
                    deal_type="rent",
                    price=price,
                    title=title,
                    property_type_raw=btype,
                    address=address,
                    town=town,
                    layout=normalize.parse_layout(madori_el.get_text(strip=True) if madori_el else ""),
                    land_area=None,
                    building_area=normalize.parse_area_m2(
                        menseki_el.get_text(strip=True) if menseki_el else ""
                    ),
                    built_year=built_year,
                    station_line=station_lines[0] if station_lines else "",
                    station_walk_text=walk_txt or " / ".join(station_lines)[:120],
                    station_walk_minutes=walk_min,
                    site_new_flag=is_new,
                    extra={"stations": station_lines},
                )
            )
        return results

    # -- pagination ---------------------------------------------------------
    @staticmethod
    def _next_page(soup, current_url: str) -> str | None:
        for a in soup.select(".pagination-parts a, .pagination_set-nav a"):
            txt = a.get_text(strip=True)
            if txt in ("次へ", "次の30件", ">"):
                return urllib.parse.urljoin(current_url, a.get("href", ""))
        return None
