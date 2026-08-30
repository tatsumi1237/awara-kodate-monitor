"""LIFULL HOME'S スクレイパー（既定で無効）.

【無効の理由】
LIFULL HOME'S は、非ブラウザの User-Agent からのアクセスを HTTP 403 で
ブロックしている（honest な bot UA・curl・requests いずれも 403。ブラウザ
UA を詐称した場合のみ 200 が返る）。
これは「アクセス制限」であり、詐称による回避は行わない方針のため、
自動監視の対象外とする（利用規約 第16条 の「サービスの利用・提供を妨げる行為」
「営利目的の営業活動」等にも配慮）。

HOME'S 掲載の空き家物件は、あわら市公式ページ(awara スクレイパー)が実質的に
カバーする。市場物件は README の手動チェック用 URL を参照。

将来 HOME'S が公式 API / RSS を提供した場合、または bot アクセスを許可した
場合は、ここに実装を追加する。
"""
from __future__ import annotations

from awara_monitor.models import ScrapedListing

from .base import BaseScraper, ScraperDisabled

REASON = (
    "LIFULL HOME'S は非ブラウザ UA を HTTP 403 でブロックしているため、"
    "自動監視の対象外です（ブラウザ詐称による回避は行いません）。"
)


class HomesScraper(BaseScraper):
    name = "homes"
    label = "LIFULL HOME'S"
    enabled = False

    def fetch(self) -> list[ScrapedListing]:
        raise ScraperDisabled(REASON)
