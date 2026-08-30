"""あわら市 空き家情報バンク スクレイパー.

対象: あわら市公式サイトの物件一覧ページ（HTML テーブル）
  https://www.city.awara.lg.jp/mokuteki/life/jyutaku1/p001478.html

- robots.txt は存在しない（= 制限なし）。公的機関の公開情報。
- 一覧テーブルから 種別 / 所在(町名) / エリア / 価格 / 間取り / 備考 を取得。
- 面積・築年・詳細住所・駅距離は各物件の PDF にのみ記載 → 条件に合致しそうな
  物件だけ、1回の実行で最大数件の PDF を取得して補完する（負荷最小化）。
"""
from __future__ import annotations

import io
import re
import urllib.parse

from bs4 import BeautifulSoup

from awara_monitor import config, normalize
from awara_monitor.models import ScrapedListing

from .base import BaseScraper, ScrapeError

LIST_URL = "https://www.city.awara.lg.jp/mokuteki/life/jyutaku1/p001478.html"

_CODE_RE = re.compile(r"(\d{4}-[\d\-]+)")
_HEADER_TOKENS = {"種別", "物件所在", "エリア", "間取り", "価格"}


class AwaraScraper(BaseScraper):
    name = "awara"
    label = "あわら市空き家バンク"

    def fetch(self) -> list[ScrapedListing]:
        if not self.gate.allowed(LIST_URL):
            raise ScrapeError(f"robots.txt で許可されていません: {LIST_URL}")
        resp = self.session.get(LIST_URL)
        soup = BeautifulSoup(resp.content, "html.parser")

        table = self._find_table(soup)
        if table is None:
            raise ScrapeError("物件一覧テーブルが見つかりません（HTML構造の変更の可能性）")

        rows = self._parse_rows(table)
        self._enrich_with_pdfs(rows)
        return rows

    # -- テーブル探索 ---------------------------------------------------------
    @staticmethod
    def _find_table(soup):
        for table in soup.find_all("table"):
            caption = table.find("caption")
            if caption and "物件" in caption.get_text():
                return table
            head_text = table.get_text(" ", strip=True)[:120]
            if "種別" in head_text and "間取り" in head_text:
                return table
        return None

    def _parse_rows(self, table) -> list[ScrapedListing]:
        out: list[ScrapedListing] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 7:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            if _HEADER_TOKENS & set(texts):  # ヘッダ行
                continue

            code_cell = cells[1]
            code, pdf_url = self._extract_code(code_cell)
            if not code:
                # No 列とずれている可能性。全セルからコードを探す
                for c in cells:
                    code, pdf_url = self._extract_code(c)
                    if code:
                        break
            if not code:
                continue

            kind_text = texts[2]
            deal_type = "rent" if "賃" in kind_text else "sale"
            town_raw = texts[3]
            area_class = texts[4]
            price_text = texts[5]
            layout_text = texts[6]
            note = texts[7] if len(texts) > 7 else ""

            if normalize.looks_excluded(town_raw, layout_text, note, keywords=("土地", "宅地", "マンション", "アパート")):
                continue

            address = f"福井県あわら市{town_raw}"
            out.append(
                ScrapedListing(
                    source=self.name,
                    site_property_id=code,
                    url=pdf_url or f"{LIST_URL}#{code}",
                    deal_type=deal_type,
                    price=normalize.parse_price_yen(price_text, deal_type),
                    title=f"あわら市空き家バンク {code}（{town_raw}）",
                    property_type_raw="一戸建て(空き家バンク)",
                    address=address,
                    town=normalize.extract_town(address),
                    layout=normalize.parse_layout(layout_text),
                    station_walk_text="",
                    site_new_flag=False,
                    site_price_updated_flag=("値下げ" in note),
                    extra={
                        "area_class": area_class,
                        "note": note,
                        "under_negotiation": "商談中" in (note + code_cell.get_text()),
                        "pdf_url": pdf_url or "",
                    },
                )
            )
        return out

    @staticmethod
    def _extract_code(cell) -> tuple[str, str]:
        pdf_url = ""
        for a in cell.find_all("a", href=True):
            if a["href"].lower().endswith(".pdf"):
                pdf_url = urllib.parse.urljoin(LIST_URL, a["href"])
                break
        m = _CODE_RE.search(cell.get_text(" ", strip=True))
        code = m.group(1).strip("-") if m else ""
        return code, pdf_url

    # -- PDF 補完 ---------------------------------------------------------
    def _enrich_with_pdfs(self, rows: list[ScrapedListing]) -> None:
        try:
            import pdfplumber  # noqa: F401
        except Exception as exc:  # pragma: no cover
            self.log.info("pdfplumber を利用できないため PDF 補完をスキップ: %s", exc)
            return

        budget = config.MAX_DETAIL_FETCHES_PER_SITE
        for row in rows:
            if budget <= 0:
                break
            pdf_url = row.extra.get("pdf_url")
            if not pdf_url:
                continue
            price = row.price
            limit = config.SALE_MAX_PRICE if row.deal_type == "sale" else config.RENT_MAX_PRICE
            # 条件近辺のものだけ詳細取得（少し余裕を持たせる）
            if price is not None and price > int(limit * 1.4):
                continue
            budget -= 1
            try:
                self._apply_pdf(row, pdf_url)
            except Exception as exc:  # PDF 解析失敗は致命的でない
                self.log.warning("PDF 解析に失敗 %s: %s", pdf_url, exc)

    def _apply_pdf(self, row: ScrapedListing, pdf_url: str) -> None:
        import pdfplumber

        if not self.gate.allowed(pdf_url):
            return
        data = self.session.get(pdf_url).content
        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages[:3]:
                text_parts.append(page.extract_text() or "")
        text = normalize.to_halfwidth("\n".join(text_parts))
        row.extra["pdf_text_excerpt"] = text[:600]

        m = re.search(r"所在地?[:：]?\s*(福井県?\s*あわら市[^\n\r、。]+)", text)
        if m:
            addr = re.sub(r"\s+", "", m.group(1))
            row.address = addr
            row.town = normalize.extract_town(addr)

        m = re.search(r"土地面積[^\d]*([\d,\.]+)\s*(?:m2|m²|㎡|平米)", text)
        if m:
            row.land_area = normalize.parse_area_m2(m.group(1) + "m2")
        m = re.search(r"(?:建物面積|延床面積|床面積)[^\d]*([\d,\.]+)\s*(?:m2|m²|㎡|平米)", text)
        if m:
            row.building_area = normalize.parse_area_m2(m.group(1) + "m2")

        m = re.search(r"(?:築年月?|建築年月?|建築時期)[:：]?\s*([^\n\r]{0,20})", text)
        if m:
            by = normalize.parse_built_year(m.group(1))
            if by:
                row.built_year = by

        for alias in config.STATION_ALIASES:
            m = re.search(alias + r"[^\n\r]{0,15}?(?:徒歩|歩)\s*(\d+)\s*分", text)
            if m:
                row.station_walk_minutes = int(m.group(1))
                row.station_walk_text = f"{alias}駅 徒歩{m.group(1)}分（PDF）"
                break
            m = re.search(alias + r"[^\n\r]{0,15}?(\d{2,4})\s*m", text)
            if m:
                meters = int(m.group(1))
                row.station_walk_minutes = max(1, -(-meters // config.WALK_METERS_PER_MINUTE))
                row.station_walk_text = f"{alias}駅 約{meters}m（PDF）"
                break
